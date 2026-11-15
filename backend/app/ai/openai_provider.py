"""OpenAI-compatible provider (OpenAI, OpenRouter, Ollama, LM Studio, ...).

Structured output degrades gracefully because many servers and models reject
``response_format`` JSON schemas: json_schema -> json_object -> plain prompting with
tolerant JSON extraction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import openai

from ..receipts.types import ParsedReceipt
from . import common
from .base import AIConfig, AIError, ImageInput, LineMatch, MatchCandidate, MatchLine

# Used only when talking to OpenAI itself (no base_url) and no model is configured.
# gpt-4.1-mini is the cheaper alternative.
DEFAULT_MODEL = "gpt-4.1"
OPENAI_URL = "https://api.openai.com/v1"
PLACEHOLDER_KEY = "not-needed"  # local servers ignore it, the SDK insists on one

EXTRACT_MAX_TOKENS = 8_000
MATCH_MAX_TOKENS = 4_000
PING_MAX_TOKENS = 32
# OpenAI "high" detail fits images within 2048px before tiling; comparable for others.
MAX_IMAGE_EDGE = 2048
REQUEST_TIMEOUT = 120.0
LOCAL_REQUEST_TIMEOUT = 600.0  # CPU inference on a home server can be slow

_MODES = ("json_schema", "json_object", "plain")


class OpenAICompatProvider:
    name = "openai"

    def __init__(
        self,
        cfg: AIConfig,
        *,
        http_client: Any = None,
        max_retries: int = 2,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (cfg.base_url or "").strip().rstrip("/") or None
        key = (cfg.api_key or "").strip()
        model = (cfg.model or "").strip()
        if not model:
            if self._base_url:
                raise AIError(
                    "Enter a model name for the AI server "
                    "(for example 'llava' or 'qwen2.5vl'); it cannot be guessed."
                )
            model = DEFAULT_MODEL
        if not key and not self._base_url:
            raise AIError("An OpenAI API key is required.")
        self.model = model
        if timeout is None:
            timeout = LOCAL_REQUEST_TIMEOUT if self._base_url else REQUEST_TIMEOUT
        self._client = openai.AsyncOpenAI(
            api_key=key or PLACEHOLDER_KEY,
            base_url=self._base_url or OPENAI_URL,  # explicit: ignore OPENAI_BASE_URL env
            timeout=openai.Timeout(timeout, connect=10.0),
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
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
            }

        def messages(include_schema: bool) -> list[dict[str, Any]]:
            system = common.EXTRACT_SYSTEM
            return [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": common.extract_user_blocks(
                        prepared, ocr_text, image_block, include_schema=include_schema
                    ),
                },
            ]

        return await self._structured(
            messages, common.RECEIPT_SCHEMA, "receipt", EXTRACT_MAX_TOKENS, common.receipt_from_data
        )

    async def match_lines(
        self, store_name: str | None, lines: list[MatchLine], candidates: list[MatchCandidate]
    ) -> list[LineMatch]:
        if not lines or not candidates:
            return []

        def messages(include_schema: bool) -> list[dict[str, Any]]:
            return [
                {"role": "system", "content": common.MATCH_SYSTEM},
                {
                    "role": "user",
                    "content": common.match_user_text(
                        store_name, lines, candidates, include_schema=include_schema
                    ),
                },
            ]

        return await self._structured(
            messages,
            common.MATCH_SCHEMA,
            "matches",
            MATCH_MAX_TOKENS,
            lambda data: common.matches_from_data(data, lines, candidates),
        )

    async def ping(self) -> str:
        try:
            resp = await self._create(
                [{"role": "user", "content": common.PING_PROMPT}], PING_MAX_TOKENS, None
            )
        except openai.OpenAIError as e:
            raise self._map_error(e) from e
        return getattr(resp, "model", None) or self.model

    # ------------------------------------------------------------------ internals
    async def _create(
        self, messages: list[dict[str, Any]], max_tokens: int, response_format: dict | None
    ) -> Any:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if self._base_url:
            # Local/compatible servers generally only know the classic parameter names.
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = 0
        else:
            # Newer OpenAI models (reasoning models) reject max_tokens/temperature.
            kwargs["max_completion_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        return await self._client.chat.completions.create(**kwargs)

    async def _structured(
        self,
        build_messages: Callable[[bool], list[dict[str, Any]]],
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int,
        convert: Callable[[Any], Any],
    ) -> Any:
        for mode in _MODES:
            response_format: dict | None = None
            if mode == "json_schema":
                response_format = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                }
            elif mode == "json_object":
                response_format = {"type": "json_object"}
            last = mode == _MODES[-1]

            try:
                resp = await self._create(
                    build_messages(mode != "json_schema"), max_tokens, response_format
                )
            except (openai.BadRequestError, openai.UnprocessableEntityError) as e:
                if last or _is_image_problem(e):
                    raise self._map_error(e) from e
                continue  # server/model dislikes this response_format; degrade
            except openai.OpenAIError as e:
                raise self._map_error(e) from e

            text = self._reply_text(resp)
            try:
                return convert(common.parse_json_loose(text))
            except common.UnusableOutput as e:
                if last:
                    raise AIError(f"The AI's answer could not be understood: {e}") from e
        raise AIError("The AI's answer could not be understood.")  # pragma: no cover

    @staticmethod
    def _reply_text(resp: Any) -> str:
        if not resp.choices:
            raise AIError("The AI server returned an empty reply.")
        choice = resp.choices[0]
        message = choice.message
        if getattr(message, "refusal", None) or choice.finish_reason == "content_filter":
            raise AIError("The AI declined to process this request. Try the built-in reader.")
        if choice.finish_reason == "length":
            raise AIError(
                "The AI ran out of room before finishing its answer. "
                "Try fewer photos or a larger output limit on the server."
            )
        return message.content or ""

    def _where(self) -> str:
        return f"the AI server at {self._base_url}" if self._base_url else "OpenAI"

    def _map_error(self, e: openai.OpenAIError) -> AIError:
        if isinstance(e, AIError):  # pragma: no cover - defensive
            return e
        if isinstance(e, openai.AuthenticationError):
            return AIError("The API key was rejected. Check that it is correct and active.")
        if isinstance(e, openai.PermissionDeniedError):
            return AIError("The API key does not have permission to use this model.")
        if isinstance(e, openai.NotFoundError):
            hint = " (or the server address is wrong; it normally ends in /v1)"
            return AIError(
                f"Model '{self.model}' was not found on this server"
                + (hint if self._base_url else "")
                + "."
            )
        if isinstance(e, openai.RateLimitError):
            if getattr(e, "code", None) == "insufficient_quota":
                return AIError("The account is out of credit or quota. Add credit and retry.")
            return AIError("The AI service is rate limiting requests. Wait a minute and retry.")
        if isinstance(e, openai.APITimeoutError):
            return AIError("The AI service took too long to respond. Try again.")
        if isinstance(e, openai.APIConnectionError):
            return AIError(
                f"Could not connect to {self._where()}. "
                "Check the address and that the server is running."
            )
        if isinstance(e, openai.APIStatusError):
            if e.status_code >= 500:
                return AIError("The AI service is temporarily unavailable. Try again shortly.")
            if _is_image_problem(e):
                return AIError(
                    f"Model '{self.model}' does not appear to accept images. "
                    "Choose a vision-capable model."
                )
            return AIError(f"The AI service rejected the request: {_api_message(e)}")
        return AIError("The AI request failed unexpectedly.")


def _api_message(e: openai.APIStatusError) -> str:
    body = e.body
    if isinstance(body, dict):
        msg = body.get("message")
        if isinstance(msg, str):
            return msg[:300]
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"][:300]
        if isinstance(err, str):
            return err[:300]
    return (e.message or "")[:300]


def _is_image_problem(e: openai.APIStatusError) -> bool:
    text = _api_message(e).lower()
    return any(w in text for w in ("image", "vision", "multimodal", "multi-modal"))
