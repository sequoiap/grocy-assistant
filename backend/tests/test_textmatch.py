import pytest

from app.services.textmatch import abbreviation_score, normalize_key, upc_matches


@pytest.mark.parametrize(
    ("receipt", "product"),
    [
        ("GV WHL MLK", "Great Value Whole Milk 1 Gallon"),
        ("KS ORG EGGS", "Kirkland Signature Organic Eggs 24ct"),
        ("KRO 2% MILK GAL", "Kroger 2% Reduced Fat Milk Gallon"),
        ("MKS CHKN BRST", "Marketside Chicken Breast"),
        ("PRIVATE SEL CHIPS", "Private Selection Kettle Chips"),
        ("TIDE PODS", "Tide Pods 42ct"),
    ],
)
def test_abbreviations_score_as_matches(receipt, product):
    assert abbreviation_score(receipt, product) >= 0.6


@pytest.mark.parametrize(
    ("receipt", "product"),
    [
        ("GV WHL MLK", "Tide Pods 42ct"),
        ("BANANAS", "Great Value Whole Milk 1 Gallon"),
        ("KS ORG EGGS", "Kirkland Signature Paper Towels"),
        ("PAPER TOWELS", "Toilet Paper"),
    ],
)
def test_unrelated_products_score_low(receipt, product):
    assert abbreviation_score(receipt, product) < 0.55


def test_right_product_beats_a_sibling_from_the_same_brand():
    milk = abbreviation_score("GV WHL MLK", "Great Value Whole Milk 1 Gallon")
    eggs = abbreviation_score("GV WHL MLK", "Great Value Large White Eggs 12ct")
    assert milk > eggs + 0.2


def test_walmart_code_matches_upc_without_check_digit():
    # Receipt prints the UPC zero-padded and without its check digit.
    assert upc_matches("007874235186", "078742351865")
    assert upc_matches("007874235186", "0078742351865")  # same code scanned as EAN-13
    assert upc_matches("078742351865", "078742351865")
    assert not upc_matches("007874235186", "078742370033")
    assert not upc_matches("000000004011", "4011")  # produce PLU: too short to trust
    assert not upc_matches(None, "078742351865")


def test_normalize_key_is_stable_across_spacing_and_punctuation():
    assert normalize_key(" kro  2% milk-gal ") == normalize_key("KRO 2 MILK GAL")
