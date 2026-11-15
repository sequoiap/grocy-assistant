"""Costco receipts.

Typical body::

    E     1234567 KS ORG EGGS        7.99 N
          512515  KS WATER 40PK      4.99 A
          0000356151 / 512515        1.00-
                     SUBTOTAL       11.98
                          TAX        0.29
                   **** TOTAL       12.27
    TOTAL NUMBER OF ITEMS SOLD = 2
    INSTANT SAVINGS                 $1.00

The leading "E" marks food-stamp-eligible items. Instant savings print as their
own row referencing the item number after the slash, usually right below the
item but not always, so they're matched by number.
"""

from __future__ import annotations

import re

from ..layout import Row
from .base import apply_discount
from .common import Trailing, fix_digits
from .generic import GenericParser

_ITEM_NUMBER = re.compile(r"^(?:[A-Z]{1,2}\s+|E(?=[0-9]))?([0-9OQDILSBZ]{1,8})\s+(.*\S)$")
_COUPON_TOKEN = re.compile(r"^(?:[0-9OQDILSBZ]{2,12}|TPD|/|[A-Z])$")


class CostcoParser(GenericParser):
    store_key = "costco"

    def __init__(self, rows: list[Row], store_name: str | None = None) -> None:
        super().__init__(rows, store_name or "Costco")

    def extract_code(self, head: str) -> tuple[str | None, str]:
        m = _ITEM_NUMBER.match(head)
        if not m:
            return None, head
        code = fix_digits(m.group(1))
        if code is None or not code.isdigit():
            return None, head
        return code, m.group(2)

    def handle_adjustment(self, tail: Trailing, row: Row) -> bool:
        # The coupon shape alone is decisive; OCR often loses the thin trailing minus.
        ref = self._coupon_ref(tail.head)
        if ref is None:
            return super().handle_adjustment(tail, row)
        target = None
        for line in reversed(self.lines):
            if line.item_code and line.item_code.lstrip("0") == ref.lstrip("0"):
                if not line.discount:
                    target = line
                    break
                target = target or line
        if target is None:
            target = self.last_line()
            if target is None:
                return False
            self.out.warnings.append(
                f"A ${tail.amount:.2f} instant saving refers to item {ref}, which wasn't "
                f'found; applied it to "{target.description}"'
            )
            target.confidence = min(target.confidence, 0.6)
        apply_discount(target, tail.amount)
        target.raw_text = f"{target.raw_text}\n{row.text.strip()}".strip()
        return True

    @staticmethod
    def _coupon_ref(head: str) -> str | None:
        """'0000356151 / 512515' -> '512515' (the item the saving applies to)."""
        tokens = head.replace("/", " / ").split()
        if not tokens or not all(_COUPON_TOKEN.match(t) for t in tokens):
            return None
        numbers = [fix_digits(t) for t in tokens if any(c.isdigit() for c in t)]
        numbers = [n for n in numbers if n and n.isdigit()]
        if not numbers:
            return None
        return numbers[-1]
