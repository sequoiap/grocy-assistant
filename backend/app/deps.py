from datetime import timedelta

import httpx
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .ai import build_provider
from .ai.base import AIError, AIProvider
from .config import get_config
from .db import get_db
from .errors import account_invalid
from .grocy.client import GrocyClient
from .models import AuthSession, User, utcnow
from .schemas import UserOut
from .security import SESSION_COOKIE, new_session_token
from .services.accounts import find_session, grocy_for, note_seen, refresh_admin
from .services.settings import resolve_ai


def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session = find_session(db, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(401, "Not signed in")
    if session.ended_reason is not None:
        # Grocy stopped accepting this person's account and the app signed them out;
        # every device still holding the cookie learns why.
        raise account_invalid()
    note_seen(session.user_id)
    return session.user


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
