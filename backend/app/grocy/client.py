"""Thin async client for the parts of the Grocy REST API this app needs."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from ..config import get_config

log = logging.getLogger(__name__)

NEVER_DUE = "2999-12-31"  # Grocy's convention for "never overdue"
# After a failed master-data refresh, serve the snapshot without asking Grocy again
# for this long, so an outage doesn't put a connection attempt in front of every scan.
RETRY_AFTER_SECONDS = 10.0
# What a reverse proxy answers when the Grocy behind it is down.
GATEWAY_STATUSES = (502, 503, 504)
# A Grocy that signs people in from a proxy's header (ReverseProxyAuthMiddleware)
# has no 401 for an API key it doesn't know. It goes on to look for that header,
# which a key request never carries, and answers 500 with an error starting like this.
PROXY_AUTH_ERROR = "ReverseProxyAuthMiddleware:"


class GrocyError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


class GrocyUnreachable(GrocyError):
    """Grocy didn't answer: connection refused, DNS failure, timeout, or a proxy in
    front of it reporting that it is down. Nothing is wrong with the request."""


def grocy_timeout(seconds: float) -> httpx.Timeout:
    """Generous for slow answers, short for "is anything there at all": a Grocy
    that is switched off shouldn't hold every request for the full timeout."""
    return httpx.Timeout(seconds, connect=min(seconds, 5.0))


def shared_http_client(timeout: float, **kwargs) -> httpx.AsyncClient:
    """The long-lived client every API-key request goes through.

    It refuses to store cookies. An httpx client replays whatever cookies it has
    collected, and this one carries requests for every user, so a Grocy session
    cookie landing in it would attach one person's identity to another's calls.
    (The cookie-based sign-in runs on its own throwaway client; see grocy/login.py.)
    """
    no_cookies = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
    return httpx.AsyncClient(
        timeout=grocy_timeout(timeout),
        follow_redirects=True,
        cookies=no_cookies,
        **kwargs,
    )


def normalize_url(url: str) -> str:
    """Accepts 'grocy.lan', 'https://grocy.lan/', '.../api' and returns the API base."""
    url = url.strip().rstrip("/")
    if not url:
        raise GrocyError("Grocy URL is empty")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url + "/api"


@dataclass
class MasterData:
    """A snapshot of the Grocy master data needed to resolve and price items."""

    products: dict[int, dict] = field(default_factory=dict)
    barcodes: dict[str, dict] = field(default_factory=dict)  # normalized barcode -> row
    locations: list[dict] = field(default_factory=list)
    stores: list[dict] = field(default_factory=list)
    quantity_units: dict[int, dict] = field(default_factory=dict)
    product_groups: list[dict] = field(default_factory=list)
    # (product_id, from_qu_id, to_qu_id) -> factor
    conversions: dict[tuple[int, int, int], float] = field(default_factory=dict)
    presets: dict[str, Any] = field(default_factory=dict)
    # product_id -> amount in stock (stock unit), for products that have any.
    # None when this Grocy (or an older saved snapshot) didn't say.
    stock: dict[int, float] | None = None
    fetched_at: float = float("-inf")  # time.monotonic() of the fetch
    # False when this is an old snapshot served because Grocy couldn't be asked.
    reachable: bool = True

    def find_barcode(self, barcode: str) -> dict | None:
        return _find_in(self.barcodes, barcode)

    def qu_name(self, qu_id: int | None, amount: float = 1) -> str:
        qu = self.quantity_units.get(qu_id or -1)
        if not qu:
            return ""
        if amount != 1 and qu.get("name_plural"):
            return qu["name_plural"]
        return qu["name"]

    def conversion(self, product_id: int, from_qu: int | None, to_qu: int | None) -> float:
        if from_qu is None or to_qu is None or from_qu == to_qu:
            return 1.0
        return self.conversions.get((product_id, from_qu, to_qu), 1.0)


def barcode_variants(barcode: str) -> list[str]:
    """Equivalent spellings of a barcode: a UPC-A is an EAN-13 with a leading zero,
    and stores/scanners disagree about which one to emit. Small packages often carry
    a UPC-E, an 8-digit compressed UPC-A, so each form also matches the other."""
    out = _padded(barcode.strip())
    for code in list(out):
        if len(code) == 8:
            other = upc_e_to_a(code)
        elif len(code) == 12:
            other = upc_a_to_e(code)
        else:
            continue
        if other:
            out += [v for v in _padded(other) if v not in out]
    return out


