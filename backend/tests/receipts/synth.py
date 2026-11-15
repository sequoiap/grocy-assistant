"""Render receipt text into images that look like phone photos of thermal paper."""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/Library/Fonts/Courier New.ttf",
]


def find_font() -> str | None:
    return next((f for f in FONT_CANDIDATES if Path(f).exists()), None)


def render_paper(text: str, font_size: int = 26, ink: int = 40) -> Image.Image:
    """Clean receipt paper with the text printed in a monospace font."""
    font_path = find_font()
    if font_path is None:
        raise RuntimeError("no monospace TrueType font available")
    font = ImageFont.truetype(font_path, font_size)
    lines = text.splitlines()
    char_w = int(round(font.getlength("M")))
    line_h = int(font_size * 1.45)
    width = char_w * (max(len(line) for line in lines) + 4)
    height = line_h * len(lines) + 4 * line_h
    paper = Image.new("L", (width, height), 246)
    draw = ImageDraw.Draw(paper)
    for i, line in enumerate(lines):
        draw.text((char_w, 2 * line_h + i * line_h), line, font=font, fill=ink)
    return paper


def simple_scan(text: str, path: Path, angle: float = 1.5, seed: int = 0) -> Path:
    """Paper with slight rotation and sensor noise, filling the frame."""
    rng = np.random.default_rng(seed)
    paper = render_paper(text).rotate(angle, expand=True, fillcolor=246, resample=Image.BICUBIC)
    arr = np.asarray(paper, dtype=np.float32)
    arr += rng.normal(0, 8, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGB")
    img.save(path, "JPEG", quality=88)
    return path


def phone_photo(
    text: str,
    path: Path,
    seed: int = 0,
    angle: float = 3.0,
    blur: float = 0.8,
    shadow: float = 0.45,
    fade: int = 85,
    canvas: tuple[int, int] = (1800, 3000),
    curl: float = 6.0,
    paper_frac: float = 0.55,
) -> Path:
    """Faded thermal print on a dark table, rotated, curled, shadowed and blurred."""
    rng = random.Random(seed)
    paper = render_paper(text, font_size=24, ink=fade)
    pw, ph = paper.size
    arr = np.asarray(paper, dtype=np.float32)

    # Paper curl: rows bow up/down across the width.
    if curl:
        xs = np.arange(pw, dtype=np.float32)
        offset = curl * np.sin(np.pi * xs / pw)
        map_x = np.tile(xs, (ph, 1))
        map_y = np.arange(ph, dtype=np.float32)[:, None] + offset[None, :]
        arr = cv2.remap(
            arr, map_x, map_y.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        )

    cw, ch = canvas
    scale = min(paper_frac * cw / pw, 0.85 * ch / ph)
    arr = cv2.resize(arr, (int(pw * scale), int(ph * scale)), interpolation=cv2.INTER_AREA)
    pw, ph = arr.shape[1], arr.shape[0]

    background = np.full((ch, cw), 70, dtype=np.float32)
    background += np.random.default_rng(seed).normal(0, 12, background.shape)
    background = cv2.GaussianBlur(background, (0, 0), 3)

    # Place paper with a perspective tilt plus rotation.
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    cx, cy = cw / 2 + rng.uniform(-60, 60), ch / 2 + rng.uniform(-60, 60)
    theta = np.deg2rad(angle)
    corners = []
    for x, y in src:
        x, y = x - pw / 2, y - ph / 2
        x *= 1 + 0.04 * (y / ph)  # far end slightly narrower
        corners.append(
            [cx + x * np.cos(theta) - y * np.sin(theta), cy + x * np.sin(theta) + y * np.cos(theta)]
        )
    matrix = cv2.getPerspectiveTransform(src, np.float32(corners))
    warped = cv2.warpPerspective(arr, matrix, (cw, ch), borderValue=0)
    mask = cv2.warpPerspective(np.ones_like(arr), matrix, (cw, ch), borderValue=0)
    image = background * (1 - mask) + warped * mask

    # A soft diagonal shadow, as from a phone held over the receipt.
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    ramp = np.clip((xx / cw + yy / ch - 0.6) * 2.5, 0, 1)
    image *= 1 - shadow * ramp

    pil = Image.fromarray(np.clip(image, 0, 255).astype(np.uint8))
    if blur:
        pil = pil.filter(ImageFilter.GaussianBlur(blur))
    grain = np.random.default_rng(seed + 1).normal(0, 6, (ch, cw))
    noisy = np.asarray(pil, dtype=np.float32) + grain
    rgb = Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8)).convert("RGB")
    rgb.save(path, "JPEG", quality=85)
    return path
