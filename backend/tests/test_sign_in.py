"""Signing in with a Grocy account, and staying in step with what Grocy says about
that account afterwards (who is an admin, whether the account still exists)."""

import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.grocy.login import find_api_key
from app.receipts.pipeline import parse_text

from .conftest import ALEX, GROCY, SAM, jpeg_bytes, sign_in
from .receipts import samples

BACKEND = Path(__file__).resolve().parents[1]
LOGIN = "/api/auth/login"
MINTED = "Grocy Assistant"  # the description the app gives the keys it creates


def stored_key(grocy_user_id: int) -> str | None:
    """The Grocy API key the app holds for that Grocy user, decrypted."""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import User
    from app.security import decrypt

    with session_scope() as db:
        user = db.scalar(select(User).where(User.grocy_user_id == grocy_user_id))
        return decrypt(user.grocy_api_key_enc) if user else None


def age_admin_check(by: timedelta) -> None:
    """Pretend every user's admin status was last checked `by` longer ago."""
    from app.db import session_scope
    from app.models import User, aware

    with session_scope() as db:
        for user in db.query(User):
            user.admin_checked_at = aware(user.admin_checked_at) - by


def second_device(client) -> TestClient:
    """Another browser talking to the same app: its own cookie jar."""
    return TestClient(client.app)


# --- signing in ------------------------------------------------------------------


def test_status_is_public_and_everything_else_needs_a_sign_in(client):
    from app import __version__

    assert client.get("/api/status").json() == {"version": __version__, "single_sign_on": False}
    assert client.get("/api/trips").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/settings").status_code == 401


