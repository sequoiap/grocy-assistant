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
            "stock_log": [],
        }
        self.bookings: list[dict] = []
        self.undone: list[str] = []
        self.off_products: dict[str, dict] = {}
        self.fail_add_for: set[int] = set()
        self.fail_add_after: dict[int, int] = {}  # product id -> bookings that succeed first
        self.fail_undo: set[str] = set()  # transaction ids whose undo answers 400
        self.stock: dict[int, float] = {}  # stock there before any booking: product -> amount
        self.fail_create: set[str] = set()  # object tables whose POST answers 400
        self.stock_actions: list[dict] = []  # consume and open calls, in order
        self.forbid_stock_changes = False  # consume and open answer 403
        # product -> its packages: {"stock_id", "amount", "open", "best_before_date"}.
        # Only for tests about one package; the amounts in `stock` still count in all.
        self.entries: dict[int, list[dict]] = {}
        self.entry_edits: list[dict] = []  # PUT /stock/entry bodies, in order

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
        # user. Behaves as Grocy 4.7.1 does: API keys still win on /api, a name it
        # hasn't seen becomes a new admin, and a request with neither a live key nor
        # the header is not a 401 but a 500.
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

    def _file_addition(self, pid: int, body: dict) -> str:
        """Files added stock into an entry, as Grocy 4.7.1 does: into an existing
        unopened entry whose details all match, else into a new one. Returns stock_id."""
        rows = self.entries.setdefault(pid, [])
        details = {
            "best_before_date": body.get("best_before_date"),
            "price": body.get("price"),
            "location_id": body.get("location_id"),
            "shopping_location_id": body.get("shopping_location_id"),
        }
        for e in rows:
            if not e.get("open") and all(e.get(k) == v for k, v in details.items()):
                e["amount"] += body["amount"]
                return e["stock_id"]
        n = sum(len(r) for r in self.entries.values()) + 1
        rows.append({"id": n, "stock_id": f"s{n}", "amount": body["amount"], "open": 0, **details})
        return f"s{n}"

    def _product(self, pid: int) -> dict | None:
        return next((p for p in self.tables["products"] if p["id"] == pid), None)

    def _live(self, rows: list[dict]) -> list[dict]:
        return [r for r in rows if r["transaction_id"] not in self.undone]

    def _amounts(self) -> dict[int, float]:
        amounts: dict[int, float] = dict(self.stock)
        for b in self._live(self.bookings):
            amounts[b["product_id"]] = amounts.get(b["product_id"], 0) + b["amount"]
        for a in self._live(self.stock_actions):
            if a["action"] == "consume":
                amounts[a["product_id"]] = amounts.get(a["product_id"], 0) - a["amount"]
        return amounts

    def _opened(self, pid: int) -> float:
        opened = sum(
            a["amount"]
            for a in self._live(self.stock_actions)
            if a["product_id"] == pid and a["action"] == "open"
        )
        return min(opened, max(self._amounts().get(pid, 0), 0))

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
        elif self.proxy_header and not (key_user and path.startswith("/api/")):
            error = f"ReverseProxyAuthMiddleware: {self.proxy_header} header is missing or invalid"
            return httpx.Response(500, json={"error_message": error, "error_details": {}})

        if path.startswith("/api/"):
            user = key_user or session_user
            if user is None:
                return httpx.Response(401, json={"error_message": "Unauthorized"})
            return self._api(request, path.removeprefix("/api"), user)
        return self._web(request, path, session_user, cookie.value if cookie else None)

    def _user_named(self, username: str) -> dict:
        user = next((u for u in self.users.values() if u["username"] == username), None)
        if user is None:
            user = self.users[self.add_user(username, "", admin=True)]
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
                rows = table
                for cond in request.url.params.get_list("query[]"):
                    key, _, value = cond.partition("=")
                    rows = [r for r in rows if str(r.get(key)) == value]
                return httpx.Response(200, json=rows)
            if m[1] in self.fail_create:
                return httpx.Response(400, json={"error_message": f"{m[1]} is broken"})
            row = {"id": len(table) + 1, "active": 1, **json.loads(request.content)}
            table.append(row)
            if m[1] == "quantity_unit_conversions":
                resolved = self.tables["quantity_unit_conversions_resolved"]
                for a, b, f in (
                    (row["from_qu_id"], row["to_qu_id"], row["factor"]),
                    (row["to_qu_id"], row["from_qu_id"], 1 / row["factor"]),
                ):
                    resolved.append(
                        {
                            "product_id": row["product_id"],
                            "from_qu_id": a,
                            "to_qu_id": b,
                            "factor": f,
                        }
                    )
            return httpx.Response(200, json={"created_object_id": str(row["id"])})
        if m := re.fullmatch(r"/objects/(\w+)/(\d+)", path):
            row = next((r for r in self.tables.get(m[1], []) if r["id"] == int(m[2])), None)
            if row is None:
                return httpx.Response(404, json={"error_message": "no such object"})
            if request.method == "PUT":
                row.update(json.loads(request.content))
                return httpx.Response(204)
            return httpx.Response(200, json=row)
        if m := re.fullmatch(r"/stock/products/(\d+)/add", path):
            pid = int(m[1])
            if pid in self.fail_add_for:
                return httpx.Response(400, json={"error_message": "Product is broken"})
            if pid in self.fail_add_after:
                if self.fail_add_after[pid] <= 0:
                    return httpx.Response(400, json={"error_message": "Out of room"})
                self.fail_add_after[pid] -= 1
            body = json.loads(request.content)
            tid = f"tx{len(self.bookings) + 1}"
            stock_id = self._file_addition(pid, body)
            self.bookings.append(
                {"product_id": pid, "transaction_id": tid, "booked_by": user["username"], **body}
            )
            log = self.tables["stock_log"]
            row = {
                "id": len(log) + 1,
                "product_id": pid,
                "transaction_id": tid,
                "transaction_type": body.get("transaction_type", "purchase"),
                "stock_id": stock_id,
                "amount": body["amount"],
                "undone": 0,
            }
            log.append(row)
            return httpx.Response(200, json=[row])
        if m := re.fullmatch(r"/stock/transactions/(\w+)/undo", path):
            if m[1] in self.fail_undo:
                return httpx.Response(400, json={"error_message": "Undo is broken"})
            self.undone.append(m[1])
            # Like Grocy 4.7.1: undoing an addition deletes every row of its stock entry,
            # including stock that an earlier addition with the same details put there.
            for row in self.tables["stock_log"]:
                if row["transaction_id"] == m[1] and not row["undone"]:
                    row["undone"] = 1
                    rows = self.entries.get(row["product_id"], [])
                    gone = sum(e["amount"] for e in rows if e["stock_id"] == row["stock_id"])
                    rows[:] = [e for e in rows if e["stock_id"] != row["stock_id"]]
                    extra = gone - row["amount"]  # what wasn't this transaction's
                    pid = row["product_id"]
                    self.stock[pid] = self.stock.get(pid, 0) - extra
            return httpx.Response(204)
        if m := re.fullmatch(r"/stock/entry/(\d+)", path):
            body = json.loads(request.content)
            for pid, rows in self.entries.items():
                for e in rows:
                    if e.get("id") == int(m[1]):
                        self.entry_edits.append({"id": e["id"], **body})
                        self.stock[pid] = self.stock.get(pid, 0) - (e["amount"] - body["amount"])
                        e["amount"] = body["amount"]
                        return httpx.Response(200, json=[{"transaction_id": "edit"}])
            return httpx.Response(400, json={"error_message": "Stock entry does not exist"})
        if path == "/stock":
            rows = [
                {
                    "product_id": pid,
                    "amount": a,
                    "amount_aggregated": a,
                    "amount_opened": self._opened(pid),
                    "amount_opened_aggregated": self._opened(pid),
                    "is_aggregated_amount": 0,
                    "best_before_date": "2999-12-31",
                    "product": self._product(pid),
                }
                for pid, a in self._amounts().items()
                if a > 0
            ]
            return httpx.Response(200, json=rows)
        if m := re.fullmatch(r"/stock/products/(\d+)", path):
            pid = int(m[1])
            product = self._product(pid)
            if product is None:
                return httpx.Response(400, json={"error_message": "Product does not exist"})
            amount = self._amounts().get(pid, 0)
            return httpx.Response(
                200,
                json={
                    "product": product,
                    "stock_amount": amount,
                    "stock_amount_opened": self._opened(pid),
                    "stock_amount_aggregated": amount,
                    "stock_amount_opened_aggregated": self._opened(pid),
                    "is_aggregated_amount": 0,
                    "next_due_date": "2026-12-01" if amount > 0 else None,
                },
            )
        if m := re.fullmatch(r"/stock/products/(\d+)/entries", path):
            rows = [e for e in self.entries.get(int(m[1]), []) if e["amount"] > 0]
            return httpx.Response(200, json=rows)
        if m := re.fullmatch(r"/stock/products/(\d+)/(consume|open)", path):
            pid, action = int(m[1]), m[2]
            if action == "open" and (self._product(pid) or {}).get("disable_open"):
                return httpx.Response(400, json={"error_message": "Product can't be opened"})
            if self.forbid_stock_changes:
                return httpx.Response(403, json={"error_message": "Permission denied"})
            body = json.loads(request.content)
            amount = self._amounts().get(pid, 0)
            limit = amount if action == "consume" else amount - self._opened(pid)
            package = [
                e for e in self.entries.get(pid, []) if e["stock_id"] == body.get("stock_entry_id")
            ]
            if body["amount"] > limit:
                verb = "consumed" if action == "consume" else "opened"
                error = f"Amount to be {verb} cannot be > current stock amount"
                return httpx.Response(400, json={"error_message": error})
            # Like Grocy 4.7: the amount was checked against the whole product above, and
            # with a package named, only that package is used, however much was asked for.
            left = body["amount"]
            for e in package:
                if action == "consume":
                    used = min(left, e["amount"])
                    e["amount"], left = e["amount"] - used, left - used
                elif not e["open"]:
                    e["open"], left = 1, left - e["amount"]
            tid = f"{action}{len(self.stock_actions) + 1}"
            self.stock_actions.append(
                {"product_id": pid, "action": action, "transaction_id": tid, **body}
            )
            return httpx.Response(200, json=[{"id": 1, "transaction_id": tid}])
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

    from app import config, db, deps, security
    from app.grocy import client as grocy_client
    from app.services import accounts

    config.get_config.cache_clear()
    db.reset_engine()
    security.reset_crypto_cache()
    grocy_client.reset_cache()
    accounts.reset_activity()
    deps.reset_warnings()

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
