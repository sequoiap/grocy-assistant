"""Signing in from a single-sign-on proxy's user header (GA_TRUSTED_USER_HEADER), for
a Grocy that sits behind the same proxy and trusts that header itself."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

HEADER = "X-Proxy-User"
MINTED = "Grocy Assistant"
ME = "/api/auth/me"
PROXY = "172.18.0.5"  # where the proxy connects from
ELSEWHERE = "192.168.1.50"  # a device that reaches the app without going through it


@pytest.fixture
def proxied(client, grocy, monkeypatch):
    """The app and Grocy both behind a proxy that names the user in X-Proxy-User.
    Requests made with this client arrive from the proxy."""
    from app import config

    monkeypatch.setenv("GA_TRUSTED_USER_HEADER", HEADER)
    monkeypatch.setenv("GA_TRUSTED_PROXIES", PROXY)
    config.get_config.cache_clear()
    grocy.proxy_header = HEADER
    grocy.login_form = False
    return device(client)


def as_user(username: str) -> dict:
    return {HEADER: username}


def device(client, connecting_from: str = PROXY) -> TestClient:
    """Another browser, with no cookies yet."""
    return TestClient(client.app, client=(connecting_from, 50000))


def test_the_header_is_ignored_unless_configured(client, grocy):
    grocy.proxy_header = HEADER
    assert device(client).get(ME, headers=as_user("alex")).status_code == 401
    assert grocy.requests == []


def test_the_header_is_only_believed_from_the_proxy(proxied, grocy, caplog):
    """Otherwise anyone who can reach the app's port signs in as whoever they name."""
    direct = device(proxied, ELSEWHERE)
    for _ in range(2):
        r = direct.get(ME, headers=as_user("alex"))
        assert r.status_code == 401 and "set-cookie" not in r.headers
    assert grocy.requests == []
    # Said once, so a setup with the wrong address in GA_TRUSTED_PROXIES can be fixed.
    (warning,) = [m for m in caplog.messages if "GA_TRUSTED_PROXIES" in m]
    assert ELSEWHERE in warning and HEADER in warning

    # Nor does it take over a session that device signed in to properly.
    r = direct.post("/api/auth/login", json={"api_key": "sams-own-key"})
    assert r.status_code == 200, r.text
    assert direct.get(ME, headers=as_user("alex")).json()["username"] == "sam"


@pytest.mark.parametrize(
    ("trusted", "address", "believed"),
    [
        ("172.18.0.0/16", "172.18.0.9", True),
        ("172.18.0.0/16", "172.19.0.9", False),
        ("10.0.0.1, 172.18.0.5", "172.18.0.5", True),
        ("10.0.0.1 fd00::/8", "fd12::5", True),
        ("172.18.0.5", "::ffff:172.18.0.5", True),  # IPv4 arriving on an IPv6 socket
        ("172.18.0.5", "testclient", False),  # not an address at all
    ],
)
def test_trusted_proxies_are_addresses_or_networks(
    proxied, monkeypatch, trusted, address, believed
):
    from app import config

    monkeypatch.setenv("GA_TRUSTED_PROXIES", trusted)
    config.get_config.cache_clear()
    r = device(proxied, address).get(ME, headers=as_user("alex"))
    assert r.status_code == (200 if believed else 401)


def test_a_header_the_proxy_added_instead_of_replacing_is_refused(proxied, grocy):
    """The first of the two is whatever the browser sent. Grocy refuses these too."""
    r = proxied.get(ME, headers=[(HEADER, "alex"), (HEADER, "sam")])
    assert r.status_code == 401
    assert grocy.requests == []


@pytest.mark.parametrize(
    ("proxies", "complaint"),
    [(None, "GA_TRUSTED_PROXIES is not"), ("the-proxy", "'the-proxy' is not an IP address")],
)
def test_the_app_wont_start_with_the_header_but_no_usable_proxy_address(
    client, monkeypatch, proxies, complaint
):
    from app import config

    monkeypatch.setenv("GA_TRUSTED_USER_HEADER", HEADER)
    if proxies is not None:
        monkeypatch.setenv("GA_TRUSTED_PROXIES", proxies)
    config.get_config.cache_clear()
    with pytest.raises(config.ConfigError, match=complaint):
        config.get_config()


def test_a_proxied_request_signs_in_without_a_sign_in_screen(proxied, grocy):
    r = proxied.get(ME, headers=as_user("alex"))
    assert r.status_code == 200, r.text
    me = {"id": 1, "username": "alex", "display_name": "Alex Doe", "is_admin": True}
    assert r.json() == {**me, "via_proxy": True}
    (minted,) = grocy.keys_of(1, MINTED)

    # The session cookie carries on from here; the header needn't be on every request.
    assert proxied.get(ME).json() == {**me, "via_proxy": False}
    assert proxied.post("/api/trips", json={}).status_code == 201

    # Another device signed in by the proxy reuses the key instead of minting one more.
    assert device(proxied).get(ME, headers=as_user("alex")).json()["username"] == "alex"
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
    # Grocy makes them an admin; the app reports what Grocy says.
    assert me["username"] == "robin" and me["is_admin"] is True
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


def test_a_revoked_key_is_replaced_at_the_next_sign_in(proxied, grocy):
    """In this mode Grocy answers a key it doesn't know with a 500, not a 401."""
    proxied.get(ME, headers=as_user("alex"))
    (old,) = grocy.keys_of(1, MINTED)
    grocy.api_keys = [k for k in grocy.api_keys if k["key"] != old]

    # A browser already signed in finds out with its next request that reaches Grocy...
    r = proxied.get("/api/grocy/meta", headers=as_user("alex"))
    assert r.status_code == 401 and r.json()["code"] == "grocy_account_invalid"
    # ...and is signed in again, with a new key, by the one after.
    assert proxied.get(ME, headers=as_user("alex")).json()["username"] == "alex"
    (new,) = grocy.keys_of(1, MINTED)
    assert new != old
    assert proxied.get("/api/grocy/meta", headers=as_user("alex")).status_code == 200