def test_wrong_password_is_refused(client, grocy):
    r = client.post(LOGIN, json={"username": "alex", "password": "nope"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Wrong username or password"}
    assert client.get("/api/auth/me").status_code == 401
    assert stored_key(1) is None and grocy.keys_of(1, MINTED) == []


@pytest.mark.parametrize(
    "body",
    [{}, {"username": "alex"}, {"password": "correct horse"}, {"username": " ", "password": "x"}],
)
def test_sign_in_needs_a_username_and_password_or_a_key(client, grocy, body):
    r = client.post(LOGIN, json=body)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert grocy.requests == []  # nothing was sent to Grocy


def test_first_sign_in_creates_the_user_and_later_ones_reuse_its_key(client, grocy):
    me = sign_in(client)
    assert me == {"id": 1, "username": "alex", "display_name": "Alex Doe", "is_admin": True}
    minted = grocy.keys_of(1, MINTED)
    assert len(minted) == 1 and stored_key(1) == minted[0]
    assert grocy.sessions == {}  # the Grocy web session was ended again
    assert client.get("/api/auth/me").json() == {**me, "via_proxy": False}
    assert client.post("/api/trips", json={}).status_code == 201  # no setup step needed

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    # Signing in again (and from another device) finds the stored key still works.
    assert sign_in(client) == me
    assert sign_in(second_device(client)) == me
    assert grocy.keys_of(1, MINTED) == minted and stored_key(1) == minted[0]
    assert grocy.count("GET", "/manageapikeys/new") == 1
    assert grocy.sessions == {}


def test_the_users_own_key_is_picked_from_a_page_listing_everyones(client, grocy):
    # Alex is an admin, so Grocy's key page shows Sam's key and an older key of
    # Alex's before the one just created. Taking the first row would be Sam's.
    sign_in(client)
    (minted,) = grocy.keys_of(1, MINTED)
    assert stored_key(1) == minted
    assert stored_key(1) not in ("sams-own-key", "alex-old-key")

    grocy.add_product("Rice", "1111111111116")
    trip_id = client.post("/api/trips", json={}).json()["id"]
    client.post(f"/api/trips/{trip_id}/scan", json={"barcode": "1111111111116"})
    client.post(f"/api/trips/{trip_id}/submit")
    assert [b["booked_by"] for b in grocy.bookings] == ["alex"]


def test_find_api_key_matches_on_the_key_id():
    page = """
        <a class="x" data-apikey-id="17"
            data-apikey-key="first-on-the-page" data-apikey-description=""></a>
        <a data-apikey-description="Grocy Assistant"
            data-apikey-key="k&amp;7"
            data-apikey-id="7" title="Delete this item"></a>
        <a data-apikey-id="70" data-apikey-key="seventy"></a>
        <span data-apikey-id="8"></span>
    """
    assert find_api_key(page, "7") == "k&7"  # whatever the attribute order
    assert find_api_key(page, "70") == "seventy"
    assert find_api_key(page, "8") is None and find_api_key(page, "9") is None


def test_ordinary_grocy_users_sign_in_too_and_are_not_admins(client, grocy):
    me = sign_in(client, SAM)
    # No display name in Grocy: fall back to the username.
    assert me == {"id": 1, "username": "sam", "display_name": "sam", "is_admin": False}
    assert stored_key(2) == grocy.keys_of(2, MINTED)[0]
    assert sign_in(second_device(client), ALEX)["id"] == 2  # ids follow first sign-in


def test_name_changes_in_grocy_are_picked_up_at_the_next_sign_in(client, grocy):
    sign_in(client, SAM)
    grocy.users[2].update(username="samantha", display_name="Sam Smith")
    me = sign_in(client, {"username": "samantha", "password": "another pass"})
    assert me == {"id": 1, "username": "samantha", "display_name": "Sam Smith", "is_admin": False}
    assert len(grocy.keys_of(2, MINTED)) == 1


def test_a_revoked_key_is_replaced_at_the_next_sign_in(client, grocy):
    sign_in(client)
    (first,) = grocy.keys_of(1, MINTED)
    grocy.api_keys[:] = [k for k in grocy.api_keys if k["key"] != first]  # deleted in Grocy
    assert sign_in(client)["id"] == 1
    (second,) = grocy.keys_of(1, MINTED)
    assert second != first and stored_key(1) == second


def test_a_fresh_grocy_install_needs_its_start_page_loaded_once(client, grocy):
    grocy.needs_first_page_load = True
    assert sign_in(client)["username"] == "alex"
    assert grocy.count("POST", "/login") == 2 and grocy.count("GET", "/") == 1


def test_sign_in_with_just_an_api_key(client, grocy):
    r = client.post(LOGIN, json={"api_key": " sams-own-key "})
    assert r.status_code == 200
    assert r.json() == {"id": 1, "username": "sam", "display_name": "sam", "is_admin": False}
    assert stored_key(2) == "sams-own-key"
    # No password was involved, so no web login and no new key.
    assert grocy.count("POST", "/login") == 0 and grocy.keys_of(2, MINTED) == []
    assert client.post("/api/trips", json={}).status_code == 201


def test_a_rejected_api_key_is_a_401_and_leaves_the_current_session_alone(authed, grocy):
    r = authed.post(LOGIN, json={"api_key": "not-a-key"})
    assert r.status_code == 401 and r.json() == {"detail": "Grocy rejected that API key"}
    # A failed sign-in attempt is not "Alex's key stopped working".
    assert authed.get("/api/auth/me").json()["username"] == "alex"
    assert stored_key(1) is not None


def test_api_key_is_asked_for_when_one_cannot_be_minted(client, grocy):
    grocy.mint_broken = True  # e.g. a future Grocy moved the page
    r = client.post(LOGIN, json=ALEX)
    assert r.status_code == 409 and r.json()["code"] == "api_key_required"
    assert isinstance(r.json()["detail"], str)
    assert client.get("/api/auth/me").status_code == 401
    assert grocy.sessions == {}  # still signed out of Grocy's web UI afterwards

    # The wrong password is still just a wrong password.
    assert client.post(LOGIN, json={**ALEX, "password": "nope"}).status_code == 401

    # The PWA then shows the key field; the key alone (or with the rest) signs in.
    r = client.post(LOGIN, json={**ALEX, "api_key": "alex-old-key"})
    assert r.status_code == 200 and r.json()["is_admin"] is True
    assert stored_key(1) == "alex-old-key"
    # With a working key stored, password sign-in works again without minting.
    client.post("/api/auth/logout")
    assert sign_in(client)["username"] == "alex"


def test_api_key_is_asked_for_when_the_new_key_cannot_be_read_back(client, grocy, monkeypatch):
    monkeypatch.setattr("tests.conftest._keys_page", lambda rows: "<html>redesigned</html>")
    r = client.post(LOGIN, json=ALEX)
    assert r.status_code == 409 and r.json()["code"] == "api_key_required"
    assert stored_key(1) is None


def test_api_key_is_asked_for_when_grocy_has_no_login_form(client, grocy):
    grocy.login_form = False  # sign-in handled by a reverse proxy in front of Grocy
    r = client.post(LOGIN, json=ALEX)
    assert r.status_code == 409 and r.json()["code"] == "api_key_required"
    assert client.post(LOGIN, json={"api_key": "alex-old-key"}).status_code == 200


@pytest.mark.parametrize("outage", ["down", "gateway_down"])
@pytest.mark.parametrize("body", [ALEX, {"api_key": "alex-old-key"}])
def test_sign_in_while_grocy_is_unreachable(client, grocy, outage, body):
    setattr(grocy, outage, True)
    r = client.post(LOGIN, json=body)
    assert r.status_code == 503 and r.json()["code"] == "grocy_unreachable"
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/setup"),
        ("POST", "/api/auth/register"),
        ("PUT", "/api/auth/me"),
        ("PUT", "/api/settings"),
        ("POST", "/api/settings/ai/test"),
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("PATCH", "/api/users/1"),
        ("DELETE", "/api/users/1"),
    ],
)
def test_local_account_endpoints_are_gone(authed, method, path):
    assert authed.request(method, path, json={}).status_code in (404, 405)


