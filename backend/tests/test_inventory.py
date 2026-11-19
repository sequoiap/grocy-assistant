"""Inventory trips: counting what is already in the house, with due dates per piece."""

from datetime import date, timedelta

BEANS = "0041331024488"
SOUP = "0051000012616"
SOUP_CASE = "10051000012613"


def _trip(authed, kind="inventory"):
    r = authed.post("/api/trips", json={"kind": kind})
    assert r.status_code == 201, r.text
    return r.json()


def _scan(authed, trip_id, code):
    r = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": code})
    assert r.status_code == 200, r.text
    return r.json()


def _patch(authed, trip_id, item_id, body):
    return authed.patch(f"/api/trips/{trip_id}/items/{item_id}", json=body)


def _item(trip, item_id):
    return next(i for i in trip["items"] if i["id"] == item_id)


def _day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_count_by_scanning_split_due_dates_and_book_as_inventory(authed, grocy):
    beans = grocy.add_product("Black Beans", BEANS, default_best_before_days=365)
    trip = _trip(authed)
    assert trip["kind"] == "inventory"
    tid = trip["id"]

    for _ in range(3):
        scan = _scan(authed, tid, BEANS)
    item = scan["item"]
    assert scan["duplicate"] is True
    assert (item["quantity"], item["quantity_source"], item["scan_count"]) == (3, "scans", 3)
    assert (item["lots"], item["rest_amount"], item["due_source"]) == ([], 3, "default")
    assert item["in_stock"] == 0 and item["warnings"] == []

    # One can is due sooner than the others.
    trip = _patch(authed, tid, item["id"], {"lots": [{"amount": 1, "due_date": _day(20)}]}).json()
    item = _item(trip, item["id"])
    assert (item["quantity"], item["rest_amount"]) == (3, 2)

    # A dated lot beyond what was counted is an extra can, not a mistake.
    lots = [{"amount": 1, "due_date": _day(20)}, {"amount": 3, "due_date": _day(90)}]
    trip = _patch(authed, tid, item["id"], {"lots": lots}).json()
    item = _item(trip, item["id"])
    assert (item["quantity"], item["quantity_source"], item["rest_amount"]) == (4, "manual", 0)

    # Counting fewer than the dated ones is refused rather than guessed at.
    r = _patch(authed, tid, item["id"], {"quantity": 3})
    assert r.status_code == 422 and "own due dates" in r.json()["detail"]

    # Scanning one more after that still counts, as an undated can.
    item = _scan(authed, tid, BEANS)["item"]
    assert (item["quantity"], item["rest_amount"]) == (5, 1)

    result = authed.post(f"/api/trips/{tid}/submit").json()
    assert result["committed"] == 1 and result["trip"]["status"] == "submitted"
    assert [(b["amount"], b["best_before_date"]) for b in grocy.bookings] == [
        (1, _day(20)),
        (3, _day(90)),
        (1, _day(365)),
    ]
    for b in grocy.bookings:
        assert b["product_id"] == beans
        assert b["transaction_type"] == "inventory-correction"
        assert "price" not in b and "shopping_location_id" not in b
    assert _item(result["trip"], item["id"])["committed_amount"] == 5

    # Undo takes every one of them back out.
    authed.post(f"/api/trips/{tid}/undo")
    assert sorted(grocy.undone) == ["tx1", "tx2", "tx3"]


def test_shopping_trips_still_book_purchases_with_lots(authed, grocy):
    grocy.add_product("Black Beans", BEANS)
    tid = _trip(authed, kind="shopping")["id"]
    item = _scan(authed, tid, BEANS)["item"]
    assert _trip_kind(authed, tid) == "shopping"
    _patch(authed, tid, item["id"], {"quantity": 2, "lots": [{"amount": 1, "due_date": "never"}]})
    authed.post(f"/api/trips/{tid}/submit")
    booked = [(b["amount"], b["best_before_date"], b["transaction_type"]) for b in grocy.bookings]
    assert booked == [
        (1, "2999-12-31", "purchase"),
        (1, "2999-12-31", "purchase"),  # the product's default: never due
    ]


def _trip_kind(authed, tid):
    return authed.get(f"/api/trips/{tid}").json()["kind"]


def test_scans_keep_counting_after_the_amount_was_typed(authed, grocy):
    grocy.add_product("Black Beans", BEANS)
    tid = _trip(authed)["id"]
    item = _scan(authed, tid, BEANS)["item"]
    _patch(authed, tid, item["id"], {"quantity": 6})
    item = _scan(authed, tid, BEANS)["item"]
    assert (item["quantity"], item["quantity_source"]) == (7, "manual")


