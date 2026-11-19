"""Consuming and opening stock from the phone: by barcode, label or search."""

MILK = "0041900076610"
YOGURT_6 = "0070470003023"  # the barcode on a six-pack of yogurt cups


def _scan(authed, code):
    return authed.post("/api/stock/scan", json={"barcode": code})


def test_scan_consume_and_undo(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK, quick_consume_amount=1)
    grocy.stock[milk] = 3

    r = _scan(authed, MILK)
    assert r.status_code == 200, r.text
    product = r.json()
    assert (product["id"], product["name"], product["amount"]) == (milk, "Whole Milk", 3)
    assert (product["unit"], product["unit_plural"]) == ("Piece", "Pieces")
    assert product["location"] == "Pantry"
    assert product["next_due_date"] == "2026-12-01"
    assert product["quick_consume_amount"] == 1 and product["pack_amount"] is None

    r = authed.post(f"/api/stock/products/{milk}/consume", json={"amount": 2})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["product"]["amount"] == 1
    action = grocy.stock_actions[-1]
    assert (action["action"], action["amount"], action["spoiled"]) == ("consume", 2, False)
    assert action["transaction_type"] == "consume"
    assert "stock_entry_id" not in action

    r = authed.post("/api/stock/undo", json={"transaction_id": out["transaction_id"]})
    assert r.status_code == 204
    assert grocy.undone == [out["transaction_id"]]
    assert _scan(authed, MILK).json()["amount"] == 3