def test_a_new_device_gets_a_new_key_when_the_stored_one_was_revoked(proxied, grocy):
    proxied.get(ME, headers=as_user("alex"))
    grocy.api_keys = [k for k in grocy.api_keys if k["description"] != MINTED]
    assert device(proxied).get(ME, headers=as_user("alex")).json()["username"] == "alex"
    assert len(grocy.keys_of(1, MINTED)) == 1


def test_a_person_deleted_in_grocy_is_signed_out(proxied, grocy):
    """Until the proxy sends them again, that is: Grocy then recreates the account."""
    from app.services.accounts import check_active_keys

    robin = proxied.get(ME, headers=as_user("robin")).json()
    (uid,) = [u["id"] for u in grocy.users.values() if u["username"] == "robin"]
    del grocy.users[uid]
    grocy.api_keys = [k for k in grocy.api_keys if k["user_id"] != uid]

    asyncio.run(check_active_keys(proxied.app.state.http))
    r = proxied.get(ME)
    assert r.status_code == 401 and r.json()["code"] == "grocy_account_invalid"
    assert robin["username"] == "robin"


def test_requests_arriving_together_sign_in_once(proxied, grocy):
    """A page that opens with several requests at once, none with a cookie yet."""
    app = proxied.app

    async def unhurried(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)  # like a real Grocy, give the other requests a turn
        return grocy.handler(request)

    transport = httpx.MockTransport(unhurried)
    app.state.http = httpx.AsyncClient(transport=transport, follow_redirects=True)
    app.state.new_login_http = lambda: httpx.AsyncClient(transport=transport)

    async def together() -> list[httpx.Response]:
        from_proxy = httpx.ASGITransport(app=app, client=(PROXY, 50000))
        async with httpx.AsyncClient(transport=from_proxy, base_url="http://app") as browser:
            return await asyncio.gather(
                *(browser.get(ME, headers=as_user("robin")) for _ in range(8))
            )

    answers = asyncio.run(together())
    assert [r.status_code for r in answers] == [200] * 8, [r.text for r in answers]
    assert {r.json()["id"] for r in answers} == {answers[0].json()["id"]}
    (uid,) = [u["id"] for u in grocy.users.values() if u["username"] == "robin"]
    assert len(grocy.keys_of(uid, MINTED)) == 1


def test_grocy_not_trusting_the_header_falls_back_to_the_sign_in_screen(proxied, grocy):
    grocy.proxy_header = None
    r = proxied.get(ME, headers=as_user("alex"))
    assert r.status_code == 401 and "set-cookie" not in r.headers
    # A pasted key still works, and the header doesn't undo that sign-in.
    r = proxied.post("/api/auth/login", json={"api_key": "sams-own-key"})
    assert r.status_code == 200 and r.json()["username"] == "sam"
    assert proxied.get(ME, headers=as_user("alex")).json()["username"] == "sam"


def test_without_the_header_the_usual_sign_in_still_applies(proxied, grocy):
    """A path the proxy lets through unauthenticated, say. This Grocy has no login
    form, so the usual sign-in is a pasted API key."""
    assert proxied.get(ME).status_code == 401
    r = proxied.post("/api/auth/login", json={"api_key": "sams-own-key"})
    assert r.status_code == 200 and r.json()["username"] == "sam"
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


# --- what the page needs to know -------------------------------------------------


def test_the_page_is_told_whether_a_proxy_signs_people_in(client, monkeypatch):
    assert client.get("/api/status").json()["single_sign_on"] is False
    from app import config

    monkeypatch.setenv("GA_TRUSTED_USER_HEADER", HEADER)
    monkeypatch.setenv("GA_TRUSTED_PROXIES", PROXY)
    config.get_config.cache_clear()
    assert client.get("/api/status").json()["single_sign_on"] is True


def test_the_page_is_told_when_signing_out_would_be_undone(proxied, grocy):
    assert proxied.get(ME, headers=as_user("alex")).json()["via_proxy"] is True
    # The same browser on a request the proxy didn't name anyone on.
    assert proxied.get(ME).json()["via_proxy"] is False

    # Signed in with a pasted key instead, from a device that doesn't come through
    # the proxy: signing out means something there, whatever header it sends.
    direct = device(proxied, ELSEWHERE)
    direct.post("/api/auth/login", json={"api_key": "sams-own-key"})
    assert direct.get(ME, headers=as_user("sam")).json()["via_proxy"] is False


@pytest.mark.parametrize(
    ("asked_for", "sent_to"),
    [
        ("/trips/3/review", "/trips/3/review"),
        ("/login?next=%2Ftrips%2F3", "/login?next=%2Ftrips%2F3"),
        (None, "/"),
        ("https://elsewhere.example/", "/"),
        ("//elsewhere.example/", "/"),
        ("/\\elsewhere.example/", "/"),
        ("trips", "/"),
    ],
)
def test_the_page_load_through_the_proxy_only_leads_back_into_the_app(client, asked_for, sent_to):
    params = {} if asked_for is None else {"next": asked_for}
    r = client.get("/api/auth/through-proxy", params=params, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == sent_to
    assert r.headers["cache-control"] == "no-store"
