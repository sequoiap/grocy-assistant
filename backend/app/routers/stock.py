"""Consuming and opening what's already in stock, straight in Grocy.

Nothing is kept here: every call reads or books stock in Grocy under the signed-in
person's own API key, the same as Grocy's own Consume page would. Amounts are in
each product's stock unit."""

from fastapi import APIRouter, Depends

from ..config import get_config
from ..deps import get_grocy
from ..errors import GROCY_UNREACHABLE, ApiError
from ..grocy.client import NEVER_DUE, GrocyClient, GrocyError, GrocyUnreachable, MasterData
from ..schemas import StockActionIn, StockActionOut, StockProduct, StockScanIn, StockUndoIn

router = APIRouter(prefix="/api/stock", tags=["stock"])


def _unreachable() -> ApiError:
    return ApiError(
        503,
        "Grocy is unreachable right now, so nothing was changed. Try again in a moment.",
        GROCY_UNREACHABLE,
    )


def _refused(exc: GrocyError) -> ApiError:
    """Grocy said no to an action (not enough in stock, a missing permission, …).
    Its own words are the clearest explanation there is."""
    if exc.status == 403:
        return ApiError(403, "Your Grocy account isn't allowed to change stock.")
    detail = exc.message
    if detail.startswith("Grocy error"):
        detail = detail.split("): ", 1)[-1]
    return ApiError(409, f"Grocy refused: {detail}")


async def _call(coro):
    """Runs a Grocy call, turning an outage or a refusal into an answer for the PWA.
    A rejected key (401) is left to the app-wide handler, which signs the person out."""
    try:
        return await coro
    except GrocyUnreachable:
        raise _unreachable() from None
    except GrocyError as exc:
        if exc.status == 401 or exc.status is None or exc.status >= 500:
            raise
        raise _refused(exc) from None


async def _md(grocy: GrocyClient) -> MasterData:
    return await _call(grocy.master_data(get_config().grocy_cache_seconds))


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _due(value) -> str | None:
    if not value:
        return None
    value = str(value)[:10]
    return "never" if value >= NEVER_DUE else value


def _location(md: MasterData, location_id) -> str | None:
    for loc in md.locations:
        if str(loc.get("id")) == str(location_id):
            return loc["name"]
    return None


def _stock_product(
    md: MasterData,
    product: dict,
    *,
    amount: float,
    opened: float,
    due,
) -> StockProduct:
    unit = md.quantity_units.get(int(product.get("qu_id_stock") or -1)) or {}
    quick = _num(product.get("quick_consume_amount"), 1.0) or 1.0
    return StockProduct(
        id=int(product["id"]),
        name=product["name"],
        amount=round(amount, 4),
        amount_opened=round(opened, 4),
        unit=unit.get("name", ""),
        unit_plural=unit.get("name_plural") or unit.get("name", ""),
        next_due_date=_due(due) if amount > 0 else None,
        location=_location(md, product.get("location_id")),
        quick_consume_amount=quick,
        quick_open_amount=_num(product.get("quick_open_amount"), quick) or quick,
        allow_partial=bool(int(product.get("allow_partial_units_in_stock") or 0)),
        tare_weight_handling=bool(int(product.get("enable_tare_weight_handling") or 0)),
    )


async def _product_now(grocy: GrocyClient, md: MasterData, product_id: int) -> StockProduct:
    """One product as Grocy has it this moment (not from the cached snapshot)."""
    details = await _call(grocy.product_details(product_id))
    product = details.get("product") or md.products.get(product_id)
    if not product:
        raise ApiError(404, "Grocy has no such product.")
    aggregated = bool(int(details.get("is_aggregated_amount") or 0))
    amount = details.get("stock_amount_aggregated" if aggregated else "stock_amount")
    opened = details.get("stock_amount_opened_aggregated" if aggregated else "stock_amount_opened")
    return _stock_product(
        md,
        product,
        amount=_num(amount),
        opened=_num(opened),
        due=details.get("next_due_date"),
    )