def test_open_some_then_the_rest_cannot_be_opened_twice(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 2

    r = authed.post(f"/api/stock/products/{milk}/open", json={"amount": 1})
    assert r.status_code == 200, r.text
    assert r.json()["product"]["amount_opened"] == 1
    assert grocy.stock_actions[-1]["action"] == "open"

    r = authed.post(f"/api/stock/products/{milk}/open", json={"amount": 2})
    assert r.status_code == 409
    assert "cannot be > current stock amount" in r.json()["detail"]


def test_spoiled_and_more_than_there_is(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 1

    r = authed.post(f"/api/stock/products/{milk}/consume", json={"amount": 5})
    assert r.status_code == 409 and r.json()["detail"].startswith("Grocy refused:")
    assert grocy.stock_actions == []

    r = authed.post(f"/api/stock/products/{milk}/consume", json={"amount": 1, "spoiled": True})
    assert r.status_code == 200
    assert grocy.stock_actions[-1]["spoiled"] is True


def test_part_of_a_unit_and_weighed_containers(authed, grocy):
    # Grocy 4 allows decimal amounts for every product; its old per-product
    # "allow partial units" option is still in the table but no longer read.
    flour = grocy.add_product("Flour", allow_partial_units_in_stock=0)
    sugar = grocy.add_product("Sugar", enable_tare_weight_handling=1)
    grocy.stock |= {flour: 2, sugar: 900}

    r = authed.post(f"/api/stock/products/{flour}/consume", json={"amount": 0.5})
    assert r.status_code == 200, r.text
    assert r.json()["product"]["amount"] == 1.5
    assert "allow_partial" not in r.json()["product"]

    r = authed.post(f"/api/stock/products/{sugar}/consume", json={"amount": 100})
    assert r.status_code == 409 and "Grocy itself" in r.json()["detail"]
    assert len(grocy.stock_actions) == 1


def test_undo_an_open_and_refuse_ids_that_are_not_grocys(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 2
    opened = authed.post(f"/api/stock/products/{milk}/open", json={"amount": 1}).json()
    assert opened["product"]["amount_opened"] == 1

    r = authed.post("/api/stock/undo", json={"transaction_id": opened["transaction_id"]})
    assert r.status_code == 204
    assert _scan(authed, MILK).json()["amount_opened"] == 0

    # Goes into a Grocy URL path, so only Grocy's own kind of id gets through.
    before = len(grocy.requests)
    for bad in ("../../objects/products", "abc?x=1", "a/b", ""):
        r = authed.post("/api/stock/undo", json={"transaction_id": bad})
        assert r.status_code == 422, bad
    assert len(grocy.requests) == before


def test_not_allowed_to_change_stock(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 1
    grocy.forbid_stock_changes = True
    r = authed.post(f"/api/stock/products/{milk}/consume", json={"amount": 1})
    assert r.status_code == 403 and "isn't allowed" in r.json()["detail"]
    assert grocy.stock_actions == []


def test_a_label_for_a_product_grocy_does_not_have(authed, grocy):
    r = _scan(authed, "grcy:p:99")
    assert r.status_code == 404 and r.json()["detail"] == "Grocy has no such product."
    r = _scan(authed, "grcy:p:milk")
    assert r.status_code == 404


def test_a_pack_barcode_offers_the_whole_pack(authed, grocy):
    yogurt = grocy.add_product("Yogurt Cup", qu_id_stock=1)
    grocy.tables["product_barcodes"].append(
        {"id": 9, "product_id": yogurt, "barcode": YOGURT_6, "amount": 6, "qu_id": 1}
    )
    grocy.stock[yogurt] = 6
    product = _scan(authed, YOGURT_6).json()
    assert product["pack_amount"] == 6 and product["quick_consume_amount"] == 1


def test_grocycode_label_of_one_package(authed, grocy):
    chili = grocy.add_product("Leftover Chili")
    grocy.stock[chili] = 5
    # One container on its own, and the four from another cook-up. Opening part of a
    # package splits it into rows that keep its stock_id.
    grocy.entries[chili] = [
        {"stock_id": "65a1b2c3d4e5f", "amount": 1, "open": 1, "best_before_date": "2026-11-25"},
        {"stock_id": "65a1b2c3d4e5f", "amount": 1, "open": 0, "best_before_date": "2026-11-25"},
        {"stock_id": "77ffee0011223", "amount": 3, "open": 0, "best_before_date": "2026-12-20"},
    ]
    product = _scan(authed, f"grcy:p:{chili}:65a1b2c3d4e5f").json()
    assert product["stock_entry_id"] == "65a1b2c3d4e5f"
    assert (product["amount"], product["amount_opened"]) == (2, 1)
    assert (product["product_amount"], product["next_due_date"]) == (5, "2026-11-25")

    # More than the package holds is refused here: Grocy itself would check it against
    # the whole product's 5, book only the package's 2, and still answer success.
    body = {"amount": 3, "stock_entry_id": "65a1b2c3d4e5f"}
    r = authed.post(f"/api/stock/products/{chili}/consume", json=body)
    assert r.status_code == 409 and r.json()["detail"] == "This package holds only 2 Pieces."
    body = {"amount": 2, "stock_entry_id": "65a1b2c3d4e5f"}
    r = authed.post(f"/api/stock/products/{chili}/open", json=body)
    assert r.status_code == 409 and "Only 1 Piece of this package is unopened" in r.text
    assert grocy.stock_actions == []

    body = {"amount": 2, "stock_entry_id": "65a1b2c3d4e5f"}
    r = authed.post(f"/api/stock/products/{chili}/consume", json=body)
    assert r.status_code == 200
    assert grocy.stock_actions[-1]["stock_entry_id"] == "65a1b2c3d4e5f"
    assert r.json()["product"]["product_amount"] is None  # the whole product again
    assert r.json()["product"]["amount"] == 3

    # The label of a package that's all used up.
    product = _scan(authed, f"grcy:p:{chili}:65a1b2c3d4e5f").json()
    assert (product["amount"], product["product_amount"]) == (0, 3)
    assert product["next_due_date"] is None
    r = authed.post(f"/api/stock/products/{chili}/consume", json=body | {"amount": 1})
    assert r.status_code == 409 and r.json()["detail"] == "This package is used up."


def test_a_product_that_is_never_opened(authed, grocy):
    salt = grocy.add_product("Salt", disable_open=1)
    grocy.stock[salt] = 1
    assert _scan(authed, f"grcy:p:{salt}").json()["can_open"] is False
    r = authed.post(f"/api/stock/products/{salt}/open", json={"amount": 1})
    assert r.status_code == 409 and "never be opened" in r.json()["detail"]
    assert grocy.stock_actions == []


def test_unknown_barcode_and_a_product_none_is_left_of(authed, grocy):
    r = _scan(authed, "0000000000017")
    assert r.status_code == 404 and "No product in Grocy" in r.json()["detail"]

    grocy.add_product("Whole Milk", MILK)
    product = _scan(authed, MILK).json()
    assert product["amount"] == 0 and product["next_due_date"] is None


def test_a_barcode_added_in_grocy_moments_ago_is_found(authed, grocy):
    authed.get("/api/stock")  # the snapshot is now cached without it
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 1
    assert _scan(authed, MILK).json()["id"] == milk


def test_list_has_only_what_is_in_stock(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    beans = grocy.add_product("Black Beans")
    grocy.add_product("Out Of Stock")
    retired = grocy.add_product("Old Thing", active=0)
    grocy.stock |= {milk: 2, beans: 4, retired: 1}
    authed.post(f"/api/stock/products/{milk}/open", json={"amount": 1})

    r = authed.get("/api/stock")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [(p["name"], p["amount"], p["amount_opened"]) for p in rows] == [
        ("Black Beans", 4, 0),
        ("Whole Milk", 2, 1),
    ]
    assert rows[0]["next_due_date"] == "never"


def test_grocy_down_changes_nothing(authed, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 1
    authed.get("/api/stock")
    grocy.down = True
    r = authed.post(f"/api/stock/products/{milk}/consume", json={"amount": 1})
    assert r.status_code == 503 and r.json()["code"] == "grocy_unreachable"
    assert "nothing was changed" in r.json()["detail"]
    assert grocy.stock_actions == []


def test_signed_out_people_cannot_consume(client, grocy):
    milk = grocy.add_product("Whole Milk", MILK)
    grocy.stock[milk] = 1
    assert client.post(f"/api/stock/products/{milk}/consume", json={"amount": 1}).status_code == 401
    assert client.get("/api/stock").status_code == 401
