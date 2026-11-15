"""Provider-agnostic interface for the optional AI assist.

AI is never required: the built-in OCR + parsers + matcher run first, and a
provider is only consulted when one is configured *and* the programmatic path
was unsure (or the user explicitly asks for an AI re-read).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..receipts.types import ParsedReceipt


class AIError(Exception):
    """Any provider failure (auth, network, refusal, unparseable output)."""


@dataclass
class AIConfig:
    provider: str  # "anthropic" | "openai"
    api_key: str | None = None  # optional for local OpenAI-compatible servers
    model: str | None = None  # None -> provider default
    base_url: str | None = None  # OpenAI-compatible only (Ollama, OpenRouter, LM Studio...)


@dataclass
class ImageInput:
    data: bytes
    media_type: str  # image/jpeg | image/png | image/webp


@dataclass
class MatchLine:
    """An unmatched receipt line the matcher couldn't place confidently."""

    id: int
    description: str
    item_code: str | None = None
    total_price: float | None = None


@dataclass
class MatchCandidate:
    """A scanned item (or known Grocy product) a receipt line might correspond to."""

    id: int
    name: str
    barcode: str | None = None


@dataclass
class LineMatch:
    line_id: int
    candidate_id: int
    confidence: float  # 0..1


@runtime_checkable
class AIProvider(Protocol):
    name: str
    model: str

    async def extract_receipt(
        self, images: list[ImageInput], ocr_text: str | None = None
    ) -> ParsedReceipt:
        """Read receipt photo(s) (several photos = one long receipt, top to bottom)
        into a ParsedReceipt with ``method="ai"``. ``ocr_text`` is the local OCR's
        attempt, offered as a hint. Raises AIError on failure."""
        ...

    async def match_lines(
        self, store_name: str | None, lines: list[MatchLine], candidates: list[MatchCandidate]
    ) -> list[LineMatch]:
        """Pair cryptic receipt descriptions with product names. Each line and each
        candidate may be used at most once; omit lines with no plausible partner.
        Raises AIError on failure."""
        ...

    async def ping(self) -> str:
        """Cheap round-trip to validate credentials; returns a short status string
        (e.g. the model name). Raises AIError on failure."""
        ...
