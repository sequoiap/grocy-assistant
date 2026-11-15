"""Receipt processing: local OCR first, AI only as a configured fallback."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from rapidfuzz import fuzz, process, utils
from sqlalchemy.orm import Session

from ..ai import build_provider
from ..ai.base import AIError, AIProvider, ImageInput
from ..config import get_config
from ..db import session_scope
from ..grocy.client import GrocyError, MasterData
from ..models import Receipt, ReceiptLine, StoreMapping, User
from ..receipts.pipeline import parse_receipt_images
from ..receipts.types import ParsedLine, ParsedReceipt
from . import matching
from .accounts import grocy_for
from .settings import resolve_ai
from .textmatch import normalize_key

log = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 3000
# Keep references so in-flight tasks aren't garbage collected mid-run.
_tasks: set[asyncio.Task] = set()


def save_upload(data: bytes) -> str:
    """Normalize an uploaded photo (EXIF rotation, sane size, JPEG) and store it.
    Returns the stored filename. Raises ValueError if it isn't a readable image."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as exc:
        raise ValueError("That file isn't an image this server can read") from exc
    if max(img.size) > MAX_IMAGE_SIDE:
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(get_config().upload_dir / name, "JPEG", quality=90)
    return name


def image_path(filename: str) -> Path:
    return get_config().upload_dir / Path(filename).name


def consolidate(lines: list[ParsedLine]) -> list[ParsedLine]:
    """Merge repeats of the same item (stores often print one line per unit)."""
    out: list[ParsedLine] = []
    index: dict[tuple, ParsedLine] = {}
    for line in lines:
        each = line.unit_price
        if each is None and line.total_price is not None and line.quantity:
            each = line.total_price / line.quantity
        key = (
            line.item_code or normalize_key(line.description),
            round(each, 2) if each is not None else None,
        )
        existing = index.get(key)
        if existing is None or line.weight is not None or not key[0]:
            out.append(line)
            if line.weight is None and key[0]:
                index[key] = line
            continue
        existing.quantity += line.quantity
        if line.total_price is not None:
            existing.total_price = round((existing.total_price or 0) + line.total_price, 2)
        if line.discount is not None:
            existing.discount = round((existing.discount or 0) + line.discount, 2)
        if line.raw_text:
            existing.raw_text = f"{existing.raw_text}\n{line.raw_text}".strip()
        existing.confidence = min(existing.confidence, line.confidence)
    return out


def guess_store(db: Session, parsed_key: str | None, name: str | None, md: MasterData):
    """Which Grocy store is this receipt from? Remembered choice first, then name."""
    if parsed_key:
        mapping = db.get(StoreMapping, parsed_key)
        if mapping and any(int(s["id"]) == mapping.shopping_location_id for s in md.stores):
            return mapping.shopping_location_id
    if name and md.stores:
        hit = process.extractOne(
            name,
            {int(s["id"]): s["name"] for s in md.stores},
            scorer=fuzz.WRatio,
            processor=utils.default_process,
            score_cutoff=85,
        )
        if hit:
            return hit[2]
    return None


def apply_parsed(db: Session, receipt: Receipt, parsed: ParsedReceipt, md: MasterData) -> None:
    # Matches pointing at the lines being replaced can't survive a re-read.
    old_ids = {line.id for line in receipt.lines}
    for item in receipt.trip.items:
        if item.receipt_line_id in old_ids:
            item.receipt_line = None
            item.match_score = None
            item.match_method = None
    db.flush()
    receipt.lines.clear()
    db.flush()
    receipt.store_key = parsed.store_key or (
        normalize_key(parsed.store_name).lower().replace(" ", "-") if parsed.store_name else None
    )
    receipt.store_name = parsed.store_name
    receipt.purchased_on = parsed.purchased_on
    receipt.subtotal = parsed.subtotal
    receipt.tax = parsed.tax
    receipt.total = parsed.total
    receipt.method = parsed.method
    receipt.confidence = parsed.confidence
    receipt.warnings = list(parsed.warnings)
    receipt.raw_text = parsed.raw_text
    receipt.shopping_location_id = guess_store(db, receipt.store_key, receipt.store_name, md)
    for pos, line in enumerate(consolidate(parsed.lines)):
        receipt.lines.append(
            ReceiptLine(
                position=pos,
                raw_text=line.raw_text,
                description=line.description[:255],
                item_code=line.item_code,
                quantity=line.quantity or 1,
                unit_price=line.unit_price,
                total_price=line.total_price,
                discount=line.discount,
                weight=line.weight,
                weight_unit=line.weight_unit,
            )
        )
    if receipt.lines:
        receipt.status, receipt.error = "ready", None
    else:
        receipt.status = "failed"
        receipt.error = "Couldn't find any items on this receipt. Try a sharper, flatter photo."
    db.flush()