def _padded(code: str) -> list[str]:
    out = [code]
    if code.isdigit():
        stripped = code.lstrip("0")
        for width in (8, 12, 13, 14):
            if len(stripped) <= width:
                padded = stripped.zfill(width)
                if padded not in out:
                    out.append(padded)
        if stripped and stripped not in out:
            out.append(stripped)
    return out


def _upc_check_digit(first11: str) -> str:
    odd = sum(int(d) for d in first11[0::2])
    even = sum(int(d) for d in first11[1::2])
    return str((10 - (odd * 3 + even) % 10) % 10)


def upc_e_to_a(code: str) -> str | None:
    """The UPC-A an 8-digit UPC-E stands for, or None if `code` isn't a valid UPC-E.
    The check digit is required to match, so an EAN-8 is never mistaken for one."""
    if len(code) != 8 or not code.isdigit() or code[0] not in "01":
        return None
    ns, d, check = code[0], code[1:7], code[7]
    last = d[5]
    if last in "012":
        body = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + last
    first11 = ns + body
    if _upc_check_digit(first11) != check:
        return None
    return first11 + check


def upc_a_to_e(code: str) -> str | None:
    """The 8-digit UPC-E for a UPC-A, or None when that UPC-A has no short form."""
    if len(code) != 12 or not code.isdigit() or code[0] not in "01":
        return None
    if _upc_check_digit(code[:11]) != code[11]:
        return None
    m, p = code[1:6], code[6:11]
    if m[3:5] == "00" and m[2] in "012" and p[:2] == "00":
        d = m[0:2] + p[2:5] + m[2]
    elif m[3:5] == "00" and p[:3] == "000":
        d = m[0:3] + p[3:5] + "3"
    elif m[4] == "0" and p[:4] == "0000":
        d = m[0:4] + p[4] + "4"
    elif p[:4] == "0000" and p[4] in "56789":
        d = m + p[4]
    else:
        return None
    short = code[0] + d + code[11]
    return short if upc_e_to_a(short) == code else None


def _barcode_table(rows: list[dict]) -> dict[str, dict]:
    return {str(b["barcode"]).strip(): b for b in rows if b.get("barcode")}


def _find_in(table: dict[str, dict], barcode: str) -> dict | None:
    for candidate in barcode_variants(barcode):
        row = table.get(candidate)
        if row:
            return row
    return None


_cache: dict[str, MasterData] = {}  # API base -> last good snapshot
_retry_at: dict[str, float] = {}  # API base -> time.monotonic() before which not to refresh
_saved: dict[str, str] = {}  # API base -> the JSON last written to disk


def invalidate_cache(base_url: str) -> None:
    """Make the next master_data() call refresh. The snapshot itself is kept: it is
    still the best answer available if that refresh can't reach Grocy."""
    cached = _cache.get(base_url)
    if cached is not None:
        cached.fetched_at = float("-inf")


def _note_outage(base_url: str) -> None:
    """A request just found Grocy unreachable. The snapshot in memory may be only
    seconds old and still say "reachable"; mark it, so the very next trip or meta
    response tells the person why their action didn't go through, and hold off
    refreshing for the usual back-off."""
    _retry_at[base_url] = time.monotonic() + RETRY_AFTER_SECONDS
    cached = _cache.get(base_url)
    if cached is not None:
        cached.reachable = False
        cached.fetched_at = float("-inf")  # refresh as soon as the back-off is over


def reset_cache() -> None:
    """Forget everything held in memory, as a process restart would."""
    _cache.clear()
    _retry_at.clear()
    _saved.clear()


def _active(rows: list[dict]) -> list[dict]:
    return [r for r in rows if int(r.get("active", 1) or 0) == 1]


def _stock_table(rows: list[dict] | None) -> dict[int, float] | None:
    if rows is None:
        return None
    out: dict[int, float] = {}
    for row in rows:
        try:
            out[int(row["product_id"])] = float(row.get("amount") or 0)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _build_master_data(raw: dict[str, Any]) -> MasterData:
    """`raw` is what Grocy returned, keyed by entity. It is also what gets written
    to disk, so a restored snapshot goes through exactly this same code."""
    settings = raw.get("user_settings") or {}
    return MasterData(
        stock=_stock_table(raw.get("stock")),
        products={int(p["id"]): p for p in raw["products"]},
        barcodes=_barcode_table(raw["product_barcodes"]),
        locations=_active(raw["locations"]),
        stores=_active(raw["shopping_locations"]),
        quantity_units={int(u["id"]): u for u in raw["quantity_units"]},
        product_groups=_active(raw["product_groups"]),
        conversions={
            (int(c["product_id"]), int(c["from_qu_id"]), int(c["to_qu_id"])): float(c["factor"])
            for c in raw["quantity_unit_conversions_resolved"]
            if c.get("product_id") is not None
        },
        presets={
            k: settings.get(k)
            for k in (
                "product_presets_location_id",
                "product_presets_qu_id",
                "product_presets_product_group_id",
                "product_presets_default_due_days",
            )
        },
    )


