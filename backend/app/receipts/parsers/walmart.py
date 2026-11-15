"""Walmart receipts.

Typical body::

    GV WHL MLK     007874235186 F    3.48 N
    GV SPRING WTR  007874202906 F
       2 AT 1 FOR 0.98               1.96 N
    BANANAS        000000004011 KF
       1.23 lb @ 1 lb /0.58          0.71 N
                       SUBTOTAL     6.15
              TAX 1  6.850 %         0.00
                          TOTAL     6.15
    # ITEMS SOLD 4

The 12-digit number is the UPC zero-padded and without its check digit. Letters
after it are department flags; the letter after the price is the tax code. A
voided entry is printed again with a negative price (sometimes after a
"VOIDED ENTRY" marker row).
"""

from __future__ import annotations

import re

from ..layout import Row
from ..types import ParsedLine
from .base import apply_discount
from .common import Trailing, fix_digits, has_amount, trailing_amount
from .generic import DISCOUNT_RE, GenericParser, letter_count

_VOID_RE = re.compile(r"\bVOID(?:ED)?\b|\bERROR CORRECT|\bCANCEL")
_GLUED_FLAG = re.compile(r"(?<=[0-9OQDILSBZ])[ACEFGHKMNPRTUVWXY]{1,2}$")
_NO_DOT_PRICE = re.compile(r"(?<![\d.,])(\d{3,5})\s*(-)?\s*([A-Z])?$")


def find_code(text: str) -> tuple[str, int, int] | None:
    """Locate the item number as (digits, start, end).

    Tolerates OCR digit confusion, a department flag glued to the end
    ("007874235186F") and the number being split in two by a stray space.
    """
    tokens = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    candidates = list(tokens)
    candidates += [(a[0] + b[0], a[1], b[2]) for a, b in zip(tokens, tokens[1:], strict=False)]
    best: tuple[str, int, int] | None = None
    for raw, start, end in candidates:
        core = _GLUED_FLAG.sub("", raw)
        fixed = fix_digits(core) if len(core) >= 11 else None
        if fixed is None or not fixed.isdigit() or not 11 <= len(fixed) <= 13:
            continue
        if sum(c.isdigit() for c in core) < 9:
            continue
        if best is None or abs(len(fixed) - 12) < abs(len(best[0]) - 12):
            best = (fixed, start, end - (len(raw) - len(core)))
    return best


class WalmartParser(GenericParser):
    store_key = "walmart"

    def __init__(self, rows: list[Row], store_name: str | None = None) -> None:
        super().__init__(rows, store_name or "Walmart")
        self.void_next = False

    def is_price_row(self, text: str) -> bool:
        # A long digit run is an item code even when OCR mangled it beyond use.
        return has_amount(text) or re.search(r"\d{6,}", text) is not None

    def extract_code(self, head: str) -> tuple[str | None, str]:
        found = find_code(head)
        if found is None:
            return None, head
        code, start, end = found
        return code, head[:start].strip()

    def parse_row(self, text: str, row: Row) -> bool:
        if _VOID_RE.search(text) and not has_amount(text):
            self.void_next = True
            return True
        found = find_code(text)
        if found is None:
            return super().parse_row(text, row)
        code, start, end = found
        desc = text[:start].strip()
        rest = text[end:].strip()
        confidence = 1.0 if len(code) == 12 else 0.6
        tail = trailing_amount(rest)
        if tail is None:
            tail = self._undotted_price(rest)
            if tail is not None:
                confidence = min(confidence, 0.5)
        if tail is not None and (tail.negative or self.void_next):
            self.void_next = False
            if self._void(code, tail.amount):
                return True
            last = self.last_line()
            if last is not None and (tail.negative or DISCOUNT_RE.search(desc)):
                apply_discount(last, tail.amount)
                last.raw_text = f"{last.raw_text}\n{row.text.strip()}".strip()
                return True
        amount = tail.amount if tail is not None else None
        if letter_count(desc) < 2:
            confidence = min(confidence, 0.6)
        line = ParsedLine(
            description=desc,
            raw_text=row.text.strip(),
            item_code=code,
            unit_price=amount,
            total_price=amount,
            confidence=confidence,
        )
        self.add_item(line, row)
        return True

    @staticmethod
    def _undotted_price(rest: str) -> Trailing | None:
        # "F 348 N": the decimal point faded or was dropped by OCR.
        m = _NO_DOT_PRICE.search(rest)
        if not m:
            return None
        return Trailing("", int(m.group(1)) / 100, bool(m.group(2)), m.group(3))

    def _void(self, code: str, amount: float) -> bool:
        for idx in range(len(self.lines) - 1, -1, -1):
            line = self.lines[idx]
            if line.item_code != code:
                continue
            each = line.unit_price if line.unit_price is not None else line.total_price
            if line.quantity > 1 and each is not None and abs(each - amount) <= 0.02:
                line.quantity -= 1
                line.total_price = round((line.total_price or 0) - amount, 2)
            else:
                del self.lines[idx]
            return True
        return False
