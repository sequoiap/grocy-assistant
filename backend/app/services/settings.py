"""AI provider settings: a household default an admin sets (kept in the `settings`
table) and an optional personal override stored on each user's row."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from ..ai.base import AIConfig
from ..models import Setting, User
from ..schemas import AISettingsIn, AISettingsOut
from ..security import decrypt, encrypt

DEFAULTS: dict[str, object] = {
    "ai_provider": "none",
    "ai_model": None,
    "ai_base_url": None,
    "ai_mode": "fallback",
    "ai_api_key_enc": None,
}


def get_setting(db: Session, key: str):
    row = db.get(Setting, key)
    return row.value if row is not None else DEFAULTS[key]


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


@dataclass
class _Stored:
    """One saved AI configuration, wherever it is kept."""

    provider: str
    model: str | None
    base_url: str | None
    mode: str
    api_key_enc: str | None

    def out(self) -> AISettingsOut:
        return AISettingsOut(
            provider=self.provider,
            model=self.model,
            base_url=self.base_url,
            mode=self.mode,
            api_key_set=bool(self.api_key_enc),
        )

    def config(self) -> AIConfig | None:
        """Something a provider can be built from, or None if this isn't usable."""
        if self.provider in (None, "none"):
            return None
        api_key = decrypt(self.api_key_enc)
        base_url = self.base_url or None
        if self.provider == "anthropic" and not api_key:
            return None
        if self.provider == "openai" and not api_key and not base_url:
            return None
        return AIConfig(
            provider=self.provider, api_key=api_key, model=self.model or None, base_url=base_url
        )


def _instance(db: Session) -> _Stored:
    return _Stored(
        provider=get_setting(db, "ai_provider") or "none",
        model=get_setting(db, "ai_model"),
        base_url=get_setting(db, "ai_base_url"),
        mode=get_setting(db, "ai_mode") or "fallback",
        api_key_enc=get_setting(db, "ai_api_key_enc"),
    )


def _personal(user: User) -> _Stored:
    return _Stored(
        provider=user.ai_provider or "none",
        model=user.ai_model,
        base_url=user.ai_base_url,
        mode=user.ai_mode or "fallback",
        api_key_enc=user.ai_api_key_enc,
    )


def instance_ai_out(db: Session) -> AISettingsOut:
    return _instance(db).out()


def personal_ai_out(user: User) -> AISettingsOut:
    return _personal(user).out()


def instance_ai_config(db: Session) -> AIConfig | None:
    return _instance(db).config()


def personal_ai_config(user: User) -> AIConfig | None:
    return _personal(user).config()


def _changes(body: AISettingsIn) -> dict[str, object]:
    """Stored-field -> new value for what the request actually asks to change."""
    sent = body.model_fields_set
    out: dict[str, object] = {}
    if body.provider is not None:
        out["ai_provider"] = body.provider
    if "model" in sent:
        out["ai_model"] = (body.model or "").strip() or None
    if "base_url" in sent:
        out["ai_base_url"] = (body.base_url or "").strip() or None
    if body.mode is not None:
        out["ai_mode"] = body.mode
    if body.api_key is not None:  # "" clears; an omitted or null key is left alone
        key = body.api_key.strip()
        out["ai_api_key_enc"] = encrypt(key) if key else None
    return out


def update_instance_ai(db: Session, body: AISettingsIn) -> None:
    for key, value in _changes(body).items():
        set_setting(db, key, value)


def update_personal_ai(user: User, body: AISettingsIn) -> None:
    for key, value in _changes(body).items():
        setattr(user, key, value)


@dataclass
class ResolvedAI:
    """What AI assist one user's receipts get."""

    source: Literal["personal", "instance", "none"]
    config: AIConfig | None = None
    mode: str = "fallback"


def resolve_ai(db: Session, user: User) -> ResolvedAI:
    """The user's own provider if it is usable, else the household's, else none.
    The mode (fallback/always) comes with whichever one is used."""
    for source, stored in (("personal", _personal(user)), ("instance", _instance(db))):
        cfg = stored.config()
        if cfg is not None:
            return ResolvedAI(source, cfg, stored.mode)
    return ResolvedAI("none")
