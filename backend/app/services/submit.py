"""Booking a reviewed trip into Grocy, one item at a time.

Every step that changes Grocy is recorded on the item straight away, so a
partial failure can simply be retried: products that were already created or
stock that was already booked is never repeated.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..grocy.client import GrocyClient, GrocyError, GrocyUnreachable
from ..models import LearnedMapping, StoreMapping, Trip, TripItem, utcnow
from .textmatch import normalize_key
from .trips import draft_pack, resolve_item

log = logging.getLogger(__name__)


def _about_grocy_not_the_item(exc: GrocyError) -> bool:
    """Grocy being down, or no longer accepting this user's key, says nothing about
    the item being booked. Those stop the whole submit/undo and are reported as
    such, with the trip left as it is, rather than recorded as the item's error."""
    return isinstance(exc, GrocyUnreachable) or exc.status == 401


def _learn(db: Session, store_key: str, kind: str, key: str, product_id: int) -> None:
    if not key:
        return
    row = db.scalar(
        select(LearnedMapping).where(
            LearnedMapping.store_key == store_key,
            LearnedMapping.kind == kind,
            LearnedMapping.key == key,
        )
    )
    if row is None:
        db.add(LearnedMapping(store_key=store_key, kind=kind, key=key, product_id=product_id))
    elif row.product_id == product_id:
        row.hits += 1
    else:
        row.product_id, row.hits = product_id, 1


def learn_from_item(db: Session, item: TripItem) -> None:
    """Remember how this store prints this product, for next time."""
    line = item.receipt_line
    if line is None or item.product_id is None:
        return
    receipt = line.receipt
    if not receipt.store_key:
        return
    if line.item_code:
        _learn(db, receipt.store_key, "code", line.item_code, item.product_id)
    _learn(db, receipt.store_key, "text", normalize_key(line.description), item.product_id)
    if receipt.shopping_location_id:
        mapping = db.get(StoreMapping, receipt.store_key)
        if mapping is None:
            db.add(
                StoreMapping(
                    store_key=receipt.store_key,
                    shopping_location_id=receipt.shopping_location_id,
                )
            )


async def _ensure_product(db: Session, grocy: GrocyClient, item: TripItem) -> None:
    """Create the drafted product and/or attach the scanned barcode, once."""
    if item.product_id is None and item.new_product:
        draft = item.new_product
        days = int(draft.get("default_best_before_days") or 0)
        body = {
            "name": draft["name"],
            "location_id": draft["location_id"],
            "qu_id_stock": draft["qu_id"],
            "qu_id_purchase": draft["qu_id"],
            "qu_id_consume": draft["qu_id"],
            "qu_id_price": draft["qu_id"],
            "default_best_before_days": days if days > 0 else -1,
        }
        if draft.get("product_group_id"):
            body["product_group_id"] = draft["product_group_id"]
        try:
            item.product_id = await grocy.create_object("products", body)
        except GrocyError as exc:
            if exc.status != 400:
                raise
            # Older Grocy versions don't know the consume/price unit columns.
            body.pop("qu_id_consume")
            body.pop("qu_id_price")
            item.product_id = await grocy.create_object("products", body)
        item.link_barcode = bool(item.barcode)
        db.commit()

    # Sold in packs: add the pack conversion and make the pack the purchase unit. Each
    # step checks Grocy first, so a submit that stopped part-way finishes here next time.
    pack = draft_pack(item.new_product) if item.product_id is not None else None
    if pack:
        pack_qu, size = pack
        md = await grocy.master_data(force=True)
        product = md.products.get(item.product_id)
        if product is not None:
            stock_qu = int(product["qu_id_stock"])
            if (item.product_id, pack_qu, stock_qu) not in md.conversions:
                await grocy.create_object(
                    "quantity_unit_conversions",
                    {
                        "product_id": item.product_id,
                        "from_qu_id": pack_qu,
                        "to_qu_id": stock_qu,
                        "factor": size,
                    },
                )
            if int(product.get("qu_id_purchase") or 0) != pack_qu:
                body = {"qu_id_purchase": pack_qu, "qu_id_price": pack_qu}
                try:
                    await grocy.update_object("products", item.product_id, body)
                except GrocyError as exc:
                    if exc.status != 400:
                        raise
                    body.pop("qu_id_price")  # older Grocy: no price unit column
                    await grocy.update_object("products", item.product_id, body)

    if item.link_barcode and item.barcode and item.product_id is not None:
        md = await grocy.master_data(force=True)
        if md.find_barcode(item.barcode) is None:
            barcode = {"product_id": item.product_id, "barcode": item.barcode}
            if pack:
                barcode |= {"qu_id": pack[0], "amount": 1}  # the barcode is on the pack
            await grocy.create_object("product_barcodes", barcode)
        item.link_barcode = False
        db.commit()


