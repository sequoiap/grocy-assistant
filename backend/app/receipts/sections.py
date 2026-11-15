"""Stitch a long receipt photographed in several overlapping sections."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from .layout import Row

_MAX_OVERLAP = 25
# Rows cut in half by a photo edge come back as junk; allow that many on each side.
_EDGE_SLACK = 2


def _key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def find_overlap(top: list[Row], bottom: list[Row], min_rows: int = 1) -> tuple[int, int, int]:
    """Find rows printed at the end of ``top`` and again at the start of ``bottom``.

    Returns ``(i, j, k)`` where ``top[i:i+k]`` matches ``bottom[j:j+k]``; ``k == 0``
    means no overlap. The match must end within a couple of rows of the bottom of
    ``top`` and start within a couple of rows of the top of ``bottom``.
    """
    a = [_key(r.text) for r in top]
    b = [_key(r.text) for r in bottom]
    best, best_score = (0, 0, 0), 0.0
    for j in range(min(_EDGE_SLACK + 1, len(b))):
        for end in range(len(a), max(len(a) - _EDGE_SLACK - 1, 0), -1):
            for size in range(min(end, len(b) - j, _MAX_OVERLAP), min_rows - 1, -1):
                if size <= 0:
                    break
                block_a, block_b = a[end - size : end], b[j : j + size]
                if max(len(x) for x in block_a) < 6:
                    continue
                pairs = zip(block_a, block_b, strict=True)
                sims = [fuzz.ratio(x, y) if x and y else 0.0 for x, y in pairs]
                if min(sims) < 75 or sum(sims) / size < 86:
                    continue
                # Prefer long overlaps that sit right at the photo edges.
                score = size + sum(sims) / (100 * size) - 0.3 * (len(a) - end + j)
                if score > best_score:
                    best, best_score = (end - size, j, size), score
                break
    return best


def merge_sections(sections: list[list[Row]], min_rows: int = 1) -> tuple[list[Row], list[int]]:
    """Concatenate sections top to bottom, keeping one copy of overlapping rows.

    Returns the merged rows and, per photo boundary, how many rows overlapped.
    Rows outside the matched block at the very edges (half-cut fragments) are
    dropped from the photo that shows them cut.
    """
    merged: list[Row] = list(sections[0]) if sections else []
    overlaps: list[int] = []
    for section in sections[1:]:
        i, j, k = find_overlap(merged, section, min_rows)
        merged = merged[: i + k] + section[j + k :] if k else merged + section
        overlaps.append(k)
    return merged, overlaps
