"""Signing in from a single-sign-on proxy's user header (GA_TRUSTED_USER_HEADER), for
a Grocy that sits behind the same proxy and trusts that header itself."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from .conftest import SAM, sign_in

HEADER = "X-Proxy-User"
MINTED = "Grocy Assistant"
ME = "/api/auth/me"


@pytest.fixture
def proxied(client, grocy, monkeypatch):
    """The app and Grocy both behind a proxy that names the user in X-Proxy-User."""
    from app import config

    monkeypatch.setenv("GA_TRUSTED_USER_HEADER", HEADER)
    config.get_config.cache_clear()
    grocy.proxy_header = HEADER
    grocy.login_form = False
    return client


def as_user(username: str) -> dict:
    return {HEADER: username}


def device(client) -> TestClient:
    return TestClient(client.app)


def test_the_header_is_ignored_unless_configured(client, grocy):
    grocy.proxy_header = HEADER
    assert client.get(ME, headers=as_user("alex")).status_code == 401
    assert grocy.requests == []


def test_a_proxied_request_signs_in_without_a_sign_in_screen(proxied, grocy):
    r = proxied.get(ME, headers=as_user("alex"))
    assert r.status_code == 200, r.text
    me = {"id": 1, "username": "alex", "display_name": "Alex Doe", "is_admin": True}
    assert r.json() == me
    (minted,) = grocy.keys_of(1, MINTED)

    # The session cookie carries on from here; the header needn't be on every request.
    assert proxied.get(ME).json() == me
    assert proxied.post("/api/trips", json={}).status_code == 201

    # Another device signed in by the proxy reuses the key instead of minting one more.
    assert device(proxied).get(ME, headers=as_user("alex")).json() == me
    assert grocy.keys_of(1, MINTED) == [minted]
    assert grocy.count("GET", "/manageapikeys/new") == 1


def test_a_freshly_installed_grocy_is_woken_up_first(proxied, grocy):
    grocy.needs_first_page_load = True
    assert proxied.get(ME, headers=as_user("alex")).json()["username"] == "alex"
    assert grocy.count("GET", "/") == 1


def test_signed_in_requests_dont_ask_grocy_again(proxied, grocy):
    proxied.get(ME, headers=as_user("alex"))
    before = grocy.count("GET", "/api/user")
    for _ in range(3):
        assert proxied.get(ME, headers=as_user("alex")).status_code == 200
    assert grocy.count("GET", "/api/user") == before


def test_someone_grocy_has_never_seen_is_created_by_grocy(proxied, grocy):
    me = proxied.get(ME, headers=as_user("robin")).json()
    assert me["username"] == "robin" and me["is_admin"] is False
    (robin,) = [u for u in grocy.users.values() if u["username"] == "robin"]
    assert len(grocy.keys_of(robin["id"], MINTED)) == 1


def test_a_different_user_from_the_proxy_replaces_the_session(proxied, grocy):
    assert proxied.get(ME, headers=as_user("alex")).json()["username"] == "alex"
    assert proxied.get(ME, headers=as_user("sam")).json()["username"] == "sam"
    # Alex's session on this browser is over, not just hidden.
    assert proxied.get(ME).json()["username"] == "sam"
    from app.db import session_scope
    from app.models import AuthSession

    with session_scope() as db:
        assert [s.user.username for s in db.query(AuthSession)] == ["sam"]


def test_a_signed_out_account_is_signed_in_again_by_the_proxy(proxied, grocy):
    proxied.get(ME, headers=as_user("alex"))
    grocy.api_keys = [k for k in grocy.api_keys if k["description"] != MINTED]
    from app.services.accounts import check_active_keys

    asyncio.run(check_active_keys(proxied.app.state.http))
    assert proxied.get(ME).json()["code"] == "grocy_account_invalid"
    assert proxied.get(ME, headers=as_user("alex")).json()["username"] == "alex"
    assert len(grocy.keys_of(1, MINTED)) == 1


def test_grocy_not_trusting_the_header_falls_back_to_the_sign_in_screen(proxied, grocy):
    grocy.proxy_header = None
    r = proxied.get(ME, headers=as_user("alex"))
    assert r.status_code == 401 and "set-cookie" not in r.headers
    # A pasted key still works, and the header doesn't undo that sign-in.
    r = proxied.post("/api/auth/login", json={"api_key": "sams-own-key"})
    assert r.status_code == 200 and r.json()["username"] == "sam"
    assert proxied.get(ME, headers=as_user("alex")).json()["username"] == "sam"


def test_without_the_header_the_usual_sign_in_still_applies(proxied, grocy):
    grocy.login_form = True
    assert proxied.get(ME).status_code == 401
    assert sign_in(proxied, SAM)["username"] == "sam"
    assert proxied.get(ME).json()["username"] == "sam"


def test_grocy_being_down_is_reported_as_such(proxied, grocy):
    grocy.down = True
    r = proxied.get(ME, headers=as_user("alex"))
    assert r.status_code == 503 and r.json()["code"] == "grocy_unreachable"


def test_the_proxy_header_is_never_sent_alongside_an_api_key(proxied, grocy):
    proxied.get(ME, headers=as_user("alex"))
    proxied.post("/api/trips", json={})
    assert grocy.proxy_header_on_key_request == []
    assert grocy.cookie_on_key_request == []
