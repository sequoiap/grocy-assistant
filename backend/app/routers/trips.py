from datetime import date

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.base import AIProvider
from ..config import get_config
from ..db import get_db
from ..deps import current_user, get_ai, get_grocy, get_http
from ..grocy.client import GrocyClient, MasterData, barcode_variants
from ..lookup.openfoodfacts import lookup_barcode
from ..models import Receipt, ReceiptImage, ReceiptLine, StoreMapping, Trip, TripItem, User
from ..schemas import (
    ItemCreate,
    ItemPatch,
    LineItemCreate,
    LinePatch,
    NewProductDraft,
    ReceiptPatch,
    ReprocessIn,
    RevisionOut,
    ScanIn,
    ScanOut,
    SubmitResult,
    TripCreate,
    TripOut,
    TripPatch,
    TripSummary,
)
from ..services import matching
from ..services.receipts import image_path, save_upload, schedule_processing
from ..services.submit import submit_trip, undo_trip
from ..services.trips import item_out, trip_out, trip_summary

router = APIRouter(prefix="/api", tags=["trips"])


# --- helpers -------------------------------------------------------------------


async def _md(grocy: GrocyClient) -> MasterData:
    return await grocy.master_data(get_config().grocy_cache_seconds)


def _trip(db: Session, trip_id: int) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "No such trip")
    return trip


def _open_trip(db: Session, trip_id: int) -> Trip:
    trip = _trip(db, trip_id)
    if trip.status != "open":
        raise HTTPException(409, "This trip was already added to Grocy. Undo it to make changes.")
    return trip


def _item(trip: Trip, item_id: int) -> TripItem:
    for item in trip.items:
        if item.id == item_id:
            return item
    raise HTTPException(404, "No such item")


def _editable(item: TripItem) -> None:
    if item.status == "committed":
        raise HTTPException(409, "This item is already in Grocy")


def _receipt(db: Session, receipt_id: int) -> Receipt:
    receipt = db.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(404, "No such receipt")
    if receipt.trip.status != "open":
        raise HTTPException(409, "This trip was already added to Grocy. Undo it to make changes.")
    return receipt


def _line(db: Session, line_id: int) -> ReceiptLine:
    line = db.get(ReceiptLine, line_id)
    if line is None:
        raise HTTPException(404, "No such receipt line")
    if line.receipt.trip.status != "open":
        raise HTTPException(409, "This trip was already added to Grocy. Undo it to make changes.")
    return line


def _validate_draft(draft: NewProductDraft, md: MasterData) -> dict:
    if not any(int(loc["id"]) == draft.location_id for loc in md.locations):
        raise HTTPException(422, "Pick a location that exists in Grocy")
    if draft.qu_id not in md.quantity_units:
        raise HTTPException(422, "Pick a quantity unit that exists in Grocy")
    if (draft.pack_size is None) != (draft.pack_qu_id is None):
        raise HTTPException(422, "A pack needs both a size and a unit")
    if draft.pack_qu_id is not None:
        if draft.pack_qu_id not in md.quantity_units:
            raise HTTPException(422, "Pick a pack unit that exists in Grocy")
        if draft.pack_qu_id == draft.qu_id:
            raise HTTPException(422, "The pack unit must differ from the unit it's counted in")
    wanted = draft.name.strip().lower()
    if any(p["name"].strip().lower() == wanted for p in md.products.values()):
        raise HTTPException(409, f'Grocy already has a product named "{draft.name.strip()}"')
    data = draft.model_dump()
    data["name"] = draft.name.strip()
    return data


def _set_product(item: TripItem, product_id: int, md: MasterData) -> None:
    if product_id not in md.products:
        raise HTTPException(422, "That product doesn't exist in Grocy")
    item.product_id = product_id
    item.new_product = None
    # An unknown barcode linked to an existing product gets attached to it at submit.
    item.link_barcode = bool(item.barcode) and md.find_barcode(item.barcode) is None


def _validate_due(value: str) -> str:
    if value == "never":
        return value
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(422, 'Due date must be YYYY-MM-DD or "never"') from exc


def _respond(db: Session, trip: Trip, md: MasterData, ai: AIProvider | None) -> TripOut:
    db.commit()
    db.refresh(trip)
    return trip_out(db, trip, md, ai is not None)


# --- trips ---------------------------------------------------------------------


