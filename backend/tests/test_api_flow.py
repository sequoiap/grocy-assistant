"""The whole trip lifecycle through the HTTP API against a fake Grocy."""

import time

from app.receipts.pipeline import parse_text

from .conftest import GROCY, jpeg_bytes
from .receipts import samples

MILK, EGGS, WATER, PODS, CHICKEN = (
    "078742351865",
    "078742370033",
    "078742029061",
    "037000875659",
    "261376000005",
)


def wait_until_read(client, trip_id):
    for _ in range(100):
        trip = client.get(f"/api/trips/{trip_id}").json()
        if not trip["processing"]:
            return trip
        time.sleep(0.05)
    raise AssertionError("receipt never finished processing")


def stock_walmart_products(grocy):
    ids = {
        "milk": grocy.add_product("Great Value Whole Milk 1 Gallon", MILK),
        "eggs": grocy.add_product("Great Value Large White Eggs 12ct", EGGS),
        "water": grocy.add_product("Great Value Spring Water", WATER, default_best_before_days=30),
        "pods": grocy.add_product("Tide Pods 42ct", PODS),
        "chicken": grocy.add_product("Marketside Chicken Breast", CHICKEN),
        "bananas": grocy.add_product("Bananas"),
    }
    return ids


def upload_walmart_receipt(client, monkeypatch, trip_id):
    monkeypatch.setattr(
        "app.services.receipts.parse_receipt_images", lambda paths: parse_text(samples.WALMART)
    )
    r = client.post(
        f"/api/trips/{trip_id}/receipts", files=[("files", ("r.jpg", jpeg_bytes(), "image/jpeg"))]
    )
    assert r.status_code == 201, r.text
    return wait_until_read(client, trip_id)


def test_scan_receipt_review_submit_undo(authed, grocy, monkeypatch):
    ids = stock_walmart_products(grocy)
    trip_id = authed.post("/api/trips", json={}).json()["id"]

    for code in (MILK, EGGS, WATER, PODS, CHICKEN):
        scan = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": code}).json()
        assert scan["item"]["state"] == "ready" and scan["duplicate"] is False
    again = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "0" + MILK}).json()
    assert again["duplicate"] is True and again["item"]["scan_count"] == 2

    trip = upload_walmart_receipt(authed, monkeypatch, trip_id)
    receipt = trip["receipts"][0]
    assert receipt["status"] == "ready" and receipt["store_key"] == "walmart"
    assert receipt["shopping_location_id"] == 1  # matched to Grocy's "Walmart" by name

    items = {i["name"]: i for i in trip["items"]}
    assert all(i["match_method"] == "upc" for i in items.values())
    # The receipt decides the quantity, even over a double scan.
    assert items["Great Value Whole Milk 1 Gallon"]["quantity"] == 1
    water = items["Great Value Spring Water"]
    assert (water["quantity"], water["quantity_source"]) == (2, "receipt")
    assert (water["line_total"], water["unit_price"]) == (1.96, 0.98)
    assert water["due_source"] == "default" and water["due_date"] != "never"
    assert items["Tide Pods 42ct"]["due_date"] == "never"

    # Bananas have no barcode: turn the leftover receipt line into an item.
    loose = [ln for ln in receipt["lines"] if ln["matched_item_id"] is None]
    assert [ln["description"] for ln in loose] == ["BANANAS"]
    trip = authed.post(
        f"/api/receipt-lines/{loose[0]['id']}/item", json={"product_id": ids["bananas"]}
    ).json()
    assert len(trip["items"]) == 6 and trip["ready_count"] == 6

    # A manual quantity override wins over the receipt.
    pods = next(i for i in trip["items"] if i["name"] == "Tide Pods 42ct")
    trip = authed.patch(f"/api/trips/{trip_id}/items/{pods['id']}", json={"quantity": 3}).json()
    pods = next(i for i in trip["items"] if i["id"] == pods["id"])
    assert (pods["quantity"], pods["quantity_source"], pods["unit_price"]) == (3, "manual", 4.3233)

    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert (result["committed"], result["failed"], result["remaining"]) == (6, 0, 0)
    assert result["trip"]["status"] == "submitted"
    booked = {b["product_id"]: b for b in grocy.bookings}
    assert booked[ids["water"]]["amount"] == 2 and booked[ids["water"]]["price"] == 0.98
    assert booked[ids["pods"]]["amount"] == 3
    assert booked[ids["pods"]]["best_before_date"] == "2999-12-31"
    assert all(b["shopping_location_id"] == 1 for b in grocy.bookings)
    assert all(b["transaction_type"] == "purchase" for b in grocy.bookings)
    assert {b["booked_by"] for b in grocy.bookings} == {"alex"}  # under the signed-in user

    # Submitting again must not book anything twice; edits are locked until undo.
    assert authed.post(f"/api/trips/{trip_id}/submit").status_code == 409
    assert len(grocy.bookings) == 6

    undone = authed.post(f"/api/trips/{trip_id}/undo").json()
    assert undone["status"] == "open" and len(grocy.undone) == 6

    # Next trip to the same store, receipt first: every line is recognized from what
    # was learned, with no scanning at all.
    trip2 = authed.post("/api/trips", json={}).json()["id"]
    trip = upload_walmart_receipt(authed, monkeypatch, trip2)
    assert len(trip["items"]) == 6 and trip["ready_count"] == 6
    assert {(i["source"], i["match_method"]) for i in trip["items"]} == {("receipt", "learned")}
    assert "Bananas" in {i["name"] for i in trip["items"]}

    # Scanning one of them afterwards claims its line instead of duplicating it.
    authed.post(f"/api/trips/{trip2}/scan", json={"barcode": MILK})
    trip = authed.get(f"/api/trips/{trip2}").json()
    milk = [i for i in trip["items"] if i["name"] == "Great Value Whole Milk 1 Gallon"]
    assert [(i["source"], i["match_method"]) for i in milk] == [("scan", "upc")]
    assert len(trip["items"]) == 6