async def read_receipt(
    paths: list[Path], provider: AIProvider | None, mode: str, force_ai: bool
) -> ParsedReceipt:
    """OCR + parse locally; consult the AI provider only if configured and needed."""
    parsed: ParsedReceipt | None = None
    try:
        parsed = await asyncio.to_thread(parse_receipt_images, paths)
    except Exception:
        log.exception("local receipt parsing crashed")
    threshold = get_config().ocr_confidence_threshold
    unsure = parsed is None or not parsed.lines or parsed.confidence < threshold
    if provider is not None and (force_ai or mode == "always" or unsure):
        try:
            images = [ImageInput(p.read_bytes(), "image/jpeg") for p in paths]
            ai_parsed = await provider.extract_receipt(images, parsed.raw_text if parsed else None)
            ai_parsed.method = "ai"
            if parsed and not ai_parsed.raw_text:
                ai_parsed.raw_text = parsed.raw_text
            if ai_parsed.lines:
                return ai_parsed
            note = "AI read found no items; showing the built-in OCR result"
        except AIError as exc:
            log.warning("AI receipt read failed: %s", exc)
            note = f"AI fallback failed ({exc}); showing the built-in OCR result"
        if parsed is not None:
            parsed.warnings.append(note)
    if parsed is None:
        return ParsedReceipt(warnings=["The built-in receipt reader failed on this photo"])
    if unsure and provider is None and parsed.lines:
        parsed.warnings.append("Low confidence read; double-check items and prices")
    return parsed


async def process_receipt(
    http: httpx.AsyncClient, receipt_id: int, user_id: int, force_ai: bool = False
) -> None:
    """Background job: read the receipt, store its lines, re-run matching.

    `user_id` is whoever uploaded (or re-read) the receipt: their AI provider
    reads it and their Grocy key fetches the products to match against."""
    try:
        with session_scope() as db:
            receipt = db.get(Receipt, receipt_id)
            user = db.get(User, user_id)
            if receipt is None or user is None:
                return
            paths = [image_path(img.filename) for img in receipt.images]
            ai = resolve_ai(db, user)

        provider: AIProvider | None = None
        if ai.config is not None:
            try:
                provider = build_provider(ai.config)
            except AIError as exc:
                log.warning("AI provider unavailable: %s", exc)

        parsed = await read_receipt(paths, provider, ai.mode, force_ai)

        # Nobody is waiting on this request, so any Grocy failure (including a key
        # Grocy no longer accepts) just means the receipt is stored without matches.
        md = MasterData()
        try:
            md = await grocy_for(user, http).master_data()
        except GrocyError as exc:
            log.warning("Grocy unavailable while processing receipt: %s", exc)

        with session_scope() as db:
            receipt = db.get(Receipt, receipt_id)
            if receipt is None:  # deleted while we were reading it
                return
            apply_parsed(db, receipt, parsed, md)
            matching.rematch(db, receipt.trip, md)
            if provider is not None and receipt.status == "ready":
                await matching.ai_rematch(db, receipt.trip, md, provider)
    except Exception as exc:
        log.exception("receipt %s processing failed", receipt_id)
        with session_scope() as db:
            receipt = db.get(Receipt, receipt_id)
            if receipt is not None:
                receipt.status = "failed"
                receipt.error = f"Processing failed: {exc}"


def schedule_processing(
    http: httpx.AsyncClient, receipt_id: int, user_id: int, force_ai: bool = False
) -> None:
    task = asyncio.create_task(process_receipt(http, receipt_id, user_id, force_ai))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def fail_interrupted() -> None:
    """Receipts left mid-read by a restart can't finish; let the user retry them."""
    with session_scope() as db:
        for receipt in db.query(Receipt).filter(Receipt.status == "processing"):
            receipt.status = "failed"
            receipt.error = "The server restarted while reading this receipt. Tap retry."
