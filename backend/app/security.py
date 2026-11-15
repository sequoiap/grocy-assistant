"""Opaque session tokens and at-rest encryption for stored API keys. There are no
passwords here: people sign in with their Grocy account (see services/accounts.py)."""

import base64
import hashlib
import os
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from .config import get_config

SESSION_COOKIE = "ga_session"


def new_session_token() -> tuple[str, str]:
    """Returns (token for the cookie, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache
def _fernet() -> Fernet:
    cfg = get_config()
    if cfg.secret_key:
        # Accept any passphrase by stretching it to a Fernet-shaped key.
        key = base64.urlsafe_b64encode(hashlib.sha256(cfg.secret_key.encode()).digest())
    else:
        key_file = cfg.data_dir / "secret.key"
        if key_file.exists():
            key = key_file.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(key)
    return Fernet(key)


def reset_crypto_cache() -> None:
    _fernet.cache_clear()


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        # Secret key changed; the stored key is unrecoverable and must be re-entered.
        return None