# --- cookie isolation --------------------------------------------------------------


def test_grocy_session_cookies_never_reach_the_shared_http_client(client, grocy):
    sam = second_device(client)
    sign_in(client, ALEX)
    sign_in(sam, SAM)
    assert len(client.app.state.http.cookies.jar) == 0

    # And so each person's purchases are booked under their own Grocy account.
    grocy.add_product("Rice", "1111111111116")
    for who in (client, sam):
        trip_id = who.post("/api/trips", json={}).json()["id"]
        who.post(f"/api/trips/{trip_id}/scan", json={"barcode": "1111111111116"})
        assert who.post(f"/api/trips/{trip_id}/submit").json()["committed"] == 1
    assert [b["booked_by"] for b in grocy.bookings] == ["alex", "sam"]
    assert grocy.cookie_on_key_request == []
    assert len(client.app.state.http.cookies.jar) == 0


async def test_the_apps_own_shared_client_refuses_to_store_cookies():
    from app.grocy.client import shared_http_client

    def handler(request):
        return httpx.Response(200, headers={"Set-Cookie": "grocy_session=abc; path=/"}, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as plain:
        await plain.get(f"{GROCY}/api/user")
        assert len(plain.cookies.jar) == 1  # what any ordinary client does
    async with shared_http_client(5, transport=transport) as shared:
        await shared.get(f"{GROCY}/api/user")
        assert len(shared.cookies.jar) == 0


# --- admin follows Grocy -------------------------------------------------------------


def test_admin_status_is_rechecked_against_grocy_after_an_hour(client, grocy):
    sam = second_device(client)
    sign_in(client, ALEX)
    sign_in(sam, SAM)
    house_ai = {"provider": "openai", "base_url": "http://ollama:11434/v1"}
    assert client.put("/api/settings/ai/instance", json=house_ai).status_code == 200
    assert sam.put("/api/settings/ai/instance", json=house_ai).status_code == 403

    # Grocy swaps who the admin is. Within the hour the app doesn't ask again...
    grocy.users[1]["admin"], grocy.users[2]["admin"] = False, True
    checks = grocy.count("GET", "/api/users/1/permissions")
    assert client.get("/api/auth/me").json()["is_admin"] is True
    assert grocy.count("GET", "/api/users/1/permissions") == checks

    # ...after it, the next admin-sensitive request does.
    age_admin_check(timedelta(minutes=61))
    assert client.put("/api/settings/ai/instance", json=house_ai).status_code == 403
    assert client.get("/api/auth/me").json()["is_admin"] is False
    assert client.get("/api/settings").json()["instance_ai"] is None
    assert sam.get("/api/auth/me").json()["is_admin"] is True
    assert sam.put("/api/settings/ai/instance", json=house_ai).status_code == 200


def test_admin_recheck_keeps_the_last_known_answer_while_grocy_is_down(authed, grocy):
    age_admin_check(timedelta(hours=2))
    grocy.down = True
    assert authed.get("/api/auth/me").json()["is_admin"] is True
    assert authed.put("/api/settings/ai/instance", json={"mode": "always"}).status_code == 200
    assert grocy.refused == 1  # and it doesn't ask again on every request

    grocy.down = False
    grocy.users[1]["admin"] = False
    age_admin_check(timedelta(minutes=2))  # the retry is due a minute after the failure
    assert authed.get("/api/auth/me").json()["is_admin"] is False


# --- a Grocy 401 ends the app session ----------------------------------------------


INVALID = {
    "detail": "Your Grocy account is no longer valid. Sign in again.",
    "code": "grocy_account_invalid",
}


def test_deleting_the_grocy_user_signs_them_out_on_every_device(client, grocy):
    from app.grocy import client as grocy_client

    phone, laptop, alex = client, second_device(client), second_device(client)
    sign_in(phone, SAM)
    sign_in(laptop, SAM)
    sign_in(alex, ALEX)
    grocy.add_product("Rice", "1111111111116")
    trip_id = phone.post("/api/trips", json={}).json()["id"]
    item = phone.post(f"/api/trips/{trip_id}/scan", json={"barcode": "1111111111116"}).json()
    assert laptop.get(f"/api/trips/{trip_id}").status_code == 200

    del grocy.users[2]  # Sam's keys now get a 401 from Grocy
    grocy_client.reset_cache()

    # The request that discovers it had already changed the trip; that is undone.
    r = phone.delete(f"/api/trips/{trip_id}/items/{item['item']['id']}")
    assert r.status_code == 401 and r.json() == INVALID
    assert "ga_session" not in phone.cookies  # the response cleared the cookie
    assert stored_key(2) is None

    # The other device is signed out too, even on requests that never touch Grocy,
    # and is told why (every time, until someone signs in on it again).
    r = laptop.get("/api/trips")
    assert r.status_code == 401 and r.json() == INVALID
    assert laptop.get("/api/auth/me").json() == INVALID
    assert phone.post(LOGIN, json=SAM).status_code == 401  # and can't get back in

    # Nobody else is affected, and Sam's trip is still there for the household.
    trip = alex.get(f"/api/trips/{trip_id}").json()
    assert trip["created_by"] == "sam" and len(trip["items"]) == 1


def test_a_revoked_key_signs_out_and_signing_in_again_recovers(client, grocy):
    from app.grocy import client as grocy_client

    def revoke_minted_key():
        grocy.api_keys[:] = [k for k in grocy.api_keys if k["description"] != MINTED]
        grocy_client.reset_cache()

    me = sign_in(client, SAM)
    trip_id = client.post("/api/trips", json={}).json()["id"]

    revoke_minted_key()
    r = client.get("/api/grocy/meta")
    assert r.status_code == 401 and r.json() == INVALID
    assert client.get("/api/auth/me").status_code == 401

    assert sign_in(client, SAM) == me  # same app user, with a newly minted key
    revoke_minted_key()
    r = client.post("/api/settings/grocy/test")  # a dead key is a sign-out here too
    assert r.status_code == 401 and r.json() == INVALID

    assert sign_in(client, SAM) == me
    assert client.get(f"/api/trips/{trip_id}").json()["created_by"] == "sam"
    assert client.post("/api/settings/grocy/test").json() == {
        "ok": True,
        "message": "Connected to Grocy 4.7.1 as sam",
    }


def check_keys(client):
    """One round of the background check that main.py runs every few seconds."""
    from app.services.accounts import check_active_keys

    asyncio.run(check_active_keys(client.app.state.http))


def test_an_idle_user_is_signed_out_soon_after_their_grocy_account_is_deleted(client, grocy):
    """Nobody has to do anything that reaches Grocy: the periodic key check finds
    the dead key, and the page's own polling then learns of it."""
    phone, laptop, alex = client, second_device(client), second_device(client)
    sign_in(phone, SAM)
    sign_in(laptop, SAM)
    sign_in(alex, ALEX)
    trip_id = phone.post("/api/trips", json={}).json()["id"]

    check_keys(client)  # everyone's key is fine: nothing happens
    assert phone.get(f"/api/trips/{trip_id}/revision").status_code == 200

    del grocy.users[2]  # Sam is deleted in Grocy; nobody touches the app
    assert laptop.get(f"/api/trips/{trip_id}/revision").status_code == 200  # not known yet
    check_keys(client)

    for device in (phone, laptop):
        r = device.get(f"/api/trips/{trip_id}/revision")  # what an open trip page polls
        assert r.status_code == 401 and r.json() == INVALID
        assert device.get("/api/auth/me").json() == INVALID  # what every other page polls
    assert stored_key(2) is None
    assert alex.get("/api/auth/me").status_code == 200

    # A signed-out device can sign out or (were the account still there) sign in again.
    assert phone.post("/api/auth/logout").status_code == 204
    assert phone.get("/api/auth/me").json() == {"detail": "Not signed in"}


def test_the_key_check_only_asks_about_people_using_the_app(authed, grocy, monkeypatch):
    from app.services import accounts

    seen = []
    served = authed.app.state.http._transport.handler

    def watching(request):
        seen.append(request.url.path)
        return served(request)

    authed.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(watching))

    authed.get("/api/trips")
    check_keys(authed)
    assert seen == ["/grocy/api/user"]

    # A minute and a half after their last request they no longer count as active.
    seen.clear()
    monkeypatch.setattr(accounts, "ACTIVE_WITHIN_SECONDS", -1.0)
    check_keys(authed)
    assert seen == []


