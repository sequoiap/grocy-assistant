"""Kroger family receipts (Kroger, Smith's, Fred Meyer, Ralphs, King Soopers, ...).

Typical body::

    KRO 2% MILK GAL          3.29 B
       SC KROGER SAVINGS     0.50-
    2 @ 2/5.00
    PRIVATE SEL CHIPS        5.00 B
    2.31 lb @ 1.99 /lb
    WT      BANANAS          4.60 B
                  TAX        0.31
         **** BALANCE       12.40

Quantity and weight rows sit *above* their item; savings and coupon rows sit
below it and are printed with or without a trailing minus.
"""

from __future__ import annotations

import re

from ..layout import Row
from ..types import ParsedLine
from .common import Trailing
from .generic import GenericParser

_WT_PREFIX = re.compile(r"^(?:WT|W7|VT)\s+")
_KROGER_SAVINGS = re.compile(
    r"^(?:SC|MC|CPN)\b|KROGER|PLUS CARD|CARD SAVINGS|DIGITAL|MFR|E-?COUPON|BONUS|"
    r"FREE ITEM|BUY \d+ GET"
)


class KrogerParser(GenericParser):
    store_key = "kroger"
    qty_before_item = True

    def handle_adjustment(self, tail: Trailing, row: Row) -> bool:
        if _KROGER_SAVINGS.search(tail.head) and not self._looks_like_product(tail.head):
            # Savings rows often lack the minus; mark them so the generic path discounts.
            tail = Trailing("SAVINGS " + tail.head, tail.amount, True, tail.flag)
        return super().handle_adjustment(tail, row)

    @staticmethod
    def _looks_like_product(head: str) -> bool:
        # "KROGER 2% MILK" is a product; "SC KROGER SAVINGS" is not.
        return head.startswith("KRO") and not re.search(r"SAVING|COUPON|CPN|DISC", head)

    def make_item(self, tail: Trailing, row: Row) -> ParsedLine | None:
        line = super().make_item(tail, row)
        if line is not None:
            line.description = _WT_PREFIX.sub("", line.description)
        return line