@router.get("", response_model=list[StockProduct])
async def in_stock(grocy: GrocyClient = Depends(get_grocy)):
    """Everything Grocy has in stock right now, by name, for searching on the phone."""
    md = await _md(grocy)
    rows = await _call(grocy.current_stock())
    out: list[StockProduct] = []
    for row in rows:
        try:
            pid = int(row["product_id"])
        except (KeyError, TypeError, ValueError):
            continue
        product = row.get("product") or md.products.get(pid)
        if not product or not int(product.get("active", 1) or 0):
            continue
        aggregated = bool(int(row.get("is_aggregated_amount") or 0))
        amount = _num(row.get("amount_aggregated" if aggregated else "amount"))
        if amount <= 0:
            continue
        opened = _num(row.get("amount_opened_aggregated" if aggregated else "amount_opened"))
        out.append(
            _stock_product(
                md, product, amount=amount, opened=opened, due=row.get("best_before_date")
            )
        )
    out.sort(key=lambda p: p.name.lower())
    return out


@router.post("/scan", response_model=StockProduct)
async def scan(body: StockScanIn, grocy: GrocyClient = Depends(get_grocy)):
    """Which product a barcode (or Grocycode label) is, and how much of it is in stock."""
    code = body.barcode.strip()
    md = await _md(grocy)
    entry_id: str | None = None
    pack: float | None = None
    if code.lower().startswith("grcy:p:"):
        # A label printed by Grocy: grcy:p:<product id>[:<stock entry id>]
        parts = code.split(":")
        try:
            product_id = int(parts[2])
        except (IndexError, ValueError):
            raise ApiError(404, "That Grocycode label isn't one for a product.") from None
        entry_id = parts[3] if len(parts) > 3 and parts[3] else None
    else:
        row = md.find_barcode(code)
        if row is None and await _call(grocy.find_barcode_live(code)) is not None:
            md = await _call(grocy.master_data(force=True))  # just added in Grocy
            row = md.find_barcode(code)
        if row is None:
            raise ApiError(404, f"No product in Grocy has the barcode {code}.")
        product_id = int(row["product_id"])
        if _num(row.get("amount")) > 0:
            stock_unit = (md.products.get(product_id) or {}).get("qu_id_stock")
            factor = md.conversion(product_id, row.get("qu_id") or stock_unit, stock_unit)
            pack = round(_num(row["amount"]) * factor, 4)
    product = await _product_now(grocy, md, product_id)
    if pack is not None and pack != product.quick_consume_amount:
        product.pack_amount = pack
    product.stock_entry_id = entry_id
    return product


def _check(product: StockProduct, body: StockActionIn) -> None:
    if product.tare_weight_handling:
        raise ApiError(
            409, f"{product.name} is weighed in its container. Consume it in Grocy itself."
        )
    if not product.allow_partial and body.amount != int(body.amount):
        raise ApiError(422, f"{product.name} is counted in whole {product.unit_plural.lower()}.")


def _transaction(rows) -> str | None:
    for row in rows or []:
        if isinstance(row, dict) and row.get("transaction_id"):
            return str(row["transaction_id"])
    return None


@router.post("/products/{product_id}/consume", response_model=StockActionOut)
async def consume(product_id: int, body: StockActionIn, grocy: GrocyClient = Depends(get_grocy)):
    md = await _md(grocy)
    _check(await _product_now(grocy, md, product_id), body)
    rows = await _call(
        grocy.consume_stock(
            product_id, amount=body.amount, spoiled=body.spoiled, stock_entry_id=body.stock_entry_id
        )
    )
    return StockActionOut(
        transaction_id=_transaction(rows), product=await _product_now(grocy, md, product_id)
    )


@router.post("/products/{product_id}/open", response_model=StockActionOut)
async def open_stock(product_id: int, body: StockActionIn, grocy: GrocyClient = Depends(get_grocy)):
    md = await _md(grocy)
    _check(await _product_now(grocy, md, product_id), body)
    rows = await _call(
        grocy.open_stock(product_id, amount=body.amount, stock_entry_id=body.stock_entry_id)
    )
    return StockActionOut(
        transaction_id=_transaction(rows), product=await _product_now(grocy, md, product_id)
    )


@router.post("/undo", status_code=204)
async def undo(body: StockUndoIn, grocy: GrocyClient = Depends(get_grocy)):
    """Takes back a consume or open, as Grocy's own "Undo" in its stock journal does."""
    await _call(grocy.undo_transaction(body.transaction_id))