def _save_snapshot(base_url: str, raw: dict[str, Any]) -> None:
    """Keep the last good master data on disk so an outage that outlasts an app
    restart can still be bridged. Skipped when nothing changed since the last write."""
    body = json.dumps(raw, sort_keys=True)
    if _saved.get(base_url) == body:
        return
    path = get_config().snapshot_path
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps({"base_url": base_url, "raw": raw}))
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("Couldn't save the Grocy master data snapshot: %s", exc)
        return
    _saved[base_url] = body


def _load_snapshot(base_url: str) -> MasterData | None:
    try:
        saved = json.loads(get_config().snapshot_path.read_text())
        if saved["base_url"] != base_url:
            return None  # GA_GROCY_URL now points at a different Grocy
        md = _build_master_data(saved["raw"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    md.reachable = False
    return md


class GrocyClient:
    def __init__(self, base_url: str, api_key: str, http: httpx.AsyncClient):
        self.base_url = normalize_url(base_url)
        self._api_key = api_key
        self._http = http

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = await self._http.request(
                method,
                f"{self.base_url}{path}",
                headers={"GROCY-API-KEY": self._api_key, "Accept": "application/json"},
                **kwargs,
            )
        except httpx.HTTPError as exc:
            _note_outage(self.base_url)
            raise GrocyUnreachable(
                f"Could not reach Grocy: {exc.__class__.__name__}: {exc}"
            ) from exc
        if resp.status_code == 401:
            raise GrocyError("Grocy rejected the API key", 401)
        if resp.status_code in GATEWAY_STATUSES:
            _note_outage(self.base_url)
            raise GrocyUnreachable(
                f"Could not reach Grocy: the server in front of it answered {resp.status_code}",
                resp.status_code,
            )
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error_message") or resp.text
            except Exception:
                detail = resp.text[:300]
            if resp.status_code == 500 and PROXY_AUTH_ERROR in str(detail):
                raise GrocyError("Grocy rejected the API key", 401)
            raise GrocyError(f"Grocy error ({resp.status_code}): {detail}", resp.status_code)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise GrocyError(
                "Grocy returned something that isn't JSON - is the URL correct?", resp.status_code
            ) from exc

    # --- basic info -----------------------------------------------------

    async def system_info(self) -> dict:
        return await self._request("GET", "/system/info")

    async def current_user(self) -> dict:
        data = await self._request("GET", "/user")
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    async def is_admin(self, grocy_user_id: int) -> bool:
        """Whether that user holds Grocy's ADMIN permission. Reading anyone's
        permissions is itself admin-only, so the answer is in the status code."""
        try:
            await self._request("GET", f"/users/{grocy_user_id}/permissions")
        except GrocyError as exc:
            if exc.status == 403:
                return False
            raise
        return True

    async def user_settings(self) -> dict:
        return await self._request("GET", "/user/settings") or {}

    # --- generic objects ------------------------------------------------

    async def objects(self, entity: str) -> list[dict]:
        return await self._request("GET", f"/objects/{entity}") or []

    async def create_object(self, entity: str, data: dict) -> int:
        result = await self._request("POST", f"/objects/{entity}", json=data)
        invalidate_cache(self.base_url)
        return int(result["created_object_id"])

    async def update_object(self, entity: str, object_id: int, data: dict) -> None:
        await self._request("PUT", f"/objects/{entity}/{object_id}", json=data)
        invalidate_cache(self.base_url)

    # --- stock ----------------------------------------------------------

    async def add_stock(
        self,
        product_id: int,
        *,
        amount: float,
        best_before_date: str,
        price: float | None = None,
        location_id: int | None = None,
        shopping_location_id: int | None = None,
        note: str | None = None,
        transaction_type: str = "purchase",
    ) -> list[dict]:
        """Adds a stock entry. `transaction_type` is "purchase" for shopping, or
        "inventory-correction" for stock that was already there (what Grocy's own
        Inventory page books when the counted amount is higher)."""
        body: dict[str, Any] = {
            "amount": amount,
            "best_before_date": best_before_date,
            "transaction_type": transaction_type,
        }
        if price is not None:
            body["price"] = price
        if location_id is not None:
            body["location_id"] = location_id
        if shopping_location_id is not None:
            body["shopping_location_id"] = shopping_location_id
        if note:
            body["note"] = note
        return await self._request("POST", f"/stock/products/{product_id}/add", json=body) or []

    async def undo_transaction(self, transaction_id: str) -> None:
        await self._request("POST", f"/stock/transactions/{transaction_id}/undo")

    # --- master data snapshot -------------------------------------------

    async def find_barcode_live(self, barcode: str) -> dict | None:
        """Ask Grocy itself whether a product has this barcode (in any spelling), for
        when the snapshot doesn't know it. Reads only the barcode table, so a scan of
        something new costs one request instead of a full master-data refresh.

        None when no product has it, and also when Grocy can't be asked right now:
        an unknown barcode during an outage is handled as new, as the snapshot would."""
        if time.monotonic() < _retry_at.get(self.base_url, 0.0):
            return None
        try:
            rows = await self.objects("product_barcodes")
        except GrocyError as exc:
            if isinstance(exc, GrocyUnreachable):
                return None  # _request already started the back-off
            if (exc.status or 0) >= 500:
                _note_outage(self.base_url)
                return None
            raise
        return _find_in(_barcode_table(rows), barcode)

    async def master_data(self, max_age: float = 30.0, force: bool = False) -> MasterData:
        """The current snapshot, refreshed when older than `max_age` (or `force`).

        If Grocy can't be asked, the last good snapshot is returned instead, marked
        ``reachable=False``; reading and scanning keep working through an outage.
        Raises only when there is no snapshot at all, or when Grocy rejects the key
        (a 401 is not an outage; it means this user has to sign in again)."""
        cached = _cache.get(self.base_url)
        now = time.monotonic()
        if now < _retry_at.get(self.base_url, 0.0):
            if cached is not None:
                return cached  # a refresh failed moments ago; don't ask again yet
        elif cached is not None and not force and now - cached.fetched_at < max_age:
            return cached

        try:
            raw = await self._fetch_master_data()
        except GrocyError as exc:
            outage = isinstance(exc, GrocyUnreachable) or (exc.status or 0) >= 500
            if not outage:
                raise
            _retry_at[self.base_url] = time.monotonic() + RETRY_AFTER_SECONDS
            stale = cached or _load_snapshot(self.base_url)
            if stale is None:
                raise
            log.warning("Serving the last good Grocy snapshot: %s", exc.message)
            stale.reachable = False
            _cache[self.base_url] = stale
            return stale

        md = _build_master_data(raw)
        md.fetched_at = time.monotonic()
        _cache[self.base_url] = md
        _retry_at.pop(self.base_url, None)
        _save_snapshot(self.base_url, raw)
        return md

    async def _fetch_master_data(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for entity in (
            "products",
            "product_barcodes",
            "locations",
            "shopping_locations",
            "quantity_units",
            "product_groups",
        ):
            raw[entity] = await self.objects(entity)
        try:
            raw["quantity_unit_conversions_resolved"] = await self.objects(
                "quantity_unit_conversions_resolved"
            )
        except GrocyError as exc:
            if not _missing_feature(exc):
                raise
            raw["quantity_unit_conversions_resolved"] = []  # Grocy < 4.0 has no such view
        try:
            raw["user_settings"] = await self.user_settings()
        except GrocyError as exc:
            if not _missing_feature(exc):
                raise
            raw["user_settings"] = {}
        try:
            # What's in stock, per product: shown when counting an inventory.
            raw["stock"] = await self._request("GET", "/stock") or []
        except GrocyError as exc:
            if not _missing_feature(exc):
                raise
            raw["stock"] = None
        return raw


def _missing_feature(exc: GrocyError) -> bool:
    """A 4xx on an optional endpoint means "this Grocy doesn't have it"; an outage
    or a rejected key part-way through a refresh must not be mistaken for that."""
    return (
        not isinstance(exc, GrocyUnreachable)
        and exc.status is not None
        and exc.status != 401
        and 400 <= exc.status < 500
    )
