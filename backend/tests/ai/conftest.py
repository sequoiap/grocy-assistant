"""Shared fixtures for AI provider tests. HTTP is mocked at the transport level: both SDKs
run on httpx2, so respx (which patches httpx) can't see their traffic; httpx2.MockTransport
exercises the real SDK request/response code instead."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest
from PIL import Image

# pyproject sets no pythonpath, so make `app` importable regardless of how pytest is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.base import ImageInput  # noqa: E402

GOOD_RECEIPT = {
    "store_name": "Smith's Food & Drug",
    "store_key": "smiths",
    "purchased_on": "2026-03-14",
    "subtotal": 10.0,
    "tax": 0.5,
    "total": 10.5,
    "items": [
        {
            "description": "GV WHL MLK GAL",
            "raw_text": "GV WHL MLK GAL 3.50",
            "item_code": "007874201234",
            "quantity": 1,
            "unit_price": 3.5,
            "total_price": 3.5,
            "discount": None,
            "weight": None,
            "weight_unit": None,
            "confidence": 0.95,
        },
        {
            "description": "BANANAS",
            "raw_text": "BANANAS | 2.31 lb @ 0.99/lb 2.29",
            "item_code": None,
            "quantity": 1,
            "unit_price": None,
            "total_price": 2.5,
            "discount": None,
            "weight": 2.31,
            "weight_unit": "lb",
            "confidence": 0.9,
        },
        {
            "description": "CHEEZ-IT",
            "raw_text": "CHEEZ-IT 5.00 | COUPON 1.50-",
            "item_code": None,
            "quantity": 2,
            "unit_price": 2.5,
            "total_price": 4.0,
            "discount": 1.0,
            "weight": None,
            "weight_unit": None,
            "confidence": 0.9,
        },
    ],
}


class Recorder:
    """Scripted HTTP responses; records every request body."""

    def __init__(self, script: list[httpx2.Response | Exception]):
        self.script = list(script)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def make_client() -> Callable[..., tuple[httpx2.AsyncClient, Recorder]]:
    def _make(*script: httpx2.Response | Exception) -> tuple[httpx2.AsyncClient, Recorder]:
        rec = Recorder(list(script))
        return httpx2.AsyncClient(transport=httpx2.MockTransport(rec)), rec

    return _make


def _png(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (250, 250, 250)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def image() -> ImageInput:
    return ImageInput(data=_png((300, 600)), media_type="image/png")


@pytest.fixture
def big_image() -> ImageInput:
    return ImageInput(data=_png((4000, 6000)), media_type="image/png")
