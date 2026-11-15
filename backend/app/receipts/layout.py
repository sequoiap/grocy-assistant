"""Rebuild printed receipt rows from scattered OCR boxes.

The OCR engine returns one box per text run, so a row like
``GV WHL MLK   007874235186 F   3.48 N`` often comes back as three boxes, the
price far to the right. Photos are rarely square to the paper and receipts curl,
so rows are grouped in a de-skewed frame and each box's own baseline angle is
used to follow mild curvature across the page.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .ocr import OcrBox


@dataclass
class Row:
    text: str
    score: float = 1.0  # mean OCR confidence of the row's boxes
    boxes: list[OcrBox] = field(default_factory=list)


def rows_from_text(text: str, score: float = 1.0) -> list[Row]:
    """Rows from plain text, one per line (for tests and re-parsing raw_text)."""
    return [Row(text=line.rstrip(), score=score) for line in text.splitlines() if line.strip()]


@dataclass
class _Placed:
    box: OcrBox
    x0: float
    x1: float
    cx: float
    cy: float
    h: float
    slope: float  # local baseline slope in the de-skewed frame


@dataclass
class _RowBuild:
    members: list[_Placed] = field(default_factory=list)

    def predict_y(self, item: _Placed) -> float:
        """Where this row's baseline sits at the item's x position."""
        nearest = min(self.members, key=lambda m: abs(m.cx - item.cx))
        wn, wi = nearest.x1 - nearest.x0, item.x1 - item.x0
        slope = (nearest.slope * wn + item.slope * wi) / max(1.0, wn + wi)
        return nearest.cy + slope * (item.cx - nearest.cx)

    def overlaps(self, item: _Placed) -> bool:
        for m in self.members:
            inter = min(m.x1, item.x1) - max(m.x0, item.x0)
            if inter > 0.5 * min(m.x1 - m.x0, item.x1 - item.x0):
                return True
        return False

    @property
    def height(self) -> float:
        return statistics.median(m.h for m in self.members)

    @property
    def cy(self) -> float:
        return statistics.fmean(m.cy for m in self.members)


def _skew(boxes: list[OcrBox]) -> float:
    """Dominant baseline angle, from boxes long enough to measure it well."""
    angles = [b.angle for b in boxes if b.width > 3 * b.height]
    if not angles:
        angles = [b.angle for b in boxes]
    return statistics.median(angles) if angles else 0.0


def build_rows(boxes: list[OcrBox]) -> list[Row]:
    if not boxes:
        return []
    skew = _skew(boxes)
    cos, sin = math.cos(-skew), math.sin(-skew)
    placed: list[_Placed] = []
    for b in boxes:
        xs = [x * cos - y * sin for x, y in b.points]
        cy = statistics.fmean(x * sin + y * cos for x, y in b.points)
        # Short boxes ("N", "3.48") have unreliable angles; trust only longer ones.
        local = b.angle - skew if b.width > 2.5 * b.height else 0.0
        local = max(-0.15, min(0.15, local))
        placed.append(_Placed(b, min(xs), max(xs), statistics.fmean(xs), cy, b.height, local))

    rows: list[_RowBuild] = []
    for item in sorted(placed, key=lambda p: p.cy):
        best, best_dist = None, None
        for row in rows[-12:]:  # only rows near the current height can match
            dist = abs(row.predict_y(item) - item.cy)
            limit = 0.55 * min(item.h, row.height)
            if dist <= limit and not row.overlaps(item) and (best_dist is None or dist < best_dist):
                best, best_dist = row, dist
        if best is None:
            rows.append(_RowBuild([item]))
        else:
            best.members.append(item)

    rows.sort(key=lambda r: r.cy)
    char_w = _char_width(placed)
    left = min(p.x0 for p in placed)
    return [_render(r, char_w, left) for r in rows]


def _char_width(placed: list[_Placed]) -> float:
    widths = [(p.x1 - p.x0) / len(p.box.text) for p in placed if len(p.box.text) >= 3]
    return statistics.median(widths) if widths else 10.0


def _render(row: _RowBuild, char_w: float, left: float) -> Row:
    """Lay boxes out on a character grid so columns stay visibly aligned."""
    members = sorted(row.members, key=lambda m: m.x0)
    text = ""
    for m in members:
        col = int(round((m.x0 - left) / char_w))
        if text:
            col = max(col, len(text) + 1)
        text = text.ljust(col) + m.box.text
    score = statistics.fmean(m.box.score for m in members)
    return Row(text=text.rstrip(), score=score, boxes=[m.box for m in members])