def test_unknown_barcode_lookup_create_and_link(authed, grocy):
    grocy.off_products["3017620422003"] = {
        "product_name": "Nutella",
        "brands": "Ferrero",
        "quantity": "400 g",
    }
    existing = grocy.add_product("Peanut Butter")
    trip_id = authed.post("/api/trips", json={}).json()["id"]

    found = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "3017620422003"}).json()
    item = found["item"]
    assert item["state"] == "needs_product"
    assert item["lookup"]["suggested_name"] == "Ferrero Nutella (400 g)"
    unknown = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "9999999999994"}).json()
    assert unknown["item"]["lookup"]["found"] is False

    # Nothing is booked while items still need a decision.
    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert (result["committed"], result["remaining"]) == (0, 2)
    assert result["trip"]["status"] == "open"

    draft = {"name": "Nutella 400g", "location_id": 1, "qu_id": 1, "default_best_before_days": 90}
    trip = authed.patch(
        f"/api/trips/{trip_id}/items/{item['id']}", json={"new_product": draft}
    ).json()
    assert trip["attention_count"] == 1
    trip = authed.patch(
        f"/api/trips/{trip_id}/items/{unknown['item']['id']}", json={"product_id": existing}
    ).json()
    linked = next(i for i in trip["items"] if i["id"] == unknown["item"]["id"])
    assert linked["link_barcode"] is True and linked["state"] == "ready"

    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert (result["committed"], result["failed"], result["remaining"]) == (2, 0, 0)
    created = grocy.tables["products"][-1]
    assert created["name"] == "Nutella 400g" and created["default_best_before_days"] == 90
    barcodes = {b["barcode"]: b["product_id"] for b in grocy.tables["product_barcodes"]}
    assert barcodes == {"3017620422003": created["id"], "9999999999994": existing}


def test_failed_item_can_be_retried_without_double_booking(authed, grocy):
    good = grocy.add_product("Rice", "1111111111116")
    bad = grocy.add_product("Beans", "2222222222222")
    grocy.fail_add_for.add(bad)
    trip_id = authed.post("/api/trips", json={}).json()["id"]
    for code in ("1111111111116", "2222222222222"):
        authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": code})

    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert (result["committed"], result["failed"]) == (1, 1)
    failed = next(i for i in result["trip"]["items"] if i["state"] == "failed")
    assert "Product is broken" in failed["error"]
    assert result["trip"]["status"] == "open"

    grocy.fail_add_for.clear()
    result = authed.post(f"/api/trips/{trip_id}/submit").json()
    assert (result["committed"], result["failed"]) == (1, 0)
    assert result["trip"]["status"] == "submitted"
    assert sorted(b["product_id"] for b in grocy.bookings) == [good, bad]