def _booked(item: TripItem) -> list[str]:
    ids = list(item.transaction_ids or [])
    if item.transaction_id and item.transaction_id not in ids:
        ids.insert(0, item.transaction_id)  # booked by a version before transaction_ids
    return ids


async def _take_back(db: Session, grocy: GrocyClient, item: TripItem) -> None:
    """Undo whatever this item has booked, newest first, recording each as it goes.
    Raises on the first one Grocy refuses, leaving the rest recorded for next time.
    Stock that Grocy merged these bookings into stays (see take_back_addition)."""
    ids = _booked(item)
    while ids:
        await grocy.take_back_addition(ids[-1])
        ids.pop()
        item.transaction_ids = list(ids)
        item.transaction_id = ids[0] if ids else None
        db.commit()


async def _book(db: Session, grocy: GrocyClient, item: TripItem, trip: Trip, resolved) -> None:
    """Book every stock entry of one item (one per due date), or none of them: if a
    later one fails, the earlier ones are taken back out before the error goes on."""
    kind = "inventory-correction" if trip.kind == "inventory" else "purchase"
    try:
        for amount, best_before in resolved.bookings():
            rows = await grocy.add_stock(
                resolved.product_id,
                amount=amount,
                best_before_date=best_before,
                price=resolved.unit_price,
                location_id=resolved.location_id,
                shopping_location_id=resolved.shopping_location_id,
                note=item.note,
                transaction_type=kind,
            )
            tid = rows[0].get("transaction_id") if rows else None
            if tid:
                item.transaction_ids = [*(item.transaction_ids or []), tid]
                item.transaction_id = item.transaction_ids[0]
                db.commit()
    except GrocyError:
        try:
            await _take_back(db, grocy, item)
        except GrocyError as undo_exc:
            log.warning("couldn't take back part of item %s: %s", item.id, undo_exc)
        raise


async def submit_trip(db: Session, grocy: GrocyClient, trip: Trip) -> tuple[int, int, int]:
    """Returns (committed, failed, remaining).

    Raises GrocyError if Grocy stops answering (or rejects the key) part-way.
    Items booked before that point stay booked and recorded; the rest are untouched,
    so submitting again later picks up where this left off."""
    committed = failed = 0
    for item in trip.items:
        if item.status not in ("pending", "failed"):
            continue
        md = await grocy.master_data()
        if resolve_item(item, trip, md).state == "needs_product":
            continue
        try:
            # Left over from an earlier attempt that couldn't be rolled back then.
            await _take_back(db, grocy, item)
            await _ensure_product(db, grocy, item)
            md = await grocy.master_data()
            resolved = resolve_item(item, trip, md)
            if resolved.product_id is None or resolved.stock_amount <= 0:
                if not md.reachable:
                    # An old snapshot can't know a product created a moment ago.
                    raise GrocyUnreachable("Grocy stopped answering while booking this item")
                raise GrocyError("Nothing to add: the product or amount is missing")
            await _book(db, grocy, item, trip, resolved)
            item.committed_amount = resolved.stock_amount
            item.status, item.error = "committed", None
            learn_from_item(db, item)
            committed += 1
        except GrocyError as exc:
            if _about_grocy_not_the_item(exc):
                raise
            log.warning("submit of item %s failed: %s", item.id, exc)
            item.status, item.error = "failed", exc.message
            failed += 1
        db.commit()

    remaining = sum(1 for i in trip.items if i.status in ("pending", "failed"))
    if remaining == 0 and any(i.status == "committed" for i in trip.items):
        trip.status = "submitted"
        trip.submitted_at = utcnow()
    db.commit()
    return committed, failed, remaining - failed


async def undo_trip(db: Session, grocy: GrocyClient, trip: Trip) -> int:
    """Reverse every stock booking this trip made. Created products are kept."""
    undone = 0
    for item in trip.items:
        if item.status != "committed":
            continue
        try:
            await _take_back(db, grocy, item)
        except GrocyError as exc:
            if _about_grocy_not_the_item(exc):
                raise
            item.error = f"Undo failed: {exc.message}"
            db.commit()
            continue
        item.status, item.error = "pending", None
        item.transaction_id = item.committed_amount = None
        item.transaction_ids = None
        undone += 1
        db.commit()
    if any(i.status != "committed" for i in trip.items):
        trip.status, trip.submitted_at = "open", None
    db.commit()
    return undone
