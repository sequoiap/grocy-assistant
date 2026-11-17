import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_config
from ..db import get_db
from ..deps import fresh_user, get_http, proxy_user, start_session, user_out
from ..errors import API_KEY_REQUIRED, GROCY_UNREACHABLE, ApiError
from ..grocy.client import GrocyError, GrocyUnreachable
from ..grocy.login import ApiKeyRequired, BadCredentials
from ..models import AuthSession, User
from ..schemas import LoginIn, MeOut, StatusOut, UserOut
from ..security import SESSION_COOKIE, hash_token
from ..services.accounts import sign_in_with_api_key, sign_in_with_password

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/status", response_model=StatusOut)
def status():
    return StatusOut(version=__version__, single_sign_on=get_config().trusted_header is not None)


@router.post("/auth/login", response_model=UserOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    http: httpx.AsyncClient = Depends(get_http),
):
    """Sign in with a Grocy account. Normally that is the Grocy username and
    password; a Grocy API key on its own also works, for when the app can't get a
    key by itself (see the 409) or Grocy doesn't use its built-in login form."""
    api_key = (body.api_key or "").strip()
    username = (body.username or "").strip()
    if not api_key and not (username and body.password):
        raise HTTPException(422, "Enter your Grocy username and password, or a Grocy API key")
    # Grocy errors are all answered here. In particular a 401 must not reach the
    # app-wide handler, which would treat it as a signed-in user's key dying.
    try:
        if api_key:
            user = await sign_in_with_api_key(db, http, api_key)
        else:
            user = await sign_in_with_password(
                db, http, request.app.state.new_login_http, username, body.password
            )
    except BadCredentials:
        raise ApiError(401, "Wrong username or password") from None
    except ApiKeyRequired as exc:
        raise ApiError(
            409,
            "Grocy accepted the sign-in, but this app couldn't get an API key from it. "
            "Create one in Grocy under Manage API keys and enter it here."
            if exc.signed_in
            else "This Grocy doesn't take a username and password here. "
            "Sign in with a Grocy API key instead.",
            API_KEY_REQUIRED,
        ) from None
    except GrocyUnreachable:
        raise ApiError(
            503, "Grocy is unreachable right now. Try again in a moment.", GROCY_UNREACHABLE
        ) from None
    except GrocyError as exc:
        if exc.status == 401:
            detail = "Grocy rejected that API key" if api_key else "Grocy rejected the sign-in"
            raise ApiError(401, detail) from None
        raise ApiError(502, exc.message) from None
    start_session(db, user, request, response)
    return user_out(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=MeOut)
def me(request: Request, user: User = Depends(fresh_user)):
    return MeOut(**user_out(user).model_dump(), via_proxy=proxy_user(request) == user.username)


@router.get("/auth/through-proxy", include_in_schema=False)
def through_proxy(next: str = "/"):
    """Where the PWA sends the whole browser when something in front of the app (a
    single-sign-on proxy whose own session ran out) has to show its sign-in page.

    The PWA's pages are served from the phone's cache without asking the network,
    and its API calls can't follow a redirect to another site, so that proxy never
    gets to show anything. A page load of this address is not cached: the proxy
    sees it, signs the person in, and they come back here to be sent on to `next`."""
    local = next.startswith("/") and not next.startswith(("//", "/\\"))
    return RedirectResponse(
        next if local else "/", status_code=303, headers={"Cache-Control": "no-store"}
    )
