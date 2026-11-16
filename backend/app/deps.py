import logging
from datetime import timedelta

import httpx
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .ai import build_provider
from .ai.base import AIError, AIProvider
from .config import get_config
from .db import get_db
from .errors import ApiError, account_invalid
from .grocy.client import GrocyClient, GrocyError, GrocyUnreachable
from .grocy.login import ApiKeyRequired
from .models import AuthSession, User, utcnow
from .schemas import UserOut
from .security import SESSION_COOKIE, new_session_token
from .services.accounts import (
    find_session,
    grocy_for,
    note_seen,
    refresh_admin,
    sign_in_from_proxy,
)
from .services.settings import resolve_ai

log = logging.getLogger(__name__)


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def current_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http),
) -> User:
    session = find_session(db, request.cookies.get(SESSION_COOKIE))
    header = get_config().trusted_header
    proxied = _proxy_user(request, header) if header else ""
    if proxied and (
        session is None or session.ended_reason is not None or session.user.username != proxied
    ):
        # The proxy says someone is here who this browser isn't signed in as (yet):
        # nobody, someone else (the proxy's sign-in changed), or a signed-out account.
        user = await _sign_in_from_proxy(db, http, request, header, proxied)
        if user is not None:
            if session is not None:
                db.delete(session)
                db.commit()
            start_session(db, user, request, response)
            note_seen(user.id)
            return user
    if session is None:
        raise HTTPException(401, "Not signed in")
    if session.ended_reason is not None:
        # Grocy stopped accepting this person's account and the app signed them out;
        # every device still holding the cookie learns why.
        raise account_invalid()
    note_seen(session.user_id)
    return session.user


def _proxy_user(request: Request, header: str) -> str:
    """Who the single-sign-on proxy says is making this request; "" if it doesn't say,
    or if what says so isn't the proxy."""
    values = request.headers.getlist(header)
    if not values:
        return ""
    peer = request.client.host if request.client else None
    if not get_config().is_trusted_proxy(peer):
        # Anyone can type a header. Only the proxy's own connections are believed.
        _warn_once(
            f"peer {peer}",
            "Ignoring %s on a request from %s, which is not in GA_TRUSTED_PROXIES",
            header,
            peer,
        )
        return ""
    if len(values) != 1:
        # A proxy that adds its header next to one the browser sent, instead of
        # replacing it. Grocy refuses these as well.
        _warn_once(
            "repeated",
            "Ignoring %s: it arrived %d times. The proxy has to replace this header, not add to it",
            header,
            len(values),
        )
        return ""
    return values[0].strip()


_warned: set[str] = set()


def _warn_once(about: str, message: str, *args: object) -> None:
    """These would otherwise be logged for every request of a misconfigured setup."""
    if about not in _warned and len(_warned) < 50:
        _warned.add(about)
        log.warning(message, *args)


def reset_warnings() -> None:
    _warned.clear()


async def _sign_in_from_proxy(
    db: Session, http: httpx.AsyncClient, request: Request, header: str, username: str
) -> User | None:
    """The proxy's user, signed in; None if Grocy doesn't accept the header, which
    leaves the request to the usual session cookie (or the sign-in screen)."""
    try:
        return await sign_in_from_proxy(
            db, http, request.app.state.new_login_http, header, username
        )
    except ApiKeyRequired as exc:
        # Most likely Grocy isn't set up to trust this header.
        log.warning("Signing in %s from %s failed: %s", username, header, exc)
        return None
    except GrocyError as exc:
        if isinstance(exc, GrocyUnreachable):
            raise
        # Answered here, not by the app-wide handler: a 401 there means a stored key
        # died, which is not what happened.
        log.warning("Signing in %s from %s failed: %s", username, header, exc.message)
        raise ApiError(502, exc.message) from None


async def fresh_user(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http),
) -> User:
    """The signed-in user, with their admin flag re-checked against Grocy if it is
    more than an hour old. For endpoints where being an admin changes the answer."""
    await refresh_admin(db, user, http)
    return user


def require_admin(user: User = Depends(fresh_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Only Grocy admins can do this")
    return user


def get_grocy(
    user: User = Depends(current_user), http: httpx.AsyncClient = Depends(get_http)
) -> GrocyClient:
    return grocy_for(user, http)


def get_ai(user: User = Depends(current_user), db: Session = Depends(get_db)) -> AIProvider | None:
    """The AI provider this user's requests get: their own, else the household's."""
    cfg = resolve_ai(db, user).config
    if cfg is None:
        return None
    try:
        return build_provider(cfg)
    except AIError:
        return None


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        is_admin=user.is_admin,
    )


def start_session(db: Session, user: User, request: Request, response: Response) -> None:
    cfg = get_config()
    token, token_hash = new_session_token()
    db.add(
        AuthSession(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=cfg.session_days),
        )
    )
    db.commit()
    if cfg.cookie_secure == "auto":
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        secure = proto.split(",")[0].strip() == "https"
    else:
        secure = cfg.cookie_secure.lower() in ("1", "true", "yes")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=cfg.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
