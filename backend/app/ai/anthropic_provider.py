"""Anthropic (Claude) provider: base64 image blocks + schema-constrained JSON output."""

from __future__ import annotations

from typing import Any

import anthropic

from ..receipts.types import ParsedReceipt
from . import common
from .base import AIConfig, AIError, ImageInput, LineMatch, MatchCandidate, MatchLine

# Default: the skill's recommended general-purpose model. Override via AIConfig.model;
# claude-sonnet-5-5 is the cheaper step down, claude-haiku-5-5 the cheapest.
DEFAULT_MODEL = "claude-opus-5-5"
API_URL = "https://api.anthropic.com"

# Opus-class models run with adaptive thinking on, and thinking tokens count against
# max_tokens, so leave generous headroom over the JSON itself.
EXTRACT_MAX_TOKENS = 16_000
MATCH_MAX_TOKENS = 8_000
PING_MAX_TOKENS = 256
# Claude downsamples anything beyond ~2576px on the long edge anyway; receipts are tall and
# narrow, so keep as much of that as allowed for legibility.
MAX_IMAGE_EDGE = 2576
REQUEST_TIMEOUT = 180.0


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        cfg: AIConfig,
        *,
        http_client: Any = None,
        max_retries: int = 2,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        key = (cfg.api_key or "").strip()
        if not key:
            raise AIError("An Anthropic API key is required.")
        self.model = (cfg.model or "").strip() or DEFAULT_MODEL
        # Construction only builds an object; no network access happens until a call.
        self._client = anthropic.AsyncAnthropic(
            api_key=key,
            base_url=API_URL,  # explicit, so a stray ANTHROPIC_BASE_URL can't redirect the key
            timeout=anthropic.Timeout(timeout, connect=10.0),
            max_retries=max_retries,
            http_client=http_client,
        )

    # ------------------------------------------------------------------ public API
    async def extract_receipt(
        self, images: list[ImageInput], ocr_text: str | None = None
    ) -> ParsedReceipt:
        if not images:
            raise AIError("There is no receipt image to read.")
        try:
            prepared = [common.prepare_image(i, max_edge=MAX_IMAGE_EDGE) for i in images]
        except common.UnusableOutput as e:
            raise AIError(str(e)) from e

        def image_block(b64: str) -> dict[str, Any]:
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            }

        content = common.extract_user_blocks(prepared, ocr_text, image_block)
        data = await self._structured(
            system=common.EXTRACT_SYSTEM,
            content=content,
            schema=common.RECEIPT_SCHEMA,
            max_tokens=EXTRACT_MAX_TOKENS,
        )
        try:
            return common.receipt_from_data(data)
        except common.UnusableOutput as e:
            raise AIError(f"The AI's answer could not be used: {e}") from e

    async def match_lines(
        self, store_name: str | None, lines: list[MatchLine], candidates: list[MatchCandidate]
    ) -> list[LineMatch]:
        if not lines or not candidates:
            return []
        data = await self._structured(
            system=common.MATCH_SYSTEM,
            content=common.match_user_text(store_name, lines, candidates),
            schema=common.MATCH_SCHEMA,
            max_tokens=MATCH_MAX_TOKENS,
        )
        try:
            return common.matches_from_data(data, lines, candidates)
        except common.UnusableOutput as e:
            raise AIError(f"The AI's answer could not be used: {e}") from e

    async def ping(self) -> str:
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=PING_MAX_TOKENS,
                messages=[{"role": "user", "content": common.PING_PROMPT}],
            )
        except anthropic.AnthropicError as e:
            raise self._map_error(e) from e
        return resp.model or self.model

    # ------------------------------------------------------------------ internals
    async def _structured(
        self, *, system: str, content: Any, schema: dict[str, Any], max_tokens: int
    ) -> Any:
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AnthropicError as e:
            raise self._map_error(e) from e

        if resp.stop_reason == "refusal":
            raise AIError("The AI declined to process this request. Try the built-in reader.")
        if resp.stop_reason == "max_tokens":
            raise AIError(
                "The AI ran out of room before finishing its answer. "
                "Try fewer photos or a shorter receipt."
            )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return common.parse_json_loose(text)
        except common.UnusableOutput as e:
            raise AIError(f"The AI's answer could not be understood: {e}") from e

    def _map_error(self, e: anthropic.AnthropicError) -> AIError:
        # Order matters: APITimeoutError is a subclass of APIConnectionError, and the
        # status-error classes are all subclasses of APIStatusError.
        if isinstance(e, anthropic.AuthenticationError):
            return AIError("The API key was rejected. Check that it is correct and active.")
        if isinstance(e, anthropic.PermissionDeniedError):
            return AIError("The API key does not have permission to use this model.")
        if isinstance(e, anthropic.NotFoundError):
            return AIError(f"Model '{self.model}' was not found. Check the model name.")
        if isinstance(e, anthropic.RateLimitError):
            return AIError("The AI service is rate limiting requests. Wait a minute and retry.")
        if isinstance(e, anthropic.APITimeoutError):
            return AIError("The AI service took too long to respond. Try again.")
        if isinstance(e, anthropic.APIConnectionError):
            return AIError("Could not reach the Anthropic API. Check the internet connection.")
        if isinstance(e, anthropic.APIStatusError):
            msg = _api_message(e)
            if "credit balance" in msg.lower():
                return AIError("The Anthropic account is out of credit. Add credit and retry.")
            if e.status_code == 413:
                return AIError("The receipt photos are too large for the AI. Try fewer photos.")
            if e.status_code >= 500:  # includes 529 "overloaded"
                return AIError("The AI service is temporarily unavailable. Try again shortly.")
            return AIError(f"The AI service rejected the request: {msg}")
        return AIError("The AI request failed unexpectedly.")


def _api_message(e: anthropic.APIStatusError) -> str:
    body = e.body
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"][:300]
    return (e.message or "")[:300]
