"""Make phone photos of thermal receipts easier to OCR.

Steps, each optional so their effect can be measured:
1. crop to the receipt paper (and straighten it when it is visibly rotated),
2. flatten uneven lighting (shadows, phone vignetting, faded thermal print),
3. rescale so the paper is about ``TARGET_WIDTH`` pixels wide. Receipts are
   ~40-48 monospace characters across, so this puts characters at a size the
   recognizer reads well no matter how far away the photo was taken.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

TARGET_WIDTH = 1300
# Keep very long receipt sections from turning into huge detection inputs.
MAX_HEIGHT = 5200


@dataclass(frozen=True)
class PrepOptions:
    crop: bool = True
    flatten: bool = True
    rescale: bool = True


def load_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Can't read image {path}")
    return image


def prepare(image: np.ndarray, options: PrepOptions = PrepOptions()) -> np.ndarray:
    """BGR photo in, cleaned-up BGR image out."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if options.crop:
        gray = crop_to_receipt(gray)
    if options.rescale:
        gray = rescale(gray)
    if options.flatten:
        gray = flatten_lighting(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def crop_to_receipt(gray: np.ndarray) -> np.ndarray:
    """Cut away the table/hand around the paper; rotate it upright if tilted."""
    h, w = gray.shape
    scale = 800 / max(h, w)
    small = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))))
    small = cv2.GaussianBlur(small, (5, 5), 0)
    # Edges rather than a brightness threshold: a shadow across the paper fools a
    # global threshold, but the paper/table boundary stays sharp.
    edges = cv2.Canny(small, 30, 90)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray
    paper = cv2.convexHull(max(contours, key=lambda c: cv2.contourArea(cv2.convexHull(c))))
    area = cv2.contourArea(paper) / (small.shape[0] * small.shape[1])
    # Too small: probably glare, not the receipt. Nearly everything: already cropped.
    if area < 0.12 or area > 0.92:
        return gray
    # Straighten by the paper edge's tilt, reduced to +-45 degrees so a short, wide
    # receipt is never turned on its side (the photo is already upright via EXIF).
    corners = cv2.boxPoints(cv2.minAreaRect(paper))
    dx, dy = corners[1] - corners[0]
    tilt = (np.degrees(np.arctan2(dy, dx)) + 45) % 90 - 45
    outline = paper.reshape(-1, 2).astype(np.float32) / scale
    if abs(tilt) > 1.0:
        rot = cv2.getRotationMatrix2D((w / 2, h / 2), float(tilt), 1.0)
        gray = cv2.warpAffine(
            gray, rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        outline = cv2.transform(outline.reshape(-1, 1, 2), rot).reshape(-1, 2)
    x, y, bw, bh = cv2.boundingRect(outline.astype(np.int32))
    margin = int(0.015 * max(bw, bh))
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(w, x + bw + margin), min(h, y + bh + margin)
    if x1 - x0 < 50 or y1 - y0 < 50:
        return gray
    return gray[y0:y1, x0:x1]


def flatten_lighting(gray: np.ndarray) -> np.ndarray:
    """Divide out the paper's brightness so shadows and fading even out."""
    h, w = gray.shape
    # The background estimate must be blind to text strokes: a closing wider than
    # a character removes the dark print and leaves only the paper shading.
    k = max(15, int(min(h, w) / 40) | 1)
    background = cv2.morphologyEx(
        gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    )
    background = cv2.GaussianBlur(background, (0, 0), k / 2)
    flat = cv2.divide(gray, background, scale=255)
    # Stretch so the faintest print still reaches near-black.
    lo, hi = np.percentile(flat, (1, 99.5))
    if hi - lo < 10:
        return flat
    stretched = np.clip((flat.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255)
    return stretched.astype(np.uint8)


def rescale(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape
    factor = TARGET_WIDTH / w
    factor = min(factor, MAX_HEIGHT / h)
    factor = max(0.4, min(factor, 3.0))
    if abs(factor - 1) < 0.08:
        return gray
    interp = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    return cv2.resize(gray, (int(w * factor), int(h * factor)), interpolation=interp)
