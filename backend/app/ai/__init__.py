"""Optional AI assist. ``build_provider`` is the only entry point the app uses."""

from .anthropic_provider import AnthropicProvider
from .base import AIConfig, AIError, AIProvider
from .openai_provider import OpenAICompatProvider


def build_provider(cfg: AIConfig) -> AIProvider:
    """Create a provider for ``cfg``. Cheap: no network access happens here.

    Raises ``AIError`` for an unknown provider or incomplete configuration."""
    kind = (cfg.provider or "").strip().lower()
    if kind == "anthropic":
        return AnthropicProvider(cfg)
    if kind == "openai":
        return OpenAICompatProvider(cfg)
    raise AIError(f"Unknown AI provider '{cfg.provider}'. Supported: anthropic, openai.")


__all__ = ["AIConfig", "AIError", "AIProvider", "build_provider"]
