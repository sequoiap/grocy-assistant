"""Pairing receipt lines with the items scanned during a trip.

Signals, strongest first:
  upc      the receipt prints a number that encodes the scanned barcode (Walmart)
  learned  this store's code/description was confirmed for this product before
  fuzzy    the description plausibly abbreviates the product's name
  ai       optional provider suggestion for whatever is left over
Manual matches made in the review screen are never overridden.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.base import AIError, AIProvider, MatchCandidate, MatchLine
from ..grocy.client import MasterData
from ..models import LearnedMapping, Receipt, ReceiptLine, Trip, TripItem
from .textmatch import best_name_score, normalize_key, upc_matches

log = logging.getLogger(__name__)

FUZZY_MIN = 0.55  # below this a name match isn't proposed at all
AUTO_METHODS = ("upc", "learned", "fuzzy")


def item_names(item: TripItem, md: MasterData) -> list[str]:
    """Every name we know this item by (Grocy name, draft name, lookup name)."""
    names: list[str] = []
    if item.product_id and item.product_id in md.products:
        names.append(md.products[item.product_id]["name"])
    if item.new_product:
        names.append(item.new_product.get("name", ""))
    if item.lookup and item.lookup.get("found"):
        names.append(item.lookup.get("suggested_name", ""))
        names.append(item.lookup.get("name", ""))
    return [n for n in names if n]


def _learned_index(db: Session, store_keys: set[str]) -> dict[tuple[str, str, str], int]:
    if not store_keys:
        return {}
    rows = db.scalars(select(LearnedMapping).where(LearnedMapping.store_key.in_(store_keys)))
    return {(m.store_key, m.kind, m.key): m.product_id for m in rows}


def learned_product(
    index: dict[tuple[str, str, str], int], store_key: str | None, line: ReceiptLine
) -> tuple[int, float] | None:
    """(product_id, score) if this line was mapped to a product on a previous trip."""
    if not store_key:
        return None
    if line.item_code:
        pid = index.get((store_key, "code", line.item_code))
        if pid is not None:
            return pid, 0.97
    key = normalize_key(line.description)
    if key:
        pid = index.get((store_key, "text", key))
        if pid is not None:
            return pid, 0.93
    return None


def learned_index_for_trip(db: Session, trip: Trip) -> dict[tuple[str, str, str], int]:
    return _learned_index(db, {r.store_key for r in trip.receipts if r.store_key})


def _open_lines(trip: Trip) -> list[tuple[Receipt, ReceiptLine]]:
    return [
        (receipt, line)
        for receipt in trip.receipts
        if receipt.status == "ready"
        for line in receipt.lines
        if not line.dismissed
    ]


def _untouched(item: TripItem) -> bool:
    """No manual overrides, so nothing is lost by recreating the item."""
    overrides = (
        item.quantity,
        item.line_total,
        item.due_date,
        item.location_id,
        item.shopping_location_id,
        item.note,
    )
    return all(value is None for value in overrides)


def rematch(db: Session, trip: Trip, md: MasterData) -> None:
    """Recompute automatic matches for the trip. Idempotent."""
    index = learned_index_for_trip(db, trip)

    # Receipt-born items whose line vanished (receipt deleted/reprocessed) go with it.
    # Untouched ones the matcher added itself are re-derived below, so that a
    # barcode scanned after the receipt was read can still claim its line.
    for item in list(trip.items):
        if item.source != "receipt" or item.status != "pending":
            continue
        if item.receipt_line_id is None or (item.match_method == "learned" and _untouched(item)):
            trip.items.remove(item)

    # Drop previous automatic matches; keep manual/AI ones and anything already booked.
    for item in trip.items:
        if (
            item.source != "receipt"
            and item.status in ("pending", "failed")
            and item.match_method in AUTO_METHODS
        ):
            item.receipt_line_id = None
            item.match_score = None
            item.match_method = None
    db.flush()

    taken = {i.receipt_line_id for i in trip.items if i.receipt_line_id is not None}
    lines = [(r, ln) for r, ln in _open_lines(trip) if ln.id not in taken]
    items = [
        i
        for i in trip.items
        if i.receipt_line_id is None
        and i.status in ("pending", "failed")
        and i.source != "receipt"
        and i.match_method != "manual"  # deliberately unmatched in the review screen
    ]

    candidates: list[tuple[float, str, ReceiptLine, TripItem]] = []
    for receipt, line in lines:
        learned = learned_product(index, receipt.store_key, line)
        for item in items:
            if upc_matches(line.item_code, item.barcode):
                candidates.append((1.0, "upc", line, item))
                continue
            if learned and item.product_id == learned[0]:
                candidates.append((learned[1], "learned", line, item))
                continue
            score = best_name_score(line.description, item_names(item, md))
            if score >= FUZZY_MIN:
                candidates.append((min(score, 0.9), "fuzzy", line, item))

    candidates.sort(key=lambda c: c[0], reverse=True)
    used_lines: set[int] = set()
    used_items: set[int] = set()
    for score, method, line, item in candidates:
        if line.id in used_lines or item.id in used_items:
            continue
        used_lines.add(line.id)
        used_items.add(item.id)
        item.receipt_line_id = line.id
        item.match_score = score
        item.match_method = method

    # Lines nobody scanned (produce, deli) that we've seen before become items on
    # their own, so repeat purchases need no manual work.
    for receipt, line in lines:
        if line.id in used_lines:
            continue
        learned = learned_product(index, receipt.store_key, line)
        if learned and learned[0] in md.products:
            trip.items.append(
                TripItem(
                    source="receipt",
                    product_id=learned[0],
                    receipt_line_id=line.id,
                    match_score=learned[1],
                    match_method="learned",
                )
            )
    db.flush()


async def ai_rematch(db: Session, trip: Trip, md: MasterData, provider: AIProvider) -> int:
    """Ask the provider to place leftovers. Returns the number of matches applied."""
    taken = {i.receipt_line_id for i in trip.items if i.receipt_line_id is not None}
    lines = {ln.id: (r, ln) for r, ln in _open_lines(trip) if ln.id not in taken}
    items = {
        i.id: i
        for i in trip.items
        if i.receipt_line_id is None
        and i.status in ("pending", "failed")
        and i.match_method != "manual"
        and item_names(i, md)
    }
    if not lines or not items:
        return 0

    applied = 0
    by_store: dict[str | None, list[ReceiptLine]] = {}
    for receipt, line in lines.values():
        by_store.setdefault(receipt.store_name, []).append(line)
    for store_name, store_lines in by_store.items():
        remaining = [i for i in items.values() if i.receipt_line_id is None]
        if not remaining:
            break
        try:
            matches = await provider.match_lines(
                store_name,
                [
                    MatchLine(ln.id, ln.description, ln.item_code, ln.total_price)
                    for ln in store_lines
                ],
                [MatchCandidate(i.id, item_names(i, md)[0], i.barcode) for i in remaining],
            )
        except AIError as exc:
            log.warning("AI matching failed: %s", exc)
            continue
        seen_lines: set[int] = set()
        for m in sorted(matches, key=lambda m: m.confidence, reverse=True):
            item = items.get(m.candidate_id)
            if (
                item is None
                or item.receipt_line_id is not None
                or m.line_id not in lines
                or m.line_id in seen_lines
                or m.confidence < 0.5
            ):
                continue
            seen_lines.add(m.line_id)
            item.receipt_line_id = m.line_id
            item.match_score = round(min(max(m.confidence, 0.0), 1.0) * 0.9, 3)
            item.match_method = "ai"
            applied += 1
    db.flush()
    return applied
