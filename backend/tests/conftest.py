"""Shared fixtures: an app instance on a throwaway data dir, talking to a fake Grocy."""

import io
import json
import re
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

# Grocy served under a sub-path, the harder case for building its URLs.
PREFIX = "/grocy"
GROCY = f"http://grocy.test{PREFIX}"
# Real Grocy (4.7.1) calls its web session cookie this.
GROCY_COOKIE = "grocy_session_access_token"

ALEX = {"username": "alex", "password": "correct horse"}  # Grocy admin
SAM = {"username": "sam", "password": "another pass"}  # ordinary Grocy user


class FakeGrocy:
    """Just enough of Grocy, in memory, to sign in to and book a shopping trip:
    the REST API plus the few web-UI pages the sign-in flow drives."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "products": [],
            "product_barcodes": [],
            "locations": [{"id": 1, "name": "Pantry", "active": 1}],
            "shopping_locations": [{"id": 1, "name": "Walmart", "active": 1}],
            "quantity_units": [
                {"id": 1, "name": "Piece", "name_plural": "Pieces", "active": 1},
                {"id": 2, "name": "Pack", "name_plural": "Packs", "active": 1},
            ],
            "product_groups": [],
            "quantity_unit_conversions_resolved": [],
        }
        self.bookings: list[dict] = []
        self.undone: list[str] = []
        self.off_products: dict[str, dict] = {}
        self.fail_add_for: set[int] = set()

        self.users: dict[int, dict] = {}
        self.api_keys: list[dict] = []
        self.sessions: dict[str, int] = {}  # live web sessions: cookie value -> user id
        self.add_user("alex", "correct horse", admin=True, display_name="Alex Doe")
        self.add_user("sam", "another pass", display_name=None)
        # Keys that exist before the app ever signs anyone in. An admin's key page
        # lists all of them, and they come before whatever gets minted later.
        self.add_key(2, "sams-own-key", "phone")
        self.add_key(1, "alex-old-key", "")

        self.down = False  # nothing answers: connection refused
        self.refused = 0  # how many connection attempts were turned away while down
        self.gateway_down = False  # a reverse proxy answers 502 for a dead Grocy
        self.needs_first_page_load = False  # fresh install: login 500s until / is loaded
        self.login_form = True  # False: sign-in is handled by something in front of Grocy
        self.mint_broken = False  # the "new API key" UI route is gone
        # Set: Grocy runs ReverseProxyAuthMiddleware and trusts this header to name the
        # user, creating unknown ones, as Grocy 4.7.1 does (API keys still win on /api).
        self.proxy_header: str | None = None
        self.proxy_header_on_key_request: list[str] = []  # API-key requests that carried it
        self.requests: list[tuple[str, str]] = []  # (method, path) of everything served
        self.cookie_on_key_request: list[str] = []  # API-key requests that carried a cookie

    # --- test setup helpers ---------------------------------------------------

    def add_user(self, username, password, admin=False, display_name=None) -> int:
        uid = max(self.users, default=0) + 1
        self.users[uid] = {
            "id": uid,
            "username": username,
            "display_name": display_name,
            "password": password,
            "admin": admin,
        }
        return uid

    def add_key(self, user_id: int, key: str | None = None, description: str = "") -> dict:
        row = {
            "id": max((k["id"] for k in self.api_keys), default=0) + 1,
            "user_id": user_id,
            "key": key or secrets.token_hex(24),
            "description": description,
        }
        self.api_keys.append(row)
        return row

    def keys_of(self, user_id: int, description: str | None = None) -> list[str]:
        return [
            k["key"]
            for k in self.api_keys
            if k["user_id"] == user_id and description in (None, k["description"])
        ]

    def count(self, method: str, path: str) -> int:
        return self.requests.count((method, path))

    def add_product(self, name: str, barcode: str | None = None, **fields) -> int:
        pid = len(self.tables["products"]) + 1
        self.tables["products"].append(
            {
                "id": pid,
                "name": name,
                "active": 1,
                "location_id": 1,
                "qu_id_stock": 1,
                "qu_id_purchase": 1,
                "default_best_before_days": 0,
                **fields,
            }
        )
        if barcode:
            self.tables["product_barcodes"].append(
                {
                    "id": len(self.tables["product_barcodes"]) + 1,
                    "product_id": pid,
                    "barcode": barcode,
                    "amount": None,
                    "qu_id": None,
                }
            )
        return pid

    # --- the server -------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        if "facts.org" in request.url.host:
            code = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
            product = self.off_products.get(code)
            if product and request.url.host == "world.openfoodfacts.org":
                return httpx.Response(200, json={"status": 1, "product": product})
            return httpx.Response(200, json={"status": 0})
        if self.down:
            self.refused += 1
            raise httpx.ConnectError("Connection refused", request=request)
        if self.gateway_down:
            return httpx.Response(502, text="<html>Bad Gateway</html>")
        if not request.url.path.startswith(PREFIX + "/"):
            return httpx.Response(404, text="not Grocy")
        path = request.url.path.removeprefix(PREFIX)
        self.requests.append((request.method, path))

        cookie = SimpleCookie(request.headers.get("cookie", "")).get(GROCY_COOKIE)
        session_user = self.users.get(self.sessions.get(cookie.value if cookie else "", -1))
        api_key = request.headers.get("GROCY-API-KEY")
        if api_key is not None and "cookie" in request.headers:
            self.cookie_on_key_request.append(path)
        key_row = next((k for k in self.api_keys if k["key"] == api_key), None)
        key_user = self.users.get(key_row["user_id"]) if key_row else None
        proxied = request.headers.get(self.proxy_header) if self.proxy_header else None
        if api_key is not None and proxied is not None:
            self.proxy_header_on_key_request.append(path)
        if self.needs_first_page_load and proxied and path != "/":
            return httpx.Response(500, text="<html>no such table: users</html>")
        if proxied:
            session_user = self._user_named(proxied)

        if path.startswith("/api/"):
            user = key_user or session_user
            if user is None:
                return httpx.Response(401, json={"error_message": "Unauthorized"})
            return self._api(request, path.removeprefix("/api"), user)
        return self._web(request, path, session_user, cookie.value if cookie else None)

    def _user_named(self, username: str) -> dict:
        user = next((u for u in self.users.values() if u["username"] == username), None)
        if user is None:
            user = self.users[self.add_user(username, "")]
        return user

    def _redirect(self, to: str, **headers) -> httpx.Response:
        return httpx.Response(302, headers={"Location": f"{GROCY}{to}", **headers})

    def _web(self, request, path, user, cookie_value) -> httpx.Response:
        if path == "/login" and request.method == "POST":
            if not self.login_form:
                return httpx.Response(200, text="<html>Single sign-on</html>")
            if self.needs_first_page_load:
                return httpx.Response(500, text="<html>no such table: sessions</html>")
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            match = next(
                (
                    u
                    for u in self.users.values()
                    if u["username"] == form.get("username")
                    and u["password"] == form.get("password")
                ),
                None,
            )
            if match is None:
                return self._redirect("/login?invalid=true")
            token = secrets.token_hex(32)
            self.sessions[token] = match["id"]
            cookie = f"{GROCY_COOKIE}={token}; path=/; HttpOnly; SameSite=Lax"
            return self._redirect("/", **{"Set-Cookie": cookie})
        if path == "/login":
            return httpx.Response(200, text="<html><form>login</form></html>")
        if path == "/":
            self.needs_first_page_load = False
        if user is None:
            return self._redirect("/login")
        if path == "/":
            return httpx.Response(200, text="<html>Stock overview</html>")
        if path == "/logout":
            self.sessions.pop(cookie_value, None)
            return self._redirect("/")
        if path == "/manageapikeys/new" and not self.mint_broken:
            row = self.add_key(user["id"], description=request.url.params.get("description", ""))
            return self._redirect(f"/manageapikeys?key={row['id']}")
        if path == "/manageapikeys":
            # Admins are shown everybody's keys; everyone else only their own.
            rows = [k for k in self.api_keys if user["admin"] or k["user_id"] == user["id"]]
            return httpx.Response(200, text=_keys_page(rows))
        return httpx.Response(404, text="<html>Page not found</html>")

    def _api(self, request, path, user) -> httpx.Response:
        if path == "/system/info":
            return httpx.Response(200, json={"grocy_version": {"Version": "4.7.1"}})
        if path == "/user":
            public = {k: user[k] for k in ("id", "username", "display_name")}
            return httpx.Response(200, json=[public])
        if path == "/user/settings":
            return httpx.Response(200, json={})
        if re.fullmatch(r"/users/\d+/permissions", path):
            if not user["admin"]:
                return httpx.Response(403, json={"error_message": "Permission missing: ADMIN"})
            return httpx.Response(200, json=[{"permission_id": 1}])
        if m := re.fullmatch(r"/objects/(\w+)", path):
            table = self.tables.setdefault(m[1], [])
            if request.method == "GET":
                return httpx.Response(200, json=table)
            row = {"id": len(table) + 1, "active": 1, **json.loads(request.content)}
            table.append(row)
            return httpx.Response(200, json={"created_object_id": str(row["id"])})
        if m := re.fullmatch(r"/stock/products/(\d+)/add", path):
            pid = int(m[1])
            if pid in self.fail_add_for:
                return httpx.Response(400, json={"error_message": "Product is broken"})
            body = json.loads(request.content)
            tid = f"tx{len(self.bookings) + 1}"
            self.bookings.append(
                {"product_id": pid, "transaction_id": tid, "booked_by": user["username"], **body}
            )
            return httpx.Response(200, json=[{"transaction_id": tid}])
        if m := re.fullmatch(r"/stock/transactions/(\w+)/undo", path):
            self.undone.append(m[1])
            return httpx.Response(204)
        return httpx.Response(404, json={"error_message": f"no route {path}"})


def _keys_page(rows: list[dict]) -> str:
    """The key table as Grocy 4.7.1 renders it (attributes on separate lines)."""
    body = "".join(
        f"""
            <tr class="">
                <td class="fit-content border-right">
                    <a class="btn btn-danger btn-sm apikey-delete-button"
                        href="#"
                        data-apikey-id="{k["id"]}"
                        data-apikey-key="{k["key"]}"
                        data-apikey-description="{k["description"]}"
                        data-toggle="tooltip"
                        title="Delete this item">
                        <i class="fa-solid fa-trash"></i>
                    </a>
                    <a class="btn btn-info btn-sm apikey-show-qr-button"
                        href="#"
                        data-apikey-key="{k["key"]}"
                        data-apikey-type="default"
                        data-apikey-description="{k["description"]}"
                        data-toggle="tooltip"
                        title="Show a QR-Code for this API key">
                        <i class="fa-solid fa-qrcode"></i>
                    </a>
                </td>
                <td>{k["key"]}</td>
            </tr>"""
        for k in rows
    )
    return f'<html><body><table><tbody class="d-none">{body}</tbody></table></body></html>'


@pytest.fixture
def grocy():
    return FakeGrocy()


@pytest.fixture
def client(tmp_path, monkeypatch, grocy):
    monkeypatch.setenv("GA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GA_STATIC_DIR", str(tmp_path / "no-static"))
    monkeypatch.setenv("GA_GROCY_URL", GROCY)
    monkeypatch.delenv("GA_SECRET_KEY", raising=False)
    # The background key check would add Grocy requests at unpredictable moments;
    # the tests call check_active_keys themselves.
    monkeypatch.setenv("GA_KEY_CHECK_SECONDS", "0")

    from app import config, db, security
    from app.grocy import client as grocy_client
    from app.services import accounts

    config.get_config.cache_clear()
    db.reset_engine()
    security.reset_crypto_cache()
    grocy_client.reset_cache()
    accounts.reset_activity()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        # Deliberately a plain httpx client, not the cookie-refusing one the app builds
        # for itself: if the sign-in flow ever ran on the shared client, this one would
        # keep the Grocy session cookie and the tests watching for that would see it.
        app.state.http = httpx.AsyncClient(
            transport=httpx.MockTransport(grocy.handler), follow_redirects=True
        )
        app.state.new_login_http = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(grocy.handler)
        )
        yield c
    db.reset_engine()
    config.get_config.cache_clear()


def sign_in(client, who=ALEX):
    r = client.post("/api/auth/login", json=who)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def authed(client):
    """A client signed in as Alex, the household's Grocy admin."""
    sign_in(client)
    return client


def jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 120), "white").save(buf, "JPEG")
    return buf.getvalue()
