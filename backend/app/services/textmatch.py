"""Scoring how well a terse receipt description ("GV WHL MLK GAL") fits a product
name ("Great Value Whole Milk, 1 Gallon").

Receipts abbreviate by dropping vowels, truncating words and using brand
initials, so plain edit distance does poorly. Each receipt token is instead
matched against the product's words using abbreviation-aware rules.
"""

from __future__ import annotations

import re
from functools import lru_cache

from rapidfuzz import fuzz

_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")

# Abbreviations that subsequence matching can't recover on its own.
_EXPANSIONS = {
    "gv": "great value",
    "ks": "kirkland signature",
    "kro": "kroger",
    "kr": "kroger",
    "mm": "members mark",
    "ps": "private selection",
    "st": "simple truth",
    "sto": "simple truth organic",
    "eq": "equate",
    "mks": "marketside",
    "org": "organic",
    "w": "with",
    "bnls": "boneless",
    "sknls": "skinless",
    "ched": "cheddar",
    "van": "vanilla",
    "choc": "chocolate",
    "pnt": "peanut",
    "btr": "butter",
    "tp": "toilet paper",
    "pt": "paper towels",
    "oj": "orange juice",
    "evoo": "extra virgin olive oil",
}

_UNIT_TOKENS = {"oz", "lb", "lbs", "ct", "pk", "gal", "qt", "pt", "fl", "ml", "kg", "g", "l", "ea"}


def normalize_key(text: str) -> str:
    """Stable key for learned text mappings: 'KRO 2% MILK ' -> 'KRO 2 MILK'."""
    return " ".join(re.findall(r"[A-Z0-9]+", text.upper()))


@lru_cache(maxsize=4096)
def tokenize(text: str) -> tuple[str, ...]:
    # Split digit/letter runs so "24CT" and "24 ct" look the same.
    return tuple(_TOKEN_RE.findall(text.lower().replace("'", "")))


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _token_score(r: str, p: str) -> float:
    if r == p:
        return 1.0
    if r[0].isdigit() or p[0].isdigit():
        return 0.0
    if len(r) >= 2 and p.startswith(r):
        return 0.9
    if len(r) >= 2 and r[0] == p[0] and len(p) > len(r) and _is_subsequence(r, p):
        return 0.85 if len(r) >= 3 else 0.6
    if len(r) >= 4 and len(p) >= 4:
        ratio = fuzz.ratio(r, p)
        if ratio >= 80:
            return 0.7 * ratio / 100
    return 0.0


def _weight(token: str) -> float:
    if token[0].isdigit() or token in _UNIT_TOKENS:
        return 1.0
    return float(min(len(token), 6))


def abbreviation_score(receipt_text: str, product_name: str) -> float:
    """0..1: how plausibly `receipt_text` is an abbreviation of `product_name`."""
    r_tokens = [t for t in tokenize(receipt_text) if len(t) > 1 or t.isdigit()]
    p_tokens = list(tokenize(product_name))
    if not r_tokens or not p_tokens:
        return 0.0

    initials = "".join(t[0] for t in p_tokens if t[0].isalpha())
    covered_p: set[int] = set()
    total = 0.0
    weight_sum = 0.0
    for r in r_tokens:
        w = _weight(r)
        weight_sum += w
        best, best_idx = 0.0, None
        for i, p in enumerate(p_tokens):
            s = _token_score(r, p)
            if s > best:
                best, best_idx = s, [i]
        expansion = _EXPANSIONS.get(r)
        if expansion and best < 0.95:
            words = expansion.split()
            hits = [i for i, p in enumerate(p_tokens) if p in words]
            if len({p_tokens[i] for i in hits}) == len(words):
                best, best_idx = 0.95, hits
        if best < 0.75 and 2 <= len(r) <= 4 and r.isalpha() and r in initials:
            start = initials.index(r)
            best, best_idx = 0.75, list(range(start, start + len(r)))
        if best_idx:
            covered_p.update(best_idx)
        total += w * best

    receipt_coverage = total / weight_sum
    p_weights = [_weight(p) for p in p_tokens]
    product_coverage = sum(p_weights[i] for i in covered_p if i < len(p_weights)) / sum(p_weights)
    return round(0.8 * receipt_coverage + 0.2 * product_coverage, 4)


def best_name_score(receipt_text: str, names: list[str]) -> float:
    return max((abbreviation_score(receipt_text, n) for n in names if n), default=0.0)


def upc_matches(item_code: str | None, barcode: str | None) -> bool:
    """Does a receipt's item number encode this barcode?

    Walmart prints the UPC zero-padded to 12 digits *without* its check digit;
    other stores print the full UPC/EAN. Compare with leading zeros stripped,
    both with and without the barcode's check digit.
    """
    if not item_code or not barcode:
        return False
    code = re.sub(r"\D", "", item_code).lstrip("0")
    bc = re.sub(r"\D", "", barcode).lstrip("0")
    if len(code) < 7 or len(bc) < 7:
        return False
    return code == bc or code == bc[:-1]
