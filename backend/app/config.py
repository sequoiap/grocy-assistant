"""Process-level configuration, read from environment variables (prefix ``GA_``).

Which Grocy the app talks to is fixed here on purpose: people type their Grocy
password into this app, so the address it is sent to must not be something that
can be changed from the web UI. The AI provider is the only thing edited at
runtime (Settings page); it lives in the database.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """The environment is missing something the app can't run without."""


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GA_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    # Directory holding the built PWA. Empty/missing means API-only (dev mode).
    static_dir: Path = Path(__file__).parent / "static"
    # Required. The Grocy everyone signs in to, e.g. https://grocy.example.com or
    # https://example.com/grocy. Must be reachable from where this app runs.
    grocy_url: str = ""
    # For a Grocy behind a single-sign-on proxy (Grocy's ReverseProxyAuthMiddleware):
    # the request header, e.g. X-Authentik-Username or Remote-User, in which that
    # proxy names the signed-in person. When set, a request carrying it is signed in
    # as that Grocy user with no sign-in screen, and the header is passed on to Grocy
    # under the same name to get them an API key. Only set this if every request
    # reaches the app through that proxy and the proxy overwrites the header: whoever
    # can send it directly can sign in as anyone.
    trusted_user_header: str = ""
    # Used to encrypt stored Grocy/AI API keys. Generated into data_dir if unset.
    secret_key: str | None = None
    # "auto" marks the session cookie Secure whenever the request arrived over HTTPS
    # (directly or via X-Forwarded-Proto from Caddy / Tailscale Serve).
    cookie_secure: str = "auto"
    session_days: int = 90
    max_upload_mb: int = 25
    # Below this OCR confidence the AI fallback (if configured) is consulted.
    ocr_confidence_threshold: float = 0.6
    grocy_cache_seconds: int = 30
    # How often the Grocy key of each person currently using the app is re-checked,
    # so someone whose Grocy account was deleted is signed out promptly. 0 = never.
    key_check_seconds: float = 15.0
    grocy_timeout_seconds: float = 20.0

    @property
    def grocy_base(self) -> str:
        """Grocy's web root: scheme, host and any sub-path, without ``/api``."""
        url = self.grocy_url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        return url.removesuffix("/api").rstrip("/")

    @property
    def trusted_header(self) -> str | None:
        return self.trusted_user_header.strip() or None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "grocy-assistant.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "receipts"

    @property
    def snapshot_path(self) -> Path:
        """Last good copy of Grocy's master data, served while Grocy is down."""
        return self.data_dir / "grocy-master-data.json"


@lru_cache
def get_config() -> Config:
    cfg = Config()
    if not cfg.grocy_url.strip():
        raise ConfigError(
            "GA_GROCY_URL is not set. Set it to the address of your Grocy, "
            "for example GA_GROCY_URL=https://grocy.example.com"
        )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.upload_dir.mkdir(parents=True, exist_ok=True)
    return cfg
