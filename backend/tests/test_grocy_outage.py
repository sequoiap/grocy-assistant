"""While Grocy is down: scanning, viewing and receipt matching carry on from the
last good snapshot of its master data; things that need Grocy say so and change
nothing."""

import json

import httpx
import pytest

from app.grocy import client as grocy_client
from app.receipts.pipeline import parse_text

from .conftest import GROCY, jpeg_bytes
from .receipts import samples
from .test_api_flow import EGGS, MILK, stock_walmart_products, wait_until_read

API = f"{GROCY}/api"
UNREACHABLE = {
    "detail": "Grocy is unreachable right now. Your trip is saved; try again in a moment.",
    "code": "grocy_unreachable",
}


def cache_expires():
    """The in-memory copy is now older than GA_GROCY_CACHE_SECONDS."""
    grocy_client.invalidate_cache(API)


def backoff_passes():
    """The few seconds after a failed refresh during which Grocy isn't asked again."""
    grocy_client._retry_at.clear()


def intercept(client, grocy, answer):
    """Give `answer(request)` first go at the app's Grocy traffic; None = serve it."""

    def handler(request):
        return answer(request) or grocy.handler(request)

    client.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def trip_id(authed, grocy):
    stock_walmart_products(grocy)
    trip_id = authed.post("/api/trips", json={}).json()["id"]
    first = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": MILK}).json()
    assert first["item"]["state"] == "ready"
    assert authed.get(f"/api/trips/{trip_id}").json()["grocy_reachable"] is True
    assert authed.get("/api/grocy/meta").json()["grocy_reachable"] is True
    return trip_id


@pytest.mark.parametrize("outage", ["down", "gateway_down"])
def test_scanning_and_viewing_work_from_the_snapshot(authed, grocy, trip_id, outage):
    setattr(grocy, outage, True)
    cache_expires()

    known = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": EGGS})
    assert known.status_code == 200
    assert known.json()["item"]["name"] == "Great Value Large White Eggs 12ct"
    assert known.json()["item"]["state"] == "ready"
    unknown = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "9999999999994"})
    assert unknown.json()["item"]["state"] == "needs_product"

    trip = authed.get(f"/api/trips/{trip_id}")
    assert trip.status_code == 200 and trip.json()["grocy_reachable"] is False
    assert [i["state"] for i in trip.json()["items"]] == ["ready", "ready", "needs_product"]
    meta = authed.get("/api/grocy/meta").json()
    assert meta["grocy_reachable"] is False and meta["grocy_version"] is None
    assert [loc["name"] for loc in meta["locations"]] == ["Pantry"]
    assert authed.get("/api/grocy/products", params={"q": "tide"}).json()[0]["name"] == (
        "Tide Pods 42ct"
    )
    edited = authed.patch(f"/api/trips/{trip_id}", json={"name": "Saturday"}).json()
    assert (edited["name"], edited["grocy_reachable"]) == ("Saturday", False)
    if outage == "down":
        # One refresh was attempted; everything after it answered without asking.
        assert grocy.refused == 1

    # Back up: the next refresh notices.
    setattr(grocy, outage, False)
    backoff_passes()
    assert authed.get(f"/api/trips/{trip_id}").json()["grocy_reachable"] is True
    assert authed.get("/api/grocy/meta").json()["grocy_version"] == "4.7.1"


@pytest.mark.parametrize("outage", ["down", "gateway_down"])
def test_an_action_that_finds_grocy_down_is_explained_by_the_next_trip_load(
    authed, grocy, trip_id, outage
):
    """Grocy went away seconds ago, so the copy in memory is fresh and still says
    "reachable". The failed submit must flip that: the PWA reloads the trip right
    after a 503 to show its "Grocy can't be reached" notice."""
    setattr(grocy, outage, True)
    assert authed.get(f"/api/trips/{trip_id}").json()["grocy_reachable"] is True  # not noticed yet

    assert authed.post(f"/api/trips/{trip_id}/submit").json() == UNREACHABLE
    assert authed.get(f"/api/trips/{trip_id}").json()["grocy_reachable"] is False
    assert authed.get("/api/grocy/meta").json()["grocy_reachable"] is False

    setattr(grocy, outage, False)
    backoff_passes()
    assert authed.get(f"/api/trips/{trip_id}").json()["grocy_reachable"] is True


@pytest.mark.parametrize("outage", ["down", "gateway_down"])
def test_submit_during_an_outage_changes_nothing(authed, grocy, trip_id, outage):
    authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": EGGS})
    before = authed.get(f"/api/trips/{trip_id}").json()
    setattr(grocy, outage, True)
    cache_expires()

    r = authed.post(f"/api/trips/{trip_id}/submit")
    assert r.status_code == 503 and r.json() == UNREACHABLE
    after = authed.get(f"/api/trips/{trip_id}").json()
    assert after["status"] == "open" and grocy.bookings == []
    # Not "every item failed with a connection error": the items are as they were.
    assert [(i["state"], i["error"]) for i in after["items"]] == [("ready", None)] * 2
    assert after["items"] == before["items"]

    # The other things that genuinely need Grocy say the same.
    r = authed.post("/api/grocy/stores", json={"name": "Aldi"})
    assert r.status_code == 503 and r.json() == UNREACHABLE

    setattr(grocy, outage, False)
    backoff_passes()
    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert (result["committed"], result["failed"]) == (2, 0)
    assert result["trip"]["status"] == "submitted" and result["trip"]["grocy_reachable"] is True


