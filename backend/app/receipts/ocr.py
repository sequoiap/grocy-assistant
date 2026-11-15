"""Thin wrapper around RapidOCR: one shared engine, results as plain boxes.

RapidOCR 3.x ships its default ONNX models (PP-OCRv6 det/rec "small" and the
v2.0 angle classifier) inside the wheel, under ``rapidocr/models``. Other model
choices would be downloaded from modelscope.cn on first use, so we stick to the
bundled defaults and the app works offline.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from rapidocr import RapidOCR

log = logging.getLogger(__name__)

# RapidOCR shrinks anything longer than 2000 px before detection, which makes the
# small print on a long receipt unreadable. Our preprocessing already sizes the
# image sensibly, so let it through.
_MAX_SIDE = 6000

_engine: RapidOCR | None = None
_engine_lock = threading.Lock()


@dataclass(frozen=True)
class OcrBox:
    """One recognized text fragment and its quadrilateral in image pixels."""

    text: str
    score: float
    # Four corners, clockwise from top-left.
    points: tuple[tuple[float, float], ...]

    @property
    def x0(self) -> float:
        return min(p[0] for p in self.points)

    @property
    def x1(self) -> float:
        return max(p[0] for p in self.points)

    @property
    def cx(self) -> float:
        return sum(p[0] for p in self.points) / len(self.points)

    @property
    def cy(self) -> float:
        return sum(p[1] for p in self.points) / len(self.points)

    @property
    def height(self) -> float:
        (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = self.points[:4]
        left = math.hypot(blx - tlx, bly - tly)
        right = math.hypot(brx - trx, bry - try_)
        return max(1.0, (left + right) / 2)

    @property
    def width(self) -> float:
        (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = self.points[:4]
        top = math.hypot(trx - tlx, try_ - tly)
        bottom = math.hypot(brx - blx, bry - bly)
        return max(1.0, (top + bottom) / 2)

    @property
    def angle(self) -> float:
        """Baseline angle in radians (positive = text slopes down to the right)."""
        (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = self.points[:4]
        top = math.atan2(try_ - tly, trx - tlx)
        bottom = math.atan2(bry - bly, brx - blx)
        return (top + bottom) / 2


def model_dir() -> Path:
    """Where RapidOCR keeps its model files (inside the installed package)."""
    import rapidocr

    return Path(rapidocr.__file__).resolve().parent / "models"


def get_engine() -> RapidOCR:
    """Create the engine once; concurrent receipt jobs share it."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rapidocr import RapidOCR

                _engine = RapidOCR(
                    params={
                        "Global.log_level": "warning",
                        "Global.max_side_len": _MAX_SIDE,
                        # Thermal print is thin; a lower box threshold keeps faint rows.
                        "Det.box_thresh": 0.4,
                    }
                )
    return _engine


# ONNX Runtime sessions are thread-safe, but RapidOCR mutates per-call settings on
# the engine object, so serialize calls rather than risk mixed-up parameters.
_run_lock = threading.Lock()


def run_ocr(image: np.ndarray) -> list[OcrBox]:
    """OCR a BGR or grayscale image and return its text boxes."""
    engine = get_engine()
    with _run_lock:
        result: Any = engine(image)
    if result is None or getattr(result, "boxes", None) is None or not result.txts:
        return []
    boxes: list[OcrBox] = []
    for quad, text, score in zip(result.boxes, result.txts, result.scores, strict=False):
        text = str(text).strip()
        if not text:
            continue
        points = tuple((float(x), float(y)) for x, y in np.asarray(quad).reshape(-1, 2)[:4])
        boxes.append(OcrBox(text=text, score=float(score), points=points))
    return boxes