@pytest.mark.parametrize("outage", ["down", "gateway_down"])
def test_the_key_check_signs_nobody_out_while_grocy_is_down(authed, grocy, outage):
    setattr(grocy, outage, True)
    check_keys(authed)
    assert authed.get("/api/trips").status_code == 200
    assert stored_key(1) is not None


def test_a_dead_key_found_by_the_admin_recheck_signs_out_too(authed, grocy):
    grocy.api_keys.clear()
    age_admin_check(timedelta(hours=2))
    r = authed.get("/api/auth/me")
    assert r.status_code == 401 and r.json() == INVALID
    assert stored_key(1) is None


def test_background_receipt_read_survives_the_key_dying(authed, grocy, monkeypatch):
    from app.db import session_scope
    from app.grocy import client as grocy_client
    from app.models import AuthSession, Receipt

    grocy.add_product("Bananas")
    trip_id = authed.post("/api/trips", json={}).json()["id"]

    def read_while_the_key_is_revoked(paths):
        grocy.api_keys.clear()
        grocy_client.reset_cache()
        return parse_text(samples.WALMART)

    monkeypatch.setattr("app.services.receipts.parse_receipt_images", read_while_the_key_is_revoked)
    r = authed.post(
        f"/api/trips/{trip_id}/receipts", files=[("files", ("r.jpg", jpeg_bytes(), "image/jpeg"))]
    )
    assert r.status_code == 201
    for _ in range(100):
        with session_scope() as db:
            receipt = db.query(Receipt).one()
            status, lines = receipt.status, len(receipt.lines)
            sessions = db.query(AuthSession).count()
        if status != "processing":
            break
        time.sleep(0.05)
    # The receipt is kept (just unmatched), and nobody is signed out from a
    # background task; that happens on the user's next request.
    assert (status, lines, sessions) == ("ready", 6, 1)
    assert authed.get(f"/api/trips/{trip_id}").json() == INVALID


