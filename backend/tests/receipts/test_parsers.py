"""Parser tests on reconstructed-row text (what the layout step hands over)."""

import pytest

from app.receipts.pipeline import parse_text

from . import samples

THRESHOLD = 0.6  # Config.ocr_confidence_threshold: below this the AI fallback is consulted


def by_desc(receipt):
    return {line.description: line for line in receipt.lines}


@pytest.mark.parametrize("text", [samples.WALMART, samples.WALMART_NOISY], ids=["clean", "noisy"])
def test_walmart(text):
    r = parse_text(text)
    assert (r.store_key, r.store_name) == ("walmart", "Walmart")
    assert r.purchased_on == "2026-11-03"
    assert (r.subtotal, r.tax, r.total) == (31.01, 0.89, 31.90)
    assert r.confidence >= THRESHOLD

    lines = by_desc(r)
    # The voided Cheerios is gone; everything else is there once.
    assert list(lines) == [
        "GV WHL MLK",
        "GV LG WHT EGG",
        "BANANAS",
        "GV SPRING WTR",
        "TIDE PODS",
        "MKS CHKN BRST",
    ]
    # Item codes survive exactly as printed (the matcher compares them to scanned UPCs).
    assert lines["GV WHL MLK"].item_code == "007874235186"
    assert lines["GV LG WHT EGG"].item_code == "007874237003"
    assert lines["GV WHL MLK"].total_price == 3.48

    water = lines["GV SPRING WTR"]
    assert (water.quantity, water.unit_price, water.total_price) == (2, 0.98, 1.96)

    bananas = lines["BANANAS"]
    assert (bananas.quantity, bananas.weight, bananas.weight_unit) == (1, 1.23, "lb")
    assert bananas.total_price == 0.71

    assert round(sum(line.total_price for line in r.lines), 2) == r.subtotal


def test_walmart_blurry_is_not_trusted():
    r = parse_text(samples.WALMART_BLURRY)
    assert r.store_key == "walmart"
    assert r.confidence < THRESHOLD
    assert any("add up to" in w for w in r.warnings)
    assert any("Couldn't read a price" in w for w in r.warnings)


@pytest.mark.parametrize("text", [samples.COSTCO, samples.COSTCO_NOISY], ids=["clean", "noisy"])
def test_costco(text):
    r = parse_text(text)
    assert (r.store_key, r.store_name) == ("costco", "Costco")
    assert r.purchased_on == "2026-11-03"
    assert (r.subtotal, r.tax, r.total) == (37.95, 1.10, 39.05)
    assert r.confidence >= THRESHOLD

    assert [(line.item_code, line.description) for line in r.lines] == [
        ("1234567", "KS ORG EGGS"),
        ("512515", "KS WATER 40PK"),
        ("968123", "ORG BANANAS"),
        ("1675112", "PAPER TOWELS"),
        ("1234567", "KS ORG EGGS"),
    ]
    water, towels = r.lines[1], r.lines[3]
    # Instant savings are attributed by item number, not by position.
    assert (water.discount, water.total_price) == (1.00, 3.99)
    assert (towels.discount, towels.total_price) == (4.00, 15.99)
    assert r.lines[0].discount is None
    assert round(sum(line.total_price for line in r.lines), 2) == r.subtotal


def test_kroger_family_smiths():
    r = parse_text(samples.SMITHS)
    assert (r.store_key, r.store_name) == ("kroger", "Smith's")
    assert r.purchased_on == "2026-11-03"
    assert (r.tax, r.total) == (0.81, 26.18)
    assert r.confidence >= THRESHOLD

    lines = by_desc(r)
    assert list(lines) == [
        "KRO 2% MILK GAL",
        "PRIVATE SEL CHIPS",
        "BANANAS",
        "SIMPLE TRUTH ORG SPINACH",
        "TIDE DETERGENT",
    ]
    milk = lines["KRO 2% MILK GAL"]
    assert (milk.discount, milk.total_price) == (0.50, 2.79)
    # "2 @ 2/5.00" sits above its item.
    chips = lines["PRIVATE SEL CHIPS"]
    assert (chips.quantity, chips.unit_price, chips.total_price) == (2, 2.50, 5.00)
    # The weight row sits above its item and the WT marker is dropped.
    bananas = lines["BANANAS"]
    assert (bananas.weight, bananas.weight_unit, bananas.total_price) == (2.31, "lb", 4.60)
    # Savings rows count with or without a trailing minus.
    assert lines["SIMPLE TRUTH ORG SPINACH"].total_price == 2.99
    assert lines["TIDE DETERGENT"].total_price == 9.99
    assert round(sum(line.total_price for line in r.lines) + r.tax, 2) == r.total


def test_kroger_family_fred_meyer_noisy_with_void():
    r = parse_text(samples.FRED_MEYER_NOISY)
    assert (r.store_key, r.store_name) == ("kroger", "Fred Meyer")
    assert r.purchased_on == "2026-11-04"
    assert r.confidence >= THRESHOLD
    assert [(line.description, line.total_price) for line in r.lines] == [
        ("KRO 2% MILK GAL", 2.79),
        ("PRIVATE SEL CHIPS", 2.50),  # rung up twice, one voided
        ("BANANAS", 4.60),
    ]


def test_generic_store():
    r = parse_text(samples.TRADER_JOES)
    assert (r.store_key, r.store_name) == ("trader-joes", "Trader Joe's")
    assert r.purchased_on == "2026-11-03"
    assert (r.subtotal, r.total) == (14.60, 14.60)
    assert r.confidence >= THRESHOLD
    lines = by_desc(r)
    assert lines["ORGANIC BANANAS"].quantity == 3
    assert lines["SPARKLING WATER"].quantity == 2
    assert lines["SPARKLING WATER"].total_price == 3.98
    # Payment rows never become items.
    assert not any("VISA" in d or "CHANGE" in d for d in lines)


def test_empty_and_garbage_input():
    assert parse_text("").confidence == 0.0
    r = parse_text("lorem ipsum\nnothing to see here\n")
    assert r.lines == []
    assert r.confidence < THRESHOLD