def test_other_barcodes_of_a_counted_product_add_to_it(authed, grocy):
    soup = grocy.add_product("Tomato Soup", SOUP)
    grocy.tables["product_barcodes"].append(
        {"id": 9, "product_id": soup, "barcode": SOUP_CASE, "amount": 12, "qu_id": 1}
    )
    tid = _trip(authed)["id"]
    first = _scan(authed, tid, SOUP)["item"]
    label = _scan(authed, tid, f"grcy:p:{soup}")
    assert label["duplicate"] is True and label["item"]["id"] == first["id"]
    assert label["item"]["quantity"] == 2

    # A case of twelve is a different thing to count, so it gets a row of its own.
    case = _scan(authed, tid, SOUP_CASE)
    assert case["duplicate"] is False and case["item"]["stock_amount"] == 12

    # Shopping trips keep separate barcodes apart (each may match its own receipt line).
    shop = _trip(authed, kind="shopping")["id"]
    _scan(authed, shop, SOUP)
    assert _scan(authed, shop, f"grcy:p:{soup}")["duplicate"] is False


def test_stock_already_in_grocy_is_pointed_out(authed, grocy):
    beans = grocy.add_product("Black Beans", BEANS)
    grocy.stock[beans] = 2
    tid = _trip(authed)["id"]
    item = _scan(authed, tid, BEANS)["item"]
    assert item["in_stock"] == 2
    assert any("already has 2" in w for w in item["warnings"])

    # Not a concern on a shopping trip: buying more of something is normal.
    shop = _trip(authed, kind="shopping")["id"]
    item = _scan(authed, shop, BEANS)["item"]
    assert item["in_stock"] == 2 and item["warnings"] == []


def test_an_item_is_booked_whole_or_not_at_all(authed, grocy):
    beans = grocy.add_product("Black Beans", BEANS)
    tid = _trip(authed)["id"]
    item = _scan(authed, tid, BEANS)["item"]
    lots = [{"amount": 1, "due_date": _day(10)}, {"amount": 1, "due_date": _day(40)}]
    _patch(authed, tid, item["id"], {"lots": lots})

    grocy.fail_add_after[beans] = 1  # the first entry goes in, the second is refused
    result = authed.post(f"/api/trips/{tid}/submit").json()
    assert (result["committed"], result["failed"]) == (0, 1)
    assert grocy.undone == ["tx1"]  # the half that went in was taken back out

    del grocy.fail_add_after[beans]
    result = authed.post(f"/api/trips/{tid}/submit").json()
    assert result["committed"] == 1
    live = [b for b in grocy.bookings if b["transaction_id"] not in grocy.undone]
    assert [b["best_before_date"] for b in live] == [_day(10), _day(40)]


def test_a_rollback_that_failed_is_finished_before_booking_again(authed, grocy):
    beans = grocy.add_product("Black Beans", BEANS)
    tid = _trip(authed)["id"]
    item = _scan(authed, tid, BEANS)["item"]
    _patch(authed, tid, item["id"], {"lots": [{"amount": 1, "due_date": _day(10)}], "quantity": 2})

    grocy.fail_add_after[beans] = 1
    grocy.fail_undo.add("tx1")
    result = authed.post(f"/api/trips/{tid}/submit").json()
    assert result["failed"] == 1 and grocy.undone == []

    grocy.fail_add_after.clear()
    grocy.fail_undo.clear()
    result = authed.post(f"/api/trips/{tid}/submit").json()
    assert result["committed"] == 1
    assert grocy.undone == ["tx1"]
    live = [b for b in grocy.bookings if b["transaction_id"] not in grocy.undone]
    assert sum(b["amount"] for b in live) == 2


def test_bulk_edit(authed, grocy):
    grocy.add_product("Black Beans", BEANS)
    grocy.add_product("Tomato Soup", SOUP)
    grocy.tables["locations"].append({"id": 2, "name": "Basement", "active": 1})
    tid = _trip(authed)["id"]
    ids = [_scan(authed, tid, code)["item"]["id"] for code in (BEANS, SOUP)]

    body = {"item_ids": ids, "location_id": 2, "shopping_location_id": 1, "due_date": _day(30)}
    trip = authed.patch(f"/api/trips/{tid}/items", json=body).json()
    for i in trip["items"]:
        assert (i["location_id"], i["shopping_location_id"]) == (2, 1)
        assert (i["due_date"], i["due_source"]) == (_day(30), "manual")

    # null goes back to the product's own default; unsent fields are left alone.
    trip = authed.patch(f"/api/trips/{tid}/items", json={"item_ids": ids, "due_date": None}).json()
    assert {i["due_source"] for i in trip["items"]} == {"default"}
    assert {i["location_id"] for i in trip["items"]} == {2}

    trip = authed.patch(f"/api/trips/{tid}/items", json={"item_ids": ids[:1], "skipped": True})
    assert [i["state"] for i in trip.json()["items"]] == ["skipped", "ready"]

    bad = authed.patch(f"/api/trips/{tid}/items", json={"item_ids": ids, "location_id": 99})
    assert bad.status_code == 422
    assert authed.patch(f"/api/trips/{tid}/items", json={"item_ids": [999]}).status_code == 404
