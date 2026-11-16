"""Accounts are Grocy accounts. Signing in proves who someone is to Grocy and
leaves the app holding a personal Grocy API key for them; admin status is
whatever Grocy says it is; and when Grocy stops accepting the key, the app
session ends with it."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_config
from ..db import session_scope
from ..errors import GROCY_ACCOUNT_INVALID
from ..grocy.client import GrocyClient, GrocyError
from ..grocy.login import ApiKeyRequired, WebSession
from ..models import AuthSession, User, aware, utcnow
from ..security import decrypt, encrypt, hash_token

log = logging.getLogger(__name__)

ADMIN_RECHECK_AFTER = timedelta(hours=1)
# How soon to ask again when the re-check couldn't reach Grocy.
ADMIN_RECHECK_RETRY = timedelta(minutes=1)
# Someone counts as "using the app" for this long after their last request. Open
# pages check in more often than this, so it only lapses once the app is closed.
ACTIVE_WITHIN_SECONDS = 90.0

_last_seen: dict[int, float] = {}  # user id -> time.monotonic() of their last request
# A page that opens with several requests at once would otherwise sign the same
# person in several times side by side: a Grocy key each, and one user row too many.
_proxy_sign_ins: dict[str, asyncio.Lock] = {}  # the proxy's name for someone -> their turn


def grocy_for(user: User, http: httpx.AsyncClient) -> GrocyClient:
    """A Grocy client acting as `user`."""
    key = decrypt(user.grocy_api_key_enc)
    if not key:
        # Only reachable if the stored key can't be decrypted any more (GA_SECRET_KEY
        # changed). Signing in again mints a fresh one, so treat it like a dead key.
        raise GrocyError("No usable Grocy API key is stored for this account", 401)
    return GrocyClient(get_config().grocy_base, key, http)


async def _key_is_for(client: GrocyClient, grocy_user_id: int) -> bool:
    try:
        who = await client.current_user()
    except GrocyError as exc:
        if exc.status == 401:
            return False
        raise
    return str(who.get("id")) == str(grocy_user_id)


async def _remember(
    db: Session, http: httpx.AsyncClient, who: dict, api_key: str, user: User | None
) -> User:
    """Create or refresh the user row for a Grocy identity whose key was just verified."""
    grocy_user_id = int(who["id"])
    if user is None:
        user = User(grocy_user_id=grocy_user_id)
        db.add(user)
    user.username = str(who.get("username") or grocy_user_id)
    user.display_name = str(who.get("display_name") or "").strip() or user.username
    if decrypt(user.grocy_api_key_enc) != api_key:
        user.grocy_api_key_enc = encrypt(api_key)
    # Saved before anything else can fail, so a retry reuses this key, not mints another.
    db.commit()
    user.is_admin = await grocy_for(user, http).is_admin(grocy_user_id)
    user.admin_checked_at = utcnow()
    db.commit()
    return user


def _by_grocy_id(db: Session, grocy_user_id: int) -> User | None:
    return db.scalar(select(User).where(User.grocy_user_id == grocy_user_id))


async def sign_in_with_password(
    db: Session,
    http: httpx.AsyncClient,
    new_login_http: Callable[[], httpx.AsyncClient],
    username: str,
    password: str,
) -> User:
    """Check the credentials with Grocy, then make sure the app holds a working API
    key for that person: the one it already has if Grocy still accepts it, a newly
    minted one otherwise. The password is used for the Grocy login and nothing else.

    Raises BadCredentials, ApiKeyRequired or GrocyError."""
    base = get_config().grocy_base
    # A client of its own for the cookie-based part; see grocy/login.py for why.
    async with new_login_http() as login_http:
        web = WebSession(base, login_http)
        try:
            who = await web.login(username, password)
            user, api_key = await _key_for(db, http, web, who)
        finally:
            await web.logout()
    return await _remember(db, http, who, api_key, user)


async def sign_in_from_proxy(
    db: Session,
    http: httpx.AsyncClient,
    new_login_http: Callable[[], httpx.AsyncClient],
    header: str,
    username: str,
) -> User:
    """Sign in the person a single-sign-on proxy in front of both this app and Grocy
    says is making the request (GA_TRUSTED_USER_HEADER). Grocy is asked with that same
    header, so it is Grocy that decides who `username` is, exactly as it does for
    its own pages; the app then holds an API key for them like after any sign-in.

    Raises ApiKeyRequired (signed_in=False when Grocy doesn't accept the header) or
    GrocyError."""
    # One at a time per person: whoever waited finds the key the first one stored.
    async with _proxy_sign_ins.setdefault(username, asyncio.Lock()):
        async with new_login_http() as login_http:
            web = WebSession(get_config().grocy_base, login_http, headers={header: username})
            who = await web.current_user()
            if who is None:
                await web.load_start_page()
                who = await web.current_user()
            if who is None:
                raise ApiKeyRequired("Grocy didn't accept the proxy's user header", signed_in=False)
            user, api_key = await _key_for(db, http, web, who)
        return await _remember(db, http, who, api_key, user)


async def _key_for(
    db: Session, http: httpx.AsyncClient, web: WebSession, who: dict
) -> tuple[User | None, str]:
    """The app's user row for `who` (if any) and a Grocy API key that works for them:
    the one already stored if Grocy still accepts it, else one minted through `web`,
    which must be signed in to Grocy as `who`."""
    base = get_config().grocy_base
    grocy_user_id = int(who["id"])
    user = _by_grocy_id(db, grocy_user_id)
    api_key = decrypt(user.grocy_api_key_enc) if user else None
    if api_key and await _key_is_for(GrocyClient(base, api_key, http), grocy_user_id):
        return user, api_key
    api_key = await web.mint_api_key()
    # An admin's key page shows everyone's keys; never trust the pick blindly.
    if not await _key_is_for(GrocyClient(base, api_key, http), grocy_user_id):
        raise ApiKeyRequired("the key read back isn't this user's", signed_in=True)
    log.info("Created a Grocy API key for %s", who.get("username"))
    return user, api_key


async def sign_in_with_api_key(db: Session, http: httpx.AsyncClient, api_key: str) -> User:
    """The fallback: the person pasted a Grocy API key; whoever it belongs to signs in.

    Raises GrocyError (status 401 when Grocy rejects the key)."""
    who = await GrocyClient(get_config().grocy_base, api_key, http).current_user()
    if who.get("id") is None:
        raise GrocyError("Grocy didn't say whose API key that is")
    return await _remember(db, http, who, api_key, _by_grocy_id(db, int(who["id"])))


async def refresh_admin(db: Session, user: User, http: httpx.AsyncClient) -> None:
    """Bring `user.is_admin` back in line with Grocy if it was last checked a while ago."""
    checked = aware(user.admin_checked_at)
    if checked is not None and utcnow() - checked < ADMIN_RECHECK_AFTER:
        return
    try:
        user.is_admin = await grocy_for(user, http).is_admin(user.grocy_user_id)
        user.admin_checked_at = utcnow()
    except GrocyError as exc:
        if exc.status == 401:
            raise
        # Grocy is down or erroring: keep the last known answer rather than fail the
        # request, and look again in a minute instead of on every request until then.
        log.warning("Couldn't re-check %s's admin status: %s", user.username, exc.message)
        user.admin_checked_at = utcnow() - ADMIN_RECHECK_AFTER + ADMIN_RECHECK_RETRY
    db.commit()


def find_session(db: Session, token: str | None) -> AuthSession | None:
    """The unexpired session a cookie belongs to. It may be one the app has ended
    (`ended_reason`); those are kept so the device can be told why."""
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None:
        return None
    if aware(session.expires_at) <= utcnow():
        db.delete(session)
        db.commit()
        return None
    return session


def session_user(db: Session, token: str | None) -> User | None:
    """The user a session cookie belongs to, if it is a live session."""
    session = find_session(db, token)
    return session.user if session is not None and session.ended_reason is None else None


def sign_out_everywhere(db: Session, user: User) -> None:
    """Grocy rejected this user's key (the Grocy account or the key is gone). The key
    is the same on all their devices, so every session ends and the key is dropped."""
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.ended_reason.is_(None))
        .values(ended_reason=GROCY_ACCOUNT_INVALID)
    )
    user.grocy_api_key_enc = None
    db.commit()
    _last_seen.pop(user.id, None)
    log.info("Signed %s out everywhere: Grocy no longer accepts their API key", user.username)


# --- noticing a dead key without waiting for the person to do something -------------


def note_seen(user_id: int) -> None:
    """Called on every signed-in request; decides whose keys are worth re-checking."""
    _last_seen[user_id] = time.monotonic()


def reset_activity() -> None:
    _last_seen.clear()
    _proxy_sign_ins.clear()


async def check_active_keys(http: httpx.AsyncClient) -> None:
    """Ask Grocy whether it still accepts the key of everyone using the app right now,
    and sign out those it rejects.

    Without this, a person whose Grocy account was deleted stays signed in until one
    of their own requests happens to reach Grocy, which an open, idle page never
    does. Only people seen in the last minute and a half are checked, so a household
    that isn't using the app causes no traffic to Grocy at all."""
    cutoff = time.monotonic() - ACTIVE_WITHIN_SECONDS
    for user_id in [uid for uid, seen in _last_seen.items() if seen < cutoff]:
        del _last_seen[user_id]
    if not _last_seen:
        return
    with session_scope() as db:
        users = db.scalars(select(User).where(User.id.in_(list(_last_seen))))
        keys = [(u.id, u.grocy_api_key_enc, decrypt(u.grocy_api_key_enc)) for u in users]
    base = get_config().grocy_base
    for user_id, stored, api_key in keys:
        if not api_key:
            continue
        try:
            await GrocyClient(base, api_key, http).current_user()
        except GrocyError as exc:
            if exc.status != 401:
                return  # Grocy is down or erroring: that says nothing about anyone's key
            with session_scope() as db:
                user = db.get(User, user_id)
                # Unless they signed in again (new key) while Grocy was being asked.
                if user is not None and user.grocy_api_key_enc == stored:
                    sign_out_everywhere(db, user)
