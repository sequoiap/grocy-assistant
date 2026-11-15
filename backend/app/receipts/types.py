"""Shared result types for receipt understanding.

Both the built-in OCR pipeline and the AI providers produce a ``ParsedReceipt``,
so everything downstream (matching, review, submit) is agnostic to how the
receipt was read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Canonical store keys with a dedicated parser. Anything else gets a slug of the
# detected store name (e.g. "trader-joes") or "unknown".
KNOWN_STORES = ("walmart", "costco", "kroger")


@dataclass
class ParsedLine:
    """One purchased item as printed on the receipt.

    ``total_price`` is what was actually paid for the line: quantity x unit price,
    minus any coupon/discount attributed to it, excluding sales tax.
    """

    description: str
    raw_text: str = ""
    # Store item identifier when printed: Walmart's 12-digit UPC-ish number,
    # Costco's item number, a Kroger UPC if present.
    item_code: str | None = None
    quantity: float = 1.0
    unit_price: float | None = None
    total_price: float | None = None
    discount: float | None = None  # positive number, already subtracted from total_price
    # Sold-by-weight items ("2.31 lb @ 1.99/lb"): quantity stays 1, weight is set.
    weight: float | None = None
    weight_unit: str | None = None  # lb | oz | kg | g
    confidence: float = 1.0  # 0..1, how sure the parser is about this line


@dataclass
class ParsedReceipt:
    lines: list[ParsedLine] = field(default_factory=list)
    store_key: str | None = None  # one of KNOWN_STORES, a slug, or None
    store_name: str | None = None  # human readable, e.g. "Smith's" for a Kroger banner
    purchased_on: str | None = None  # ISO date (YYYY-MM-DD)
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    raw_text: str = ""  # OCR text, one receipt row per line, for debugging and AI context
    method: str = "ocr"  # ocr | ai
    # 0..1 overall trust in this parse. The orchestrator consults the AI fallback
    # (when one is configured) below ``Config.ocr_confidence_threshold``.
    confidence: float = 0.0
    # Human-readable notes shown in the review screen, e.g.
    # "Item prices add up to $41.20 but the receipt subtotal is $43.19".
    warnings: list[str] = field(default_factory=list)
