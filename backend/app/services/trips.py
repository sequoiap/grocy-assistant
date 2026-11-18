"""Turning stored trip rows into what the review screen shows and what gets sent
to Grocy. Overrides stored on an item win; everything else is derived here from
the matched receipt line and Grocy's own product defaults."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from rapidfuzz import fuzz, process, utils
from sqlalchemy.orm import Session

from ..grocy.client import NEVER_DUE, MasterData
from ..models import Receipt, ReceiptLine, Trip, TripItem
from ..schemas import (
    IdName,
    ItemOut,
    LookupOut,
    NewProductDefaults,
    NewProductDraft,
    ProductHit,
    ReceiptImageOut,
    ReceiptLineOut,
    ReceiptOut,
    TripOut,
    TripSummary,
)
from .matching import learned_index_for_trip, learned_product

_WEIGHT_UNITS = {
    "lb": {"lb", "lbs", "pound", "pounds"},
    "oz": {"oz", "ounce", "ounces"},
    "kg": {"kg", "kilogram", "kilograms", "kilo", "kilos"},
    "g": {"g", "gram", "grams"},
}


@dataclass
class Resolved:
    """Everything derived for one item; shared by the API output and the submit."""

    name: str
    state: str
    product_id: int | None
    quantity: float
    quantity_source: str
    pack_factor: float
    pack_unit: str
    stock_amount: float
    stock_unit: str
    line_total: float | None
    price_source: str | None
    unit_price: float | None
    due_date: str  # ISO or "never"
    due_source: str
    location_id: int | None
    shopping_location_id: int | None
    warnings: list[str]

    @property
    def best_before_date(self) -> str:
        return NEVER_DUE if self.due_date == "never" else self.due_date


def _unit_is_weight(unit_name: str, weight_unit: str | None) -> bool:
    return bool(weight_unit) and unit_name.strip().lower() in _WEIGHT_UNITS.get(weight_unit, set())


def draft_pack(draft: dict | None) -> tuple[int, float] | None:
    """(pack unit id, stock units per pack) for a new product sold in packs, else None."""
    if not draft or not draft.get("pack_qu_id") or not draft.get("pack_size"):
        return None
    return int(draft["pack_qu_id"]), float(draft["pack_size"])


def default_due(days: int | None) -> str:
    return (date.today() + timedelta(days=days)).isoformat() if days and days > 0 else "never"


def resolve_item(item: TripItem, trip: Trip, md: MasterData) -> Resolved:
    line: ReceiptLine | None = item.receipt_line
    receipt: Receipt | None = line.receipt if line else None
    product = md.products.get(item.product_id) if item.product_id else None
    draft = item.new_product if not product else None
    warnings: list[str] = []

    # -- product, units, pack size -----------------------------------------
    pack_factor, pack_unit, stock_unit_id, due_days, default_location = 1.0, "", None, 0, None
    if product:
        name = product["name"]
        pid = int(product["id"])
        stock_unit_id = product.get("qu_id_stock")
        purchase_unit_id = product.get("qu_id_purchase") or stock_unit_id
        bc = md.find_barcode(item.barcode) if item.barcode else None
        if bc and int(bc["product_id"]) == pid and bc.get("amount"):
            # This barcode is a known pack size (e.g. a 6-pack of the product).
            bc_unit = bc.get("qu_id") or stock_unit_id
            pack_factor = float(bc["amount"]) * md.conversion(pid, bc_unit, stock_unit_id)
            pack_unit = "pack"
        else:
            pack_factor = md.conversion(pid, purchase_unit_id, stock_unit_id)
            pack_unit = md.qu_name(purchase_unit_id)
        due_days = int(product.get("default_best_before_days") or 0)
        default_location = product.get("location_id")
    elif draft:
        name = draft["name"]
        stock_unit_id = draft.get("qu_id")
        pack = draft_pack(draft)
        if pack:
            pack_unit, pack_factor = md.qu_name(pack[0]), pack[1]
        else:
            pack_unit = md.qu_name(stock_unit_id)
        due_days = int(draft.get("default_best_before_days") or 0)
        default_location = draft.get("location_id")
    else:
        lookup_name = (item.lookup or {}).get("suggested_name")
        name = lookup_name or (line.description if line else None) or item.barcode or "Unknown"

    if item.status in ("committed", "failed", "skipped"):
        state = item.status
    elif product or draft:
        state = "ready"
    else:
        state = "needs_product"
        if item.product_id and not product:
            warnings.append("The linked product no longer exists in Grocy")

    # -- quantity -----------------------------------------------------------
    stock_unit_name = md.qu_name(stock_unit_id)
    sold_by_weight = bool(line and line.weight) and _unit_is_weight(
        stock_unit_name, line.weight_unit if line else None
    )
    if item.quantity is not None:
        quantity, quantity_source = item.quantity, "manual"
    elif sold_by_weight:
        # Stock is tracked by weight and the receipt printed the weight: use it as is.
        quantity, quantity_source, pack_factor, pack_unit = line.weight, "receipt", 1.0, ""
    elif line:
        quantity, quantity_source = line.quantity or 1.0, "receipt"
    elif item.scan_count > 1:
        quantity, quantity_source = float(item.scan_count), "scans"
    else:
        quantity, quantity_source = 1.0, "default"
    stock_amount = round(quantity * pack_factor, 4)

    # -- price --------------------------------------------------------------
    if item.line_total is not None:
        line_total, price_source = item.line_total, "manual"
    elif line and line.total_price is not None:
        line_total, price_source = line.total_price, "receipt"
    else:
        line_total, price_source = None, None
    unit_price = (
        round(line_total / stock_amount, 4) if line_total is not None and stock_amount > 0 else None
    )

    # -- due date, location, store -------------------------------------------
    if item.due_date:
        due_date, due_source = item.due_date, "manual"
    else:
        due_date, due_source = default_due(due_days), "default"
    location_id = item.location_id or default_location
    if item.shopping_location_id is not None:
        store_id = item.shopping_location_id
    elif receipt is not None:
        store_id = receipt.shopping_location_id
    else:
        # Not on any receipt: if the whole trip was one store, it came from there.
        ready = [r for r in trip.receipts if r.status == "ready"]
        store_id = ready[0].shopping_location_id if len(ready) == 1 else None

    # -- things worth a second look -------------------------------------------
    if state in ("ready", "needs_product"):
        has_receipts = any(r.status == "ready" for r in trip.receipts)
        if line is None and has_receipts and item.quantity is None:
            warnings.append("Not found on a receipt, so quantity and price are guesses")
        if (
            line is not None
            and item.match_method in ("fuzzy", "ai")
            and (item.match_score or 0) < 0.75
        ):
            warnings.append("Receipt match is a guess; check it's the right line")
        if line is not None and line.weight and not sold_by_weight and item.quantity is None:
            warnings.append(
                f"Sold by weight ({line.weight:g} {line.weight_unit or ''}); counted as 1".strip()
            )

    return Resolved(
        name=name,
        state=state,
        product_id=int(product["id"]) if product else None,
        quantity=quantity,
        quantity_source=quantity_source,
        pack_factor=pack_factor,
        pack_unit=pack_unit,
        stock_amount=stock_amount,
        stock_unit=md.qu_name(stock_unit_id, stock_amount),
        line_total=line_total,
        price_source=price_source,
        unit_price=unit_price,
        due_date=due_date,
        due_source=due_source,
        location_id=location_id,
        shopping_location_id=store_id,
        warnings=warnings,
    )


def suggest_products(query: str, md: MasterData, limit: int = 5, cutoff: float = 55) -> list:
    """Existing Grocy products whose name resembles `query`."""
    if not query.strip():
        return []
    names = {pid: p["name"] for pid, p in md.products.items() if int(p.get("active", 1) or 0)}
    hits = process.extract(
        query,
        names,
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        limit=limit,
        score_cutoff=cutoff,
    )
    return [ProductHit(id=pid, name=name, score=round(score / 100, 3)) for name, score, pid in hits]


def item_out(item: TripItem, trip: Trip, md: MasterData) -> ItemOut:
    r = resolve_item(item, trip, md)
    suggestions: list[ProductHit] = []
    if r.state == "needs_product":
        query = (item.lookup or {}).get("name") or ""
        if not query and item.receipt_line:
            query = item.receipt_line.description
        suggestions = suggest_products(query, md, limit=3, cutoff=70)
    product = md.products.get(item.product_id) if item.product_id else None
    return ItemOut(
        id=item.id,
        source=item.source,
        barcode=item.barcode,
        scan_count=item.scan_count,
        state=r.state,
        name=r.name,
        product=IdName(id=int(product["id"]), name=product["name"]) if product else None,
        link_barcode=item.link_barcode,
        new_product=NewProductDraft(**item.new_product) if item.new_product else None,
        lookup=LookupOut(**item.lookup) if item.lookup else None,
        suggestions=suggestions,
        quantity=r.quantity,
        quantity_source=r.quantity_source,
        pack_factor=r.pack_factor,
        pack_unit=r.pack_unit,
        stock_amount=r.stock_amount,
        stock_unit=r.stock_unit,
        line_total=r.line_total,
        price_source=r.price_source,
        unit_price=r.unit_price,
        due_date=r.due_date,
        due_source=r.due_source,
        location_id=r.location_id,
        shopping_location_id=r.shopping_location_id,
        note=item.note,
        receipt_line_id=item.receipt_line_id,
        match_score=item.match_score,
        match_method=item.match_method,
        warnings=r.warnings,
        error=item.error,
        committed_amount=item.committed_amount,
    )


def receipt_out(receipt: Receipt, trip: Trip, md: MasterData, learned: dict) -> ReceiptOut:
    matched = {i.receipt_line_id: i.id for i in trip.items if i.receipt_line_id is not None}
    lines = []
    for line in receipt.lines:
        suggestion = None
        if line.id not in matched and not line.dismissed:
            hit = learned_product(learned, receipt.store_key, line)
            if hit and hit[0] in md.products:
                suggestion = IdName(id=hit[0], name=md.products[hit[0]]["name"])
        lines.append(
            ReceiptLineOut(
                id=line.id,
                receipt_id=receipt.id,
                position=line.position,
                description=line.description,
                raw_text=line.raw_text,
                item_code=line.item_code,
                quantity=line.quantity,
                unit_price=line.unit_price,
                total_price=line.total_price,
                discount=line.discount,
                weight=line.weight,
                weight_unit=line.weight_unit,
                dismissed=line.dismissed,
                matched_item_id=matched.get(line.id),
                suggested_product=suggestion,
            )
        )
    return ReceiptOut(
        id=receipt.id,
        status=receipt.status,
        store_key=receipt.store_key,
        store_name=receipt.store_name,
        shopping_location_id=receipt.shopping_location_id,
        purchased_on=receipt.purchased_on,
        subtotal=receipt.subtotal,
        tax=receipt.tax,
        total=receipt.total,
        method=receipt.method,
        confidence=receipt.confidence,
        warnings=list(receipt.warnings or []),
        error=receipt.error,
        images=[
            ReceiptImageOut(id=img.id, url=f"/api/receipts/{receipt.id}/images/{img.id}")
            for img in receipt.images
        ],
        lines=lines,
    )


def trip_summary(trip: Trip) -> TripSummary:
    totals = [r.total for r in trip.receipts if r.total is not None]
    stores: list[str] = []
    for r in trip.receipts:
        if r.store_name and r.store_name not in stores:
            stores.append(r.store_name)
    return TripSummary(
        id=trip.id,
        name=trip.name,
        status=trip.status,
        created_at=trip.created_at,
        submitted_at=trip.submitted_at,
        created_by=trip.user.username,
        item_count=len(trip.items),
        receipt_count=len(trip.receipts),
        stores=stores,
        total=round(sum(totals), 2) if totals else None,
        revision=trip.revision or 0,
    )


def trip_out(db: Session, trip: Trip, md: MasterData, ai_available: bool) -> TripOut:
    learned = learned_index_for_trip(db, trip)
    items = [item_out(i, trip, md) for i in trip.items]
    return TripOut(
        **trip_summary(trip).model_dump(),
        items=items,
        receipts=[receipt_out(r, trip, md, learned) for r in trip.receipts],
        processing=any(r.status == "processing" for r in trip.receipts),
        ready_count=sum(1 for i in items if i.state == "ready"),
        attention_count=sum(1 for i in items if i.state == "needs_product"),
        ai_available=ai_available,
        grocy_reachable=md.reachable,
    )


def new_product_defaults(md: MasterData) -> NewProductDefaults:
    """Grocy's own "presets for new products" user settings, with sane fallbacks."""

    def preset(key: str, valid: set[int]) -> int | None:
        try:
            value = int(md.presets.get(key) or -1)
        except (TypeError, ValueError):
            return None
        return value if value in valid else None

    location_ids = {int(x["id"]) for x in md.locations}
    unit_ids = set(md.quantity_units)
    group_ids = {int(g["id"]) for g in md.product_groups}
    try:
        due_days = int(md.presets.get("product_presets_default_due_days") or 0)
    except (TypeError, ValueError):
        due_days = 0
    return NewProductDefaults(
        location_id=preset("product_presets_location_id", location_ids)
        or (min(location_ids) if location_ids else None),
        qu_id=preset("product_presets_qu_id", unit_ids) or (min(unit_ids) if unit_ids else None),
        product_group_id=preset("product_presets_product_group_id", group_ids),
        default_best_before_days=due_days,
    )
