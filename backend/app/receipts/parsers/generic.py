"""Fallback parser for stores without a dedicated one: description + trailing price.

Also the base for the Kroger family, whose layout is the same apart from where
quantity/weight rows go and how savings rows are worded.
"""

from __future__ import annotations

import re

from ..layout import Row
from ..types import ParsedLine
from .base import BaseParser, apply_discount, apply_qty, apply_weight, close
from .common import (
    QtyInfo,
    Trailing,
    WeightInfo,
    fix_digits,
    parse_qty,
    parse_weight,
    trailing_amount,
)

DISCOUNT_RE = re.compile(
    r"\b(?:SAVINGS?|SAVED|COUPONS?|CPN|DISCOUNT|DISC|PROMO|ROLLBACK|MARKDOWN|REBATE|BOGO|"
    r"PRICE ?CUT|\d+% OFF)\b|^(?:SC|MC)\b"
)
_CODE_TOKEN = re.compile(r"^[0-9OQDILSBZ]{6,14}$")


def split_code(head: str) -> tuple[str | None, str]:
    """Pull a leading or trailing item number (6+ digits) off a description."""
    tokens = head.split()
    for idx in (0, len(tokens) - 1):
        if len(tokens) < 2 or not _CODE_TOKEN.match(tokens[idx]):
            continue
        fixed = fix_digits(tokens[idx])
        if fixed and fixed.isdigit() and sum(c.isdigit() for c in tokens[idx]) >= 5:
            rest = tokens[1:] if idx == 0 else tokens[:-1]
            return fixed, " ".join(rest)
    return None, head


def letter_count(text: str) -> int:
    return sum(c.isalpha() for c in text)


class GenericParser(BaseParser):
    store_key = None
    # Kroger prints "2 @ 2/5.00" and weight rows *above* the item they belong to.
    qty_before_item = False

    def __init__(self, rows: list[Row], store_name: str | None = None) -> None:
        super().__init__(rows, store_name)
        self.pending_qty: tuple[QtyInfo, str] | None = None
        self.pending_weight: tuple[WeightInfo, str] | None = None
        self.last_was_item = False

    def parse_row(self, text: str, row: Row) -> bool:
        weight = parse_weight(text)
        if weight is not None:
            self.handle_weight(weight, row.text.strip())
            self.last_was_item = False
            return True
        qty = parse_qty(text)
        if qty is not None:
            self.handle_qty(qty, row.text.strip())
            self.last_was_item = False
            return True
        tail = trailing_amount(text)
        if tail is None:
            self.last_was_item = False
            return False
        if self.handle_adjustment(tail, row):
            self.last_was_item = False
            return True
        line = self.make_item(tail, row)
        if line is None:
            self.last_was_item = False
            return self.attach_orphan_price(tail)
        self.add_item(line, row)
        return True

    # --- items ---------------------------------------------------------------------

    def extract_code(self, head: str) -> tuple[str | None, str]:
        return split_code(head)

    def make_item(self, tail: Trailing, row: Row) -> ParsedLine | None:
        code, desc = self.extract_code(tail.head)
        if letter_count(desc) < 2:
            return None
        return ParsedLine(
            description=desc,
            raw_text=row.text.strip(),
            item_code=code,
            unit_price=tail.amount,
            total_price=tail.amount,
        )

    def add_item(self, line: ParsedLine, row: Row) -> None:
        self.add_line(line, row)
        if self.pending_weight is not None:
            apply_weight(line, *self.pending_weight)
            self.pending_weight = None
        if self.pending_qty is not None:
            apply_qty(line, *self.pending_qty)
            self.pending_qty = None
        self.last_was_item = True

    def attach_orphan_price(self, tail: Trailing) -> bool:
        """A price that lost its description to a layout split belongs to the item above."""
        last = self.last_line()
        if tail.head or last is None or last.total_price is not None or tail.negative:
            return False
        last.total_price = tail.amount
        last.unit_price = last.unit_price or tail.amount
        last.confidence = min(last.confidence, 0.7)
        return True

    # --- discounts, voids ------------------------------------------------------------

    def handle_adjustment(self, tail: Trailing, row: Row) -> bool:
        is_discount = bool(DISCOUNT_RE.search(tail.head))
        if not is_discount and not tail.negative:
            return False
        last = self.last_line()
        if last is None:
            return False
        if not is_discount and self.void_matching(tail):
            return True
        apply_discount(last, tail.amount)
        last.raw_text = f"{last.raw_text}\n{row.text.strip()}".strip()
        return True

    def void_matching(self, tail: Trailing) -> bool:
        """A negative item row cancels an earlier identical one."""
        code, desc = self.extract_code(tail.head)
        key = re.sub(r"[^A-Z0-9]", "", desc)
        if letter_count(desc) < 2:
            return False
        for idx in range(len(self.lines) - 1, -1, -1):
            line = self.lines[idx]
            same = (code and line.item_code == code) or (
                re.sub(r"[^A-Z0-9]", "", line.description.upper()) == key
            )
            if same and close(line.unit_price, tail.amount):
                if line.quantity > 1:
                    line.quantity -= 1
                    line.total_price = round((line.total_price or 0) - tail.amount, 2)
                else:
                    del self.lines[idx]
                return True
        return False

    # --- quantity and weight rows ----------------------------------------------------

    def _previous_item_fits(self, expected: float | None, explicit_total: float | None) -> bool:
        last = self.last_line()
        if last is None or not self.last_was_item or last.weight is not None:
            return False
        if last.quantity != 1:
            return False
        if explicit_total is not None or last.total_price is None:
            return True
        return close(last.total_price, expected, 0.05)

    def handle_qty(self, qty: QtyInfo, raw: str) -> None:
        expected = round(qty.quantity * qty.unit_price, 2)
        attach = (not self.qty_before_item or qty.total is not None) and self._previous_item_fits(
            expected, qty.total
        )
        last = self.last_line()
        if attach and last is not None:
            apply_qty(last, qty, raw)
        else:
            self.pending_qty = (qty, raw)

    def handle_weight(self, weight: WeightInfo, raw: str) -> None:
        expected = round(weight.weight * weight.unit_price, 2)
        attach = (
            not self.qty_before_item or weight.total is not None
        ) and self._previous_item_fits(expected, weight.total)
        last = self.last_line()
        if attach and last is not None:
            apply_weight(last, weight, raw)
        else:
            self.pending_weight = (weight, raw)

    def finish(self) -> None:
        # A trailing qty/weight row with no item after it most likely belonged above.
        last = self.last_line()
        if last is None:
            return
        if self.pending_weight is not None and last.weight is None:
            apply_weight(last, *self.pending_weight)
        if self.pending_qty is not None and last.quantity == 1:
            apply_qty(last, *self.pending_qty)
