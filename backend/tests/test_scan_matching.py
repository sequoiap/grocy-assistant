"""A scan resolves against Grocy's own barcodes before anything is looked up online."""

import pytest

from app.grocy.client import barcode_variants, upc_a_to_e, upc_e_to_a

# A textbook pair: the UPC-E printed on a small pack and the UPC-A it stands for.
UPC_E, UPC_A = "04252614", "042100005264"


@pytest.mark.parametrize(
    ("short", "long"),
    [
        (UPC_E, UPC_A),  # last digit 0-2: manufacturer "XX?00", item "00???"
        ("01234531", "012300000451"),  # last digit 3
        ("01234543", "012340000053"),  # last digit 4
        ("01234558", "012345000058"),  # last digit 5-9
    ],
)
def test_upc_e_round_trips(short, long):
    assert upc_e_to_a(short) == long
    assert upc_a_to_e(long) == short


def test_codes_that_are_not_upc_e_stay_alone():
    assert upc_e_to_a("04252615") is None  # wrong check digit (an EAN-8, say)
    assert upc_e_to_a("96385074") is None  # number system 9 has no UPC-E
    assert upc_a_to_e("078742351865") is None  # this UPC-A has no short form
    assert upc_a_to_e("042100005265") is None  # wrong check digit


def test_variants_cover_both_forms_and_ean13():
    from_short = barcode_variants(UPC_E)
    from_long = barcode_variants("0" + UPC_A)  # as an EAN-13
    assert {UPC_A, "0" + UPC_A, UPC_E} <= set(from_short)
    assert {UPC_A, UPC_E} <= set(from_long)


@pytest.fixture
def trip_id(authed):
    return authed.post("/api/trips", json={}).json()["id"]


@pytest.mark.parametrize(("stored", "scanned"), [(UPC_A, UPC_E), (UPC_E, "0" + UPC_A)])
def test_scan_matches_the_other_upc_form(authed, grocy, trip_id, stored, scanned):
    grocy.add_product("Gum 5ct", stored)
    item = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": scanned}).json()["item"]
    assert (item["name"], item["state"]) == ("Gum 5ct", "ready")
    assert item["lookup"] is None and item["link_barcode"] is False


def test_unknown_barcode_asks_grocy_once_before_looking_online(authed, grocy, trip_id):
    grocy.add_product("Milk", "078742351865")
    authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "078742351865"})  # warm snapshot
    full, table = (
        grocy.count("GET", "/api/objects/products"),
        grocy.count("GET", "/api/objects/product_barcodes"),
    )

    item = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "9999999999994"}).json()
    assert item["item"]["state"] == "needs_product"
    assert grocy.count("GET", "/api/objects/products") == full  # no full refresh
    assert grocy.count("GET", "/api/objects/product_barcodes") == table + 1


def test_barcode_added_in_grocy_after_the_snapshot_is_found(authed, grocy, trip_id):
    grocy.add_product("Milk", "078742351865")
    authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "078742351865"})  # warm snapshot
    grocy.off_products["3017620422003"] = {"product_name": "Nutella"}
    grocy.add_product("Nutella 400g", "3017620422003")  # added in Grocy just now

    item = authed.post(f"/api/trips/{trip_id}/scan", json={"barcode": "3017620422003"}).json()
    assert (item["item"]["name"], item["item"]["state"]) == ("Nutella 400g", "ready")
    assert item["item"]["lookup"] is None
