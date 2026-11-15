"""The row loop every store parser shares.

A parser walks the reconstructed rows top to bottom. Summary rows (subtotal,
tax, total, item count) and obvious non-item rows (tenders, loyalty, survey
text) are handled here; each store subclass only decides what an item row,
a discount row, and a quantity/weight row look like for that store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..layout import Row
from ..types import ParsedLine
from .common import (
    QtyInfo,
    WeightInfo,
    clean,
    find_date,
    fix_word_zeros,
    has_amount,
    is_noise,
    summary,
    trailing_amount,
)

PRICE_TOLERANCE = 0.02


def close(a: float | None, b: float | None, tol: float = PRICE_TOLERANCE) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


@dataclass
class Outcome:
    """Everything a parser extracted, plus the evidence confidence is based on."""

    lines: list[ParsedLine] = field(default_factory=list)
    store_key: str | None = None
    store_name: str | None = None
    purchased_on: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    items_sold: float | None = None  # printed "# ITEMS SOLD"
    savings: float | None = None  # printed savings summary (e.g. Costco INSTANT SAVINGS)
    price_rows: int = 0  # rows in the item area that carry a price or item code
    understood_rows: int = 0  # ...of which the parser could make sense
    unparsed: list[str] = field(default_factory=list)
    row_scores: list[float] = field(default_factory=list)  # OCR confidence of item-area rows
    warnings: list[str] = field(default_factory=list)


def apply_discount(line: ParsedLine, amount: float) -> None:
    amount = round(abs(amount), 2)
    line.discount = round((line.discount or 0) + amount, 2)
    if line.total_price is not None:
        line.total_price = round(line.total_price - amount, 2)


def apply_qty(line: ParsedLine, qty: QtyInfo, raw: str) -> None:
    line.quantity = float(qty.quantity)
    line.unit_price = round(qty.unit_price, 2)
    expected = round(qty.quantity * qty.unit_price, 2)
    if qty.total is not None:
        line.total_price = qty.total
    elif line.total_price is None:
        line.total_price = expected
    if not close(line.total_price, expected, 0.02 + 0.01 * qty.quantity):
        line.confidence = min(line.confidence, 0.6)
    line.raw_text = f"{line.raw_text}\n{raw}".strip()


def apply_weight(line: ParsedLine, weight: WeightInfo, raw: str) -> None:
    line.weight = weight.weight
    line.weight_unit = weight.unit
    line.unit_price = round(weight.unit_price, 2)
    expected = round(weight.weight * weight.unit_price, 2)
    if weight.total is not None and (line.total_price is None or close(weight.total, expected)):
        line.total_price = weight.total
    elif line.total_price is None:
        line.total_price = expected
    if not close(line.total_price, expected, 0.03):
        line.confidence = min(line.confidence, 0.6)
    line.raw_text = f"{line.raw_text}\n{raw}".strip()


class BaseParser:
    store_key: str | None = None

    def __init__(self, rows: list[Row], store_name: str | None = None) -> None:
        self.rows = rows
        self.out = Outcome(store_key=self.store_key, store_name=store_name)
        self.in_footer = False
        self._tax_lines: list[float] = []
        self._total_tax: float | None = None

    # --- hooks -----------------------------------------------------------------------

    def parse_row(self, text: str, row: Row) -> bool:
        """Consume an item-area row; return True if it was understood."""
        raise NotImplementedError

    def is_price_row(self, text: str) -> bool:
        return has_amount(text)

    def finish(self) -> None:
        """Called after the last row."""

    # --- shared machinery --------------------------------------------------------------

    @property
    def lines(self) -> list[ParsedLine]:
        return self.out.lines

    def last_line(self) -> ParsedLine | None:
        return self.out.lines[-1] if self.out.lines else None

    def add_line(self, line: ParsedLine, row: Row) -> ParsedLine:
        line.confidence = round(min(line.confidence, max(0.0, row.score)), 3)
        self.out.lines.append(line)
        return line

    def parse(self) -> Outcome:
        for row in self.rows:
            text = clean(row.text)
            if not text:
                continue
            found = summary(text)
            if found is not None:
                self._take_summary(found.kind, found.value)
                continue
            if self._is_garbled_total(text):
                self._take_summary("total", self.out.total or 0.0)
                continue
            if self.in_footer or is_noise(text):
                continue
            price_row = self.is_price_row(text)
            understood = self.parse_row(text, row)
            if price_row:
                self.out.price_rows += 1
                self.out.row_scores.append(row.score)
                if understood:
                    self.out.understood_rows += 1
                else:
                    self.out.unparsed.append(row.text.strip())
        self.finish()
        self._finish_common()
        return self.out

    def _is_garbled_total(self, text: str) -> bool:
        """'T 39.05' right after subtotal and tax: the TOTAL label didn't survive OCR."""
        out = self.out
        if self.in_footer or out.subtotal is None or not self._tax_lines:
            return False
        tail = trailing_amount(text)
        expected = round(out.subtotal + sum(self._tax_lines), 2)
        if tail is None or abs(tail.amount - expected) > 0.005 or len(tail.head) > 12:
            return False
        out.total = tail.amount
        return True

    def _take_summary(self, kind: str, value: float) -> None:
        out = self.out
        if kind == "items_sold":
            out.items_sold = value
        elif kind == "savings":
            out.savings = out.savings if out.savings is not None else value
        elif self.in_footer:
            return  # tender sections and tax breakdowns repeat these figures
        elif kind == "subtotal":
            out.subtotal = value
        elif kind == "tax":
            # A tax breakdown can repeat the same figure; separate rates add up.
            if value not in self._tax_lines or value == 0:
                self._tax_lines.append(value)
        elif kind == "total_tax":
            self._total_tax = value
        elif kind == "total":
            out.total = value
            self.in_footer = True

    def _finish_common(self) -> None:
        out = self.out
        if self._total_tax is not None:
            out.tax = self._total_tax
        elif self._tax_lines:
            out.tax = round(sum(self._tax_lines), 2)
        out.purchased_on = find_date([clean(r.text) for r in self.rows])
        for line in out.lines:
            desc = fix_word_zeros(line.description).strip(" .:-*")
            line.description = desc or "(unreadable item)"
            if line.total_price is None:
                line.confidence = min(line.confidence, 0.3)
                out.warnings.append(f'Couldn\'t read a price for "{line.description}"')
