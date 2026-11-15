"""Full pipeline on rendered receipt images: preprocessing, OCR, layout, parsing."""

import pytest

from app.receipts.pipeline import parse_receipt_images

from . import samples, synth

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(synth.find_font() is None, reason="no monospace font to render with"),
]


def test_scanned_walmart_receipt(tmp_path):
    path = synth.simple_scan(samples.WALMART, tmp_path / "walmart.jpg", angle=1.5)
    r = parse_receipt_images([path])
    assert r.store_key == "walmart"
    assert r.method == "ocr"
    assert r.total == 31.90
    codes = {line.item_code for line in r.lines}
    assert {"007874235186", "007874237003", "003700087565"} <= codes
    assert round(sum(line.total_price or 0 for line in r.lines), 2) == r.subtotal == 31.01
    assert r.confidence >= 0.6


def test_phone_photo_of_costco_receipt(tmp_path):
    path = synth.phone_photo(samples.COSTCO, tmp_path / "costco.jpg", seed=3)
    r = parse_receipt_images([path])
    assert r.store_key == "costco"
    assert r.total == 39.05
    assert len(r.lines) == 5
    assert r.confidence >= 0.6


def test_long_receipt_in_two_overlapping_photos(tmp_path):
    rows = samples.SMITHS.splitlines()
    top = synth.simple_scan("\n".join(rows[:13]), tmp_path / "top.jpg", angle=-1.0)
    bottom = synth.simple_scan("\n".join(rows[10:]), tmp_path / "bottom.jpg", angle=1.0, seed=1)
    r = parse_receipt_images([top, bottom])
    assert r.store_key == "kroger"
    assert r.total == 26.18
    # The three rows visible in both photos are counted once.
    assert [line.description for line in r.lines].count("BANANAS") == 1
    assert len(r.lines) == 5


def test_unreadable_file_is_reported_not_raised(tmp_path):
    bad = tmp_path / "not-an-image.jpg"
    bad.write_bytes(b"definitely not a jpeg")
    r = parse_receipt_images([bad])
    assert r.lines == []
    assert r.confidence == 0.0
    assert any("couldn't be read" in w for w in r.warnings)
