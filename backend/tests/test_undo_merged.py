"""Undoing a trip must take back only what the trip added.

Grocy 4.7.1 files new stock into an existing stock entry when every detail matches
(due date, price, location...), and undoing that addition's transaction deletes the
whole entry, including what was there before. The fake Grocy behaves the same way."""

MILK = "0070038000563"


def _trip(authed, kind="shopping"):
    r = authed.post("/api/trips", json={"kind": kind})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _buy(authed, code, quantity, kind="shopping"):
    """A trip with one scanned item, booked into Grocy. Returns the trip id."""
    tid = _trip(authed, kind)
    item = authed.post(f"/api/trips/{tid}/scan", json={"barcode": code}).json()["item"]
    r = authed.patch(
        f"/api/trips/{tid}/items/{item['id']}",
        json={"quantity": quantity, "line_total": 3.0 * quantity},
    )
    assert r.status_code == 200, r.text
    result = authed.post(f"/api/trips/{tid}/submit").json()
    assert result["committed"] == 1, result
    return tid


def _amount(authed, grocy, pid):
    return grocy._amounts().get(pid, 0)


def test_undo_keeps_stock_an_earlier_trip_added_to_the_same_entry(authed, grocy):
    milk = grocy.add_product("Milk", MILK, default_best_before_days=7)
    _buy(authed, MILK, 2)
    second = _buy(authed, MILK, 1)
    # Same day, same price, same place: Grocy filed both into one entry.
    assert [e["amount"] for e in grocy.entries[milk]] == [3]

    trip = authed.post(f"/api/trips/{second}/undo").json()

    assert trip["status"] == "open"
    assert _amount(authed, grocy, milk) == 2  # the first trip's milk is still there
    assert [e["amount"] for e in grocy.entries[milk]] == [2]
    assert grocy.undone == []  # shrunk, not undone: Grocy's undo would delete all 3
    assert [e["amount"] for e in grocy.entry_edits] == [2]


def test_undo_of_an_entry_of_its_own_still_uses_grocys_undo(authed, grocy):
    milk = grocy.add_product("Milk", MILK, default_best_before_days=7)
    tid = _buy(authed, MILK, 2)

    authed.post(f"/api/trips/{tid}/undo")

    assert grocy.undone == ["tx1"] and grocy.entry_edits == []
    assert _amount(authed, grocy, milk) == 0


def test_undo_after_a_partial_use_takes_back_only_the_addition(authed, grocy):
    milk = grocy.add_product("Milk", MILK, default_best_before_days=7)
    _buy(authed, MILK, 2)
    second = _buy(authed, MILK, 3)
    grocy.entries[milk][0]["amount"] -= 1  # someone drank one in the meantime
    grocy.stock[milk] = grocy.stock.get(milk, 0) - 1

    authed.post(f"/api/trips/{second}/undo")

    assert _amount(authed, grocy, milk) == 1
    assert [e["amount"] for e in grocy.entries[milk]] == [1]


def test_redo_after_undo_books_again_without_losing_the_earlier_stock(authed, grocy):
    milk = grocy.add_product("Milk", MILK, default_best_before_days=7)
    _buy(authed, MILK, 2)
    second = _buy(authed, MILK, 1)

    authed.post(f"/api/trips/{second}/undo")
    result = authed.post(f"/api/trips/{second}/submit").json()
    assert result["committed"] == 1
    assert _amount(authed, grocy, milk) == 3

    authed.post(f"/api/trips/{second}/undo")
    assert _amount(authed, grocy, milk) == 2


def test_inventory_counts_are_taken_back_the_same_way(authed, grocy):
    milk = grocy.add_product("Milk", MILK, default_best_before_days=7)
    _buy(authed, MILK, 2, kind="inventory")
    second = _buy(authed, MILK, 1, kind="inventory")

    authed.post(f"/api/trips/{second}/undo")

    assert _amount(authed, grocy, milk) == 2
    assert grocy.undone == []