# --- startup -----------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "  "])
def test_app_refuses_to_start_without_a_grocy_url(tmp_path, value):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GA_")}
    env.update(GA_DATA_DIR=str(tmp_path / "data"), PYTHONPATH=str(BACKEND))
    if value is not None:
        env["GA_GROCY_URL"] = value
    # Run from an empty directory so no developer .env file can supply the value.
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    lines = proc.stderr.strip().splitlines()
    assert len(lines) == 1 and "GA_GROCY_URL" in lines[0], proc.stderr
    assert not (tmp_path / "data").exists()  # and it didn't touch the disk first


def test_the_grocy_address_is_not_sent_to_the_browser(authed):
    # It is server configuration, often an internal address, and nobody can change it.
    assert "grocy_url" not in authed.get("/api/settings").json()


@pytest.mark.parametrize(
    ("configured", "base"),
    [
        ("https://grocy.example.com/", "https://grocy.example.com"),
        ("https://example.com/grocy/api/", "https://example.com/grocy"),
        ("grocy.lan:9283", "http://grocy.lan:9283"),
    ],
)
def test_grocy_base_url_forms(configured, base):
    from app.config import Config

    assert Config(grocy_url=configured).grocy_base == base


def test_database_from_before_grocy_sign_in_is_moved_aside(tmp_path, monkeypatch, caplog):
    import shutil

    from app import config, db

    # An old-schema database as a crash would leave it: its newest rows are still
    # in the write-ahead log next to it.
    build = tmp_path / "build"
    build.mkdir()
    old = sqlite3.connect(build / "grocy-assistant.db")
    old.execute("PRAGMA journal_mode=WAL")
    old.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64),"
        " password_hash VARCHAR(255), is_admin BOOLEAN, grocy_api_key_enc TEXT,"
        " created_at DATETIME)"
    )
    old.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'alex', 'argon2')")
    old.commit()
    data = tmp_path / "data"
    shutil.copytree(build, data)
    old.close()
    assert (data / "grocy-assistant.db-wal").stat().st_size > 0

    monkeypatch.setenv("GA_DATA_DIR", str(data))
    monkeypatch.setenv("GA_GROCY_URL", GROCY)
    config.get_config.cache_clear()
    db.reset_engine()
    try:
        with caplog.at_level("WARNING"):
            db.init_db()
        backup = data / "grocy-assistant.db.pre-grocy-login.bak"
        kept = sqlite3.connect(backup)
        assert kept.execute("SELECT username, password_hash FROM users").fetchall() == [
            ("alex", "argon2")
        ]
        kept.close()
        fresh = sqlite3.connect(data / "grocy-assistant.db")
        columns = {row[1] for row in fresh.execute("PRAGMA table_info(users)")}
        assert "grocy_user_id" in columns and "password_hash" not in columns
        assert fresh.execute("SELECT count(*) FROM users").fetchone() == (0,)
        fresh.close()
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1 and str(backup) in warnings[0]

        # The fresh database is left alone on the next start.
        db.reset_engine()
        db.init_db()
        assert len(list(data.glob("*.bak"))) == 1
    finally:
        db.reset_engine()
        config.get_config.cache_clear()