def test_pack_barcode_multiplies_stock_amount(authed, grocy):
    soda = grocy.add_product("Cola Can")
    grocy.tables["product_barcodes"].append(
        {"id": 1, "product_id": soda, "barcode": "5449000000996", "amount": 12, "qu_id": 1}
    )
    trip_id = authed.post("/api/trips", json={}).json()["id"]
    item = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "5449000000996"}).json()[
        "item"
    ]
    assert (item["quantity"], item["pack_factor"], item["stock_amount"]) == (1, 12, 12)
    trip = authed.patch(
        f"/api/trips/{trip_id}/items/{item['id']}", json={"quantity": 2, "line_total": 12.0}
    ).json()
    assert (trip["items"][0]["stock_amount"], trip["items"][0]["unit_price"]) == (24, 0.5)
    authed.post(f"/api/trips/{trip_id}/submit")
    assert (grocy.bookings[0]["amount"], grocy.bookings[0]["price"]) == (24, 0.5)


def test_revision_moves_with_every_change_so_other_devices_can_follow(authed, grocy, monkeypatch):
    stock_walmart_products(grocy)
    trip = authed.post("/api/trips", json={}).json()
    trip_id = trip["id"]

    def revision():
        return authed.get(f"/api/trips/{trip_id}/revision").json()["revision"]

    seen = [revision()]
    assert trip["revision"] == seen[0]

    def changed():
        seen.append(revision())
        return seen[-1] > seen[-2]

    # Reading never moves it.
    authed.get(f"/api/trips/{trip_id}")
    assert revision() == seen[0]

    # A scan from the phone (which only gets the one item back, not the trip).
    item = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": MILK}).json()["item"]
    assert changed()
    authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": MILK})  # repeat scan
    assert changed()

    # A receipt upload, and again when the background read finishes.
    upload_walmart_receipt(authed, monkeypatch, trip_id)
    assert changed()
    full = authed.get(f"/api/trips/{trip_id}").json()
    assert full["revision"] == seen[-1]

    # Edits to items, receipt lines and receipts.
    assert (
        authed.patch(f"/api/trips/{trip_id}/items/{item['id']}", json={"note": "x"}).json()[
            "revision"
        ]
        == revision()
    )
    assert changed()
    line = next(ln for ln in full["receipts"][0]["lines"] if ln["matched_item_id"] is None)
    authed.patch(f"/api/receipt-lines/{line['id']}", json={"dismissed": True})
    assert changed()
    authed.patch(f"/api/receipts/{full['receipts'][0]['id']}", json={"purchased_on": "2026-11-01"})
    assert changed()

    # Removing things, submitting and undoing.
    authed.delete(f"/api/trips/{trip_id}/items/{item['id']}")
    assert changed()
    authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": EGGS})
    authed.post(f"/api/trips/{trip_id}/submit")
    assert changed()
    authed.post(f"/api/trips/{trip_id}/undo")
    assert changed()

    # Other trips are unaffected, and it needs a sign-in like everything else.
    other = authed.post("/api/trips", json={}).json()
    before = revision()
    authed.post(f"/api/trips/{other['id']}/scan", json={"barcode": PODS})
    assert revision() == before
    assert authed.get("/api/trips/99999/revision").status_code == 404
    authed.post("/api/auth/logout")
    assert authed.get(f"/api/trips/{trip_id}/revision").status_code == 401


def test_revision_column_is_added_to_an_older_database(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setenv("GA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GA_GROCY_URL", GROCY)
    from app import config, db

    config.get_config.cache_clear()
    db.reset_engine()
    old = sqlite3.connect(tmp_path / "grocy-assistant.db")
    old.execute(
        "CREATE TABLE trips (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(120),"
        " status VARCHAR(16), created_at DATETIME, submitted_at DATETIME)"
    )
    old.execute("INSERT INTO trips (id, user_id, name, status) VALUES (1, 1, 'old', 'open')")
    old.commit()
    old.close()

    db.init_db()
    db.init_db()  # idempotent
    check = sqlite3.connect(tmp_path / "grocy-assistant.db")
    assert check.execute("SELECT revision FROM trips WHERE id = 1").fetchone() == (0,)
    check.close()
    db.reset_engine()
    config.get_config.cache_clear()