def test_grocy_going_down_midway_keeps_what_was_booked(authed, grocy, trip_id):
    authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": EGGS})

    def dies_after_the_first_booking(request):
        if request.url.path.endswith("/add") and len(grocy.bookings) == 1:
            raise httpx.ConnectError("Connection refused", request=request)

    intercept(authed, grocy, dies_after_the_first_booking)
    r = authed.post(f"/api/trips/{trip_id}/submit")
    assert r.status_code == 503 and r.json() == UNREACHABLE
    states = [i["state"] for i in authed.get(f"/api/trips/{trip_id}").json()["items"]]
    assert states == ["committed", "ready"] and len(grocy.bookings) == 1

    intercept(authed, grocy, lambda request: None)
    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert result["committed"] == 1 and result["trip"]["status"] == "submitted"
    assert len(grocy.bookings) == 2  # nothing booked twice


def test_undo_during_an_outage_leaves_the_trip_submitted(authed, grocy, trip_id):
    authed.post(f"/api/trips/{trip_id}/submit")
    grocy.down = True
    cache_expires()
    r = authed.post(f"/api/trips/{trip_id}/undo")
    assert r.status_code == 503 and r.json() == UNREACHABLE
    trip = authed.get(f"/api/trips/{trip_id}").json()
    assert trip["status"] == "submitted" and trip["items"][0]["error"] is None
    assert grocy.undone == []


def test_snapshot_survives_an_app_restart(authed, grocy, tmp_path):
    # A product bought in packs of 6: that factor lives in `conversions`, whose keys
    # are tuples and so need care on the way to disk and back.
    soda = grocy.add_product("Cola Can", "5449000000996", qu_id_purchase=2)
    grocy.tables["quantity_unit_conversions_resolved"].append(
        {"id": 1, "product_id": soda, "from_qu_id": 2, "to_qu_id": 1, "factor": 6}
    )
    trip_id = authed.post("/api/trips", json={}).json()["id"]
    snapshot = tmp_path / "grocy-master-data.json"
    assert json.loads(snapshot.read_text())["base_url"] == API

    grocy.down = True
    grocy_client.reset_cache()  # the app restarted while Grocy was still down

    item = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "5449000000996"}).json()
    assert item["item"]["state"] == "ready" and item["item"]["name"] == "Cola Can"
    assert (item["item"]["pack_factor"], item["item"]["pack_unit"]) == (6, "Pack")
    trip = authed.get(f"/api/trips/{trip_id}").json()
    assert trip["grocy_reachable"] is False and trip["items"][0]["stock_amount"] == 6
    assert authed.post(f"/api/trips/{trip_id}/submit").status_code == 503


def test_receipts_are_matched_against_the_snapshot_during_an_outage(
    authed, grocy, trip_id, monkeypatch
):
    monkeypatch.setattr(
        "app.services.receipts.parse_receipt_images", lambda paths: parse_text(samples.WALMART)
    )
    grocy.down = True
    cache_expires()
    r = authed.post(
        f"/api/trips/{trip_id}/receipts", files=[("files", ("r.jpg", jpeg_bytes(), "image/jpeg"))]
    )
    assert r.status_code == 201
    trip = wait_until_read(authed, trip_id)
    assert trip["receipts"][0]["status"] == "ready" and trip["grocy_reachable"] is False
    assert trip["receipts"][0]["shopping_location_id"] == 1  # Walmart, from the snapshot
    assert [(i["name"], i["match_method"]) for i in trip["items"]] == [
        ("Great Value Whole Milk 1 Gallon", "upc")
    ]


def test_without_any_snapshot_an_outage_is_a_503(authed, grocy):
    grocy.down = True
    for _ in range(2):
        r = authed.post("/api/trips", json={})
        assert r.status_code == 503 and r.json() == UNREACHABLE


def test_a_snapshot_of_a_different_grocy_is_not_used(authed, grocy, trip_id, tmp_path):
    snapshot = tmp_path / "grocy-master-data.json"
    saved = json.loads(snapshot.read_text())
    snapshot.write_text(json.dumps({**saved, "base_url": "http://other-grocy.test/api"}))
    grocy.down = True
    grocy_client.reset_cache()
    assert authed.get(f"/api/trips/{trip_id}").status_code == 503


def test_a_rejected_key_is_not_treated_as_an_outage(authed, grocy, trip_id):
    grocy.api_keys.clear()
    cache_expires()
    r = authed.get(f"/api/trips/{trip_id}")
    assert r.status_code == 401 and r.json()["code"] == "grocy_account_invalid"


def test_other_grocy_errors_are_still_a_502(authed, grocy):
    def refuses_new_stores(request):
        if request.method == "POST" and request.url.path.endswith("/shopping_locations"):
            return httpx.Response(400, json={"error_message": "Name is not unique"})

    intercept(authed, grocy, refuses_new_stores)
    r = authed.post("/api/grocy/stores", json={"name": "Walmart"})
    assert r.status_code == 502
    assert r.json() == {"detail": "Grocy error (400): Name is not unique"}