@router.get("/trips", response_model=list[TripSummary])
def list_trips(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """All household trips, newest first."""
    trips = db.scalars(select(Trip).order_by(Trip.created_at.desc()).limit(100))
    return [trip_summary(t) for t in trips]


@router.post("/trips", response_model=TripOut, status_code=201)
async def create_trip(
    body: TripCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    trip = Trip(user_id=user.id, name=body.name.strip())
    db.add(trip)
    return _respond(db, trip, await _md(grocy), ai)


@router.get("/trips/{trip_id}", response_model=TripOut)
async def get_trip(
    trip_id: int,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    return trip_out(db, _trip(db, trip_id), await _md(grocy), ai is not None)


@router.get("/trips/{trip_id}/revision", response_model=RevisionOut)
def trip_revision(trip_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Cheap staleness check for a device that has this trip open: it polls this
    (no Grocy round trip) and refetches the trip only when the number moved."""
    return RevisionOut(revision=_trip(db, trip_id).revision or 0)


@router.patch("/trips/{trip_id}", response_model=TripOut)
async def rename_trip(
    trip_id: int,
    body: TripPatch,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    trip = _trip(db, trip_id)
    trip.name = body.name.strip()
    return _respond(db, trip, await _md(grocy), ai)


@router.delete("/trips/{trip_id}", status_code=204)
def delete_trip(trip_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    """Deletes the trip record only; anything already booked into Grocy stays there."""
    trip = _trip(db, trip_id)
    filenames = [img.filename for r in trip.receipts for img in r.images]
    db.delete(trip)
    db.commit()
    for name in filenames:
        image_path(name).unlink(missing_ok=True)


# --- items ---------------------------------------------------------------------


@router.post("/trips/{trip_id}/scan", response_model=ScanOut)
async def scan(
    trip_id: int,
    body: ScanIn,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    http: httpx.AsyncClient = Depends(get_http),
):
    trip = _open_trip(db, trip_id)
    barcode = body.barcode.strip()
    md = await _md(grocy)

    variants = set(barcode_variants(barcode))
    for item in trip.items:
        if (
            item.barcode
            and item.status == "pending"
            and variants & set(barcode_variants(item.barcode))
        ):
            item.scan_count += 1
            db.commit()
            return ScanOut(item=item_out(item, trip, md), duplicate=True)

    item = TripItem(source="scan", barcode=barcode)
    if barcode.lower().startswith("grcy:p:"):
        # A Grocycode label printed by Grocy itself: grcy:p:<product id>[:<stock id>]
        try:
            product_id = int(barcode.split(":")[2])
        except (IndexError, ValueError):
            product_id = None
        if product_id in md.products:
            item.product_id, item.barcode = product_id, None
    else:
        row = md.find_barcode(barcode)
        if row is None and await grocy.find_barcode_live(barcode) is not None:
            # Someone just added it in Grocy. Refresh everything, since the product
            # it belongs to may be new as well.
            md = await grocy.master_data(force=True)
            row = md.find_barcode(barcode)
        if row is not None:
            item.product_id = int(row["product_id"])
        else:
            item.lookup = await lookup_barcode(http, barcode)
    trip.items.append(item)
    db.flush()
    matching.rematch(db, trip, md)
    db.commit()
    db.refresh(item)
    return ScanOut(item=item_out(item, trip, md), duplicate=False)


@router.post("/trips/{trip_id}/items", response_model=TripOut, status_code=201)
async def add_item(
    trip_id: int,
    body: ItemCreate,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    trip = _open_trip(db, trip_id)
    md = await _md(grocy)
    item = TripItem(source="manual", quantity=body.quantity)
    _set_product(item, body.product_id, md)
    trip.items.append(item)
    db.flush()
    matching.rematch(db, trip, md)
    return _respond(db, trip, md, ai)


@router.patch("/trips/{trip_id}/items/{item_id}", response_model=TripOut)
async def patch_item(
    trip_id: int,
    item_id: int,
    body: ItemPatch,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    trip = _open_trip(db, trip_id)
    item = _item(trip, item_id)
    _editable(item)
    md = await _md(grocy)
    sent = body.model_fields_set

    if "product_id" in sent:
        if body.product_id is None:
            item.product_id, item.link_barcode = None, False
        else:
            _set_product(item, body.product_id, md)
    if "new_product" in sent:
        if body.new_product is None:
            item.new_product = None
        else:
            item.new_product = _validate_draft(body.new_product, md)
            item.product_id, item.link_barcode = None, False
    for field in ("quantity", "line_total", "location_id", "shopping_location_id"):
        if field in sent:
            setattr(item, field, getattr(body, field))
    if "note" in sent:
        item.note = (body.note or "").strip()[:255] or None
    if "due_date" in sent:
        item.due_date = _validate_due(body.due_date) if body.due_date else None
    if "receipt_line_id" in sent:
        if body.receipt_line_id is None:
            item.receipt_line = None
            item.match_score = None
        else:
            line = db.get(ReceiptLine, body.receipt_line_id)
            if line is None or line.receipt.trip_id != trip.id:
                raise HTTPException(422, "That receipt line isn't part of this trip")
            for other in list(trip.items):
                if other.id != item.id and other.receipt_line_id == line.id:
                    if other.status == "committed":
                        raise HTTPException(409, "That line belongs to an item already in Grocy")
                    if other.source == "receipt":
                        trip.items.remove(other)
                    else:
                        other.receipt_line = None
                        other.match_score = other.match_method = None
            line.dismissed = False
            item.receipt_line = line
            item.match_score = 1.0
        # "manual" also pins a deliberate un-match so rematching leaves it alone.
        item.match_method = "manual"
    if body.skipped is not None:
        item.status = "skipped" if body.skipped else "pending"
        item.error = None

    db.flush()
    matching.rematch(db, trip, md)
    return _respond(db, trip, md, ai)


@router.delete("/trips/{trip_id}/items/{item_id}", response_model=TripOut)
async def delete_item(
    trip_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    trip = _open_trip(db, trip_id)
    item = _item(trip, item_id)
    _editable(item)
    if item.source == "receipt" and item.match_method == "learned" and item.receipt_line:
        # Otherwise the remembered mapping would recreate it on the next rematch.
        item.receipt_line.dismissed = True
    trip.items.remove(item)
    db.flush()
    md = await _md(grocy)
    matching.rematch(db, trip, md)
    return _respond(db, trip, md, ai)


# --- receipts ------------------------------------------------------------------


@router.post("/trips/{trip_id}/receipts", response_model=TripOut, status_code=201)
async def upload_receipt(
    trip_id: int,
    files: list[UploadFile] = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    http: httpx.AsyncClient = Depends(get_http),
    ai: AIProvider | None = Depends(get_ai),
):
    """One receipt per call. Several files = one long receipt photographed in
    sections, in top-to-bottom order."""
    trip = _open_trip(db, trip_id)
    limit = get_config().max_upload_mb * 1024 * 1024
    receipt = Receipt(status="processing")
    saved: list[str] = []
    try:
        for pos, upload in enumerate(files):
            data = await upload.read()
            if len(data) > limit:
                raise HTTPException(413, f"Photos must be under {get_config().max_upload_mb} MB")
            try:
                saved.append(save_upload(data))
            except ValueError as exc:
                raise HTTPException(415, str(exc)) from exc
            receipt.images.append(ReceiptImage(position=pos, filename=saved[-1]))
    except HTTPException:
        for name in saved:
            image_path(name).unlink(missing_ok=True)
        raise
    trip.receipts.append(receipt)
    db.commit()
    schedule_processing(http, receipt.id, user.id)
    return _respond(db, trip, await _md(grocy), ai)


@router.get("/receipts/{receipt_id}/images/{image_id}")
def receipt_image(
    receipt_id: int,
    image_id: int,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    image = db.get(ReceiptImage, image_id)
    if image is None or image.receipt_id != receipt_id or not image_path(image.filename).exists():
        raise HTTPException(404, "No such image")
    return FileResponse(
        image_path(image.filename),
        media_type=image.content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.patch("/receipts/{receipt_id}", response_model=TripOut)
async def patch_receipt(
    receipt_id: int,
    body: ReceiptPatch,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    receipt = _receipt(db, receipt_id)
    md = await _md(grocy)
    sent = body.model_fields_set
    if "store_name" in sent:
        receipt.store_name = (body.store_name or "").strip() or None
    if "purchased_on" in sent:
        receipt.purchased_on = _validate_due(body.purchased_on) if body.purchased_on else None
    if "shopping_location_id" in sent:
        store_id = body.shopping_location_id
        if store_id is not None and not any(int(s["id"]) == store_id for s in md.stores):
            raise HTTPException(422, "That store doesn't exist in Grocy")
        receipt.shopping_location_id = store_id
        if receipt.store_key and store_id is not None:
            # Remember the choice so the next receipt from this store needs no input.
            mapping = db.get(StoreMapping, receipt.store_key)
            if mapping is None:
                db.add(StoreMapping(store_key=receipt.store_key, shopping_location_id=store_id))
            else:
                mapping.shopping_location_id = store_id
    return _respond(db, receipt.trip, md, ai)


@router.delete("/receipts/{receipt_id}", response_model=TripOut)
async def delete_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    receipt = _receipt(db, receipt_id)
    trip = receipt.trip
    line_ids = {line.id for line in receipt.lines}
    if any(i.status == "committed" and i.receipt_line_id in line_ids for i in trip.items):
        raise HTTPException(409, "Items from this receipt are already in Grocy")
    for item in trip.items:
        if item.receipt_line_id in line_ids:
            item.receipt_line = None
            item.match_score = item.match_method = None
    filenames = [img.filename for img in receipt.images]
    trip.receipts.remove(receipt)
    db.flush()
    md = await _md(grocy)
    matching.rematch(db, trip, md)
    out = _respond(db, trip, md, ai)
    for name in filenames:
        image_path(name).unlink(missing_ok=True)
    return out


@router.post("/receipts/{receipt_id}/reprocess", response_model=TripOut)
async def reprocess_receipt(
    receipt_id: int,
    body: ReprocessIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    http: httpx.AsyncClient = Depends(get_http),
    ai: AIProvider | None = Depends(get_ai),
):
    receipt = _receipt(db, receipt_id)
    if receipt.status == "processing":
        raise HTTPException(409, "This receipt is still being read")
    if body.use_ai and ai is None:
        raise HTTPException(409, "No AI provider is configured")
    line_ids = {line.id for line in receipt.lines}
    if any(i.status == "committed" and i.receipt_line_id in line_ids for i in receipt.trip.items):
        raise HTTPException(409, "Items from this receipt are already in Grocy")
    receipt.status, receipt.error = "processing", None
    db.commit()
    schedule_processing(http, receipt.id, user.id, force_ai=body.use_ai)
    return _respond(db, receipt.trip, await _md(grocy), ai)


@router.patch("/receipt-lines/{line_id}", response_model=TripOut)
async def patch_line(
    line_id: int,
    body: LinePatch,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    line = _line(db, line_id)
    trip = line.receipt.trip
    if body.description is not None:
        line.description = body.description.strip()[:255]
    if body.quantity is not None:
        line.quantity = body.quantity
    if body.total_price is not None:
        line.total_price = body.total_price
    if body.dismissed is not None:
        line.dismissed = body.dismissed
        if body.dismissed:
            for item in list(trip.items):
                if item.receipt_line_id != line.id:
                    continue
                if item.status == "committed":
                    raise HTTPException(409, "This line's item is already in Grocy")
                if item.source == "receipt":
                    trip.items.remove(item)
                else:
                    item.receipt_line = None
                    item.match_score = item.match_method = None
    db.flush()
    md = await _md(grocy)
    matching.rematch(db, trip, md)
    return _respond(db, trip, md, ai)


@router.post("/receipt-lines/{line_id}/item", response_model=TripOut, status_code=201)
async def line_to_item(
    line_id: int,
    body: LineItemCreate,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    """For things with no barcode to scan: make the receipt line itself an item."""
    line = _line(db, line_id)
    trip = line.receipt.trip
    if any(i.receipt_line_id == line.id for i in trip.items):
        raise HTTPException(409, "That line is already matched to an item")
    md = await _md(grocy)
    item = TripItem(source="receipt", match_score=1.0, match_method="manual")
    if body.product_id is not None:
        _set_product(item, body.product_id, md)
    elif body.new_product is not None:
        item.new_product = _validate_draft(body.new_product, md)
    line.dismissed = False
    item.receipt_line = line
    trip.items.append(item)
    return _respond(db, trip, md, ai)


# --- matching & submit ---------------------------------------------------------


@router.post("/trips/{trip_id}/rematch", response_model=TripOut)
async def rematch_trip(
    trip_id: int,
    use_ai: bool = False,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    trip = _open_trip(db, trip_id)
    md = await grocy.master_data(force=True)
    matching.rematch(db, trip, md)
    if use_ai:
        if ai is None:
            raise HTTPException(409, "No AI provider is configured")
        await matching.ai_rematch(db, trip, md, ai)
    return _respond(db, trip, md, ai)


@router.post("/trips/{trip_id}/submit", response_model=SubmitResult)
async def submit(
    trip_id: int,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    """Books every ready item into Grocy under the signed-in user's API key.
    Safe to call again: items already booked are never added twice."""
    trip = _open_trip(db, trip_id)
    if any(r.status == "processing" for r in trip.receipts):
        raise HTTPException(409, "A receipt is still being read. Try again in a moment.")
    committed, failed, remaining = await submit_trip(db, grocy, trip)
    md = await grocy.master_data(force=True)
    return SubmitResult(
        committed=committed,
        failed=failed,
        remaining=remaining,
        trip=_respond(db, trip, md, ai),
    )


@router.post("/trips/{trip_id}/undo", response_model=TripOut)
async def undo(
    trip_id: int,
    db: Session = Depends(get_db),
    grocy: GrocyClient = Depends(get_grocy),
    ai: AIProvider | None = Depends(get_ai),
):
    """Reverses this trip's stock bookings in Grocy and reopens it for editing."""
    trip = _trip(db, trip_id)
    await undo_trip(db, grocy, trip)
    return _respond(db, trip, await grocy.master_data(force=True), ai)
