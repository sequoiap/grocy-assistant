"""Signing in to Grocy's web UI with a username and password, to learn who the
person is and to get them a personal API key.

Grocy's REST API has no "log in" call and can't hand out API keys, so this drives
the same pages a browser would: the login form, then "Manage API keys". Those are
UI routes, not a documented interface; when they don't behave as expected the
caller is told to fall back to a pasted API key (`ApiKeyRequired`).

Everything here runs on a client created for one sign-in and thrown away after.
It must never be the app's shared client: this flow lives on a session cookie,
and a cookie left in the shared client's jar would be replayed on other people's
API-key requests.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote

import httpx

from .client import GATEWAY_STATUSES, GrocyError, GrocyUnreachable

KEY_DESCRIPTION = "Grocy Assistant"

_TAG_WITH_KEY_ID = re.compile(r'<[^<>]*\bdata-apikey-id="(\d+)"[^<>]*>')
_KEY_ATTR = re.compile(r'\bdata-apikey-key="([^"]+)"')


class BadCredentials(Exception):
    """Grocy said the username or password is wrong."""


class ApiKeyRequired(Exception):
    """Password sign-in can't be completed on this Grocy; an API key is needed.

    `signed_in` tells the two cases apart: Grocy accepted the username and password
    but no key could be obtained (True), or it never got that far because this
    Grocy has no login form to post them to (False)."""

    def __init__(self, reason: str, signed_in: bool):
        super().__init__(reason)
        self.signed_in = signed_in


def find_api_key(page: str, key_id: str) -> str | None:
    """The key with that id on Grocy's "Manage API keys" page.

    Looked up by id on purpose: an admin's page lists every user's keys, so "the
    first key on the page" would often be somebody else's."""
    for tag in _TAG_WITH_KEY_ID.finditer(page):
        if tag[1] == key_id:
            key = _KEY_ATTR.search(tag[0])
            if key:
                return html.unescape(key[1])
    return None


class WebSession:
    """One Grocy web session, held in `http`'s cookie jar."""

    def __init__(
        self, base_url: str, http: httpx.AsyncClient, headers: dict[str, str] | None = None
    ):
        self._base = base_url
        self._http = http
        # Sent with every request. For a Grocy behind a single-sign-on proxy this is
        # the proxy's user header, which then stands in for the login (no cookie).
        self._headers = headers or {}

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        kwargs.setdefault("follow_redirects", False)
        if self._headers:
            kwargs["headers"] = {**self._headers, **kwargs.get("headers", {})}
        try:
            resp = await self._http.request(method, f"{self._base}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise GrocyUnreachable(f"Could not reach Grocy: {exc.__class__.__name__}") from exc
        if resp.status_code in GATEWAY_STATUSES:
            raise GrocyUnreachable(
                f"Could not reach Grocy: the server in front of it answered {resp.status_code}",
                resp.status_code,
            )
        return resp

    async def login(self, username: str, password: str) -> dict:
        """Returns Grocy's record of the signed-in user (id, username, display_name)."""
        form = {"username": username, "password": password}
        resp = await self._send("POST", "/login", data=form)
        if resp.status_code == 500:
            await self.load_start_page()
            resp = await self._send("POST", "/login", data=form)
        if resp.status_code >= 500:
            raise GrocyError(
                f"Grocy answered the sign-in with an error ({resp.status_code})", resp.status_code
            )
        if not resp.is_redirect:
            # Not Grocy's login form: sign-in is handled by a reverse proxy, or disabled.
            raise ApiKeyRequired("no login form at this address", signed_in=False)
        if "invalid=true" in resp.headers.get("location", ""):
            raise BadCredentials()
        data = await self.current_user()
        if data is None:
            raise ApiKeyRequired("the login didn't produce a session", signed_in=False)
        return data

    async def load_start_page(self) -> None:
        """A freshly installed Grocy creates its database on the first page load, and
        fails everything else until then."""
        await self._send("GET", "/", follow_redirects=True)

    async def current_user(self) -> dict | None:
        """Grocy's record of whoever this session is signed in as, or None if Grocy
        doesn't recognize it as signed in."""
        who = await self._send("GET", "/api/user", headers={"Accept": "application/json"})
        try:
            data = who.json() if who.status_code == 200 else None
        except ValueError:
            data = None
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or data.get("id") is None:
            return None
        return data

    async def mint_api_key(self) -> str:
        """Create a new API key for the signed-in user and return it."""
        created = await self._send(
            "GET", f"/manageapikeys/new?description={quote(KEY_DESCRIPTION)}"
        )
        key_id = re.search(r"[?&]key=(\d+)", created.headers.get("location", ""))
        if not created.is_redirect or key_id is None:
            raise ApiKeyRequired("Grocy didn't create an API key", signed_in=True)
        page = await self._send("GET", "/manageapikeys")
        key = find_api_key(page.text, key_id[1]) if page.status_code == 200 else None
        if key is None:
            raise ApiKeyRequired("the new API key couldn't be read back", signed_in=True)
        return key

    async def logout(self) -> None:
        """End the web session so nothing stays signed in on the app's behalf.
        Best effort: the cookie is discarded with the client either way."""
        try:
            await self._send("GET", "/logout")
        except GrocyError:
            pass
