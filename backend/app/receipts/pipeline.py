"""Receipt photo(s) -> ParsedReceipt using only local OCR and parsers."""

from __future__ import annotations

import logging
from pathlib import Path

from .confidence import score
from .layout import Row, build_rows, rows_from_text
from .ocr import run_ocr
from .parsers import parse_rows
from .preprocess import load_image, prepare
from .sections import merge_sections
from .types import ParsedReceipt

log = logging.getLogger(__name__)


def read_rows(image_path: Path) -> list[Row]:
    """OCR one photo and rebuild its printed rows."""
    image = prepare(load_image(image_path))
    return build_rows(run_ocr(image))


def parse_receipt_images(image_paths: list[Path]) -> ParsedReceipt:
    """Synchronous and CPU-bound; callers run it in a worker thread.

    Several paths are sections of one long receipt, top to bottom.
    """
    sections: list[list[Row]] = []
    problems: list[str] = []
    for n, path in enumerate(image_paths, start=1):
        try:
            sections.append(read_rows(path))
        except ValueError as exc:
            log.warning("skipping unreadable receipt image %s: %s", path, exc)
            problems.append(f"Photo {n} couldn't be read")
    receipt = parse_sections(sections)
    receipt.warnings = problems + receipt.warnings
    return receipt


def parse_sections(sections: list[list[Row]]) -> ParsedReceipt:
    """Merge overlapping photo sections, then parse.

    A single repeated row at a photo boundary is ambiguous: it is either overlap
    or the same item bought twice. Both readings are parsed and the one that
    reconciles better wins.
    """
    rows, overlaps = merge_sections(sections)
    receipt = parse_text_rows(rows)
    if 1 in overlaps:
        alt_rows, _ = merge_sections(sections, min_rows=2)
        alternative = parse_text_rows(alt_rows)
        if alternative.confidence > receipt.confidence:
            receipt = alternative
    return receipt


def parse_text_rows(rows: list[Row]) -> ParsedReceipt:
    raw_text = "\n".join(r.text for r in rows)
    if not rows:
        return ParsedReceipt(
            raw_text=raw_text,
            confidence=0.0,
            warnings=["No text was found in the photo; try a sharper, closer shot"],
        )
    outcome = parse_rows(rows)
    confidence, notes = score(outcome)
    return ParsedReceipt(
        lines=outcome.lines,
        store_key=outcome.store_key,
        store_name=outcome.store_name,
        purchased_on=outcome.purchased_on,
        subtotal=outcome.subtotal,
        tax=outcome.tax,
        total=outcome.total,
        raw_text=raw_text,
        method="ocr",
        confidence=confidence,
        warnings=outcome.warnings + notes,
    )


def parse_text(text: str) -> ParsedReceipt:
    """Parse already-reconstructed receipt text (one printed row per line)."""
    return parse_text_rows(rows_from_text(text))
