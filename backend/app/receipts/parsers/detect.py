"""Which store printed this receipt?"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .common import clean

# Kroger Co. banners; all share Kroger's receipt format. (pattern, display name)
KROGER_BANNERS: list[tuple[str, str]] = [
    (r"SMITH'?S(?: FOOD| MARKET|\b)", "Smith's"),
    (r"FRED ?MEYER", "Fred Meyer"),
    (r"KING ?SOOPERS", "King Soopers"),
    (r"RALPHS", "Ralphs"),
    (r"FRY'?S (?:FOOD|MARKET|MARKETPLACE)", "Fry's"),
    (r"\bQFC\b|QUALITY FOOD CENTERS", "QFC"),
    (r"DILLONS", "Dillons"),
    (r"BAKER'?S (?:SUPERMARKET|FOOD)", "Baker's"),
    (r"CITY MARKET", "City Market"),
    (r"GERBES", "Gerbes"),
    (r"\bJAY ?C\b", "Jay C"),
    (r"PAY ?LESS (?:SUPER|FOOD)", "Pay Less"),
    (r"MARIANO'?S", "Mariano's"),
    (r"PICK ?'?N'? ?SAVE", "Pick 'n Save"),
    (r"METRO MARKET", "Metro Market"),
    (r"HARRIS ?TEETER", "Harris Teeter"),
    (r"FOOD ?4 ?LESS", "Food 4 Less"),
    (r"FOODS ?CO\b", "Foods Co"),
    (r"\bKROGER\b(?! SAVINGS| PLUS| BRAND| MILK| BREAD)", "Kroger"),
]
# Lines that only Kroger-family receipts print, for when the banner is unreadable.
_KROGER_HINTS = re.compile(
    r"KROGER (?:SAVINGS|PLUS)|PLUS CARD|FUEL POINTS|\bSC KROGER|\*{2,} BALANCE|"
    r"KROGER\.COM|ANNUAL CARD SAVINGS"
)
_WALMART = re.compile(r"WA[LI][\s\-*•.]?MART|SAVE MONEY\.? LIVE BETTER|WALMART\.COM")
_COSTCO = re.compile(r"COSTCO|WHOLESALE\b.*#|KIRKLAND SIGNATURE")

# Other common US grocers, so the generic parser can still name the store.
OTHER_STORES = [
    "Target",
    "Trader Joe's",
    "Whole Foods Market",
    "Aldi",
    "Safeway",
    "Albertsons",
    "Sprouts Farmers Market",
    "WinCo Foods",
    "Publix",
    "H-E-B",
    "Meijer",
    "Hy-Vee",
    "Sam's Club",
    "Harmons",
    "Lidl",
    "Walgreens",
    "CVS",
    "Natural Grocers",
    "Macey's",
    "Wegmans",
    "Giant Eagle",
    "Food Lion",
    "Stop & Shop",
    "Vons",
    "Jewel-Osco",
    "Shaw's",
    "Acme Markets",
    "Winn-Dixie",
    "Hannaford",
    "Price Chopper",
    "ShopRite",
    "Market Basket",
    "Grocery Outlet",
    "Dollar General",
    "Family Dollar",
    "Smart & Final",
    "Stater Bros",
    "Food City",
    "Ingles",
    "Piggly Wiggly",
    "Save Mart",
    "Raley's",
    "Lunds & Byerlys",
    "Schnucks",
    "Dierbergs",
    "Fareway",
    "Weis Markets",
    "BJ's",
]
_HEADER_SKIP = re.compile(
    r"\d{3}.*\d{4}|\b(?:ST|AVE|RD|BLVD|DR|HWY|WAY|LN|PKWY|SUITE|STE)\b|WELCOME|RECEIPT|"
    r"STORE|MANAGER|OPEN|HOURS|PHONE|THANK|CUSTOMER|COPY"
)


@dataclass
class StoreGuess:
    key: str | None  # walmart | costco | kroger | slug | None
    name: str | None
    certain: bool  # found by name rather than inferred


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def _letters(text: str) -> str:
    return re.sub(r"[^A-Z& ]", "", text.replace("'", "")).strip()


# Digits OCR substitutes for letters in words like "C0STCO" or "WAL-MART".
_LETTERIZE = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I"})


def _letterize(text: str) -> str:
    return re.sub(
        r"[A-Z0-9|]+",
        lambda m: m.group().translate(_LETTERIZE) if re.search(r"[A-Z]", m.group()) else m.group(),
        text,
    )


def detect_store(texts: list[str]) -> StoreGuess:
    rows = [_letterize(clean(t)) for t in texts]
    body = "\n".join(rows)
    header = rows[:10]
    if _WALMART.search(body) or any(fuzz.partial_ratio("WALMART", h) >= 90 for h in header):
        return StoreGuess("walmart", "Walmart", True)
    if _COSTCO.search(body) or any(fuzz.partial_ratio("COSTCO", h) >= 90 for h in header):
        return StoreGuess("costco", "Costco", True)
    for pattern, name in KROGER_BANNERS:
        if re.search(pattern, body):
            return StoreGuess("kroger", name, True)
    if _KROGER_HINTS.search(body):
        return StoreGuess("kroger", "Kroger", False)
    for name in OTHER_STORES:
        target = _letters(name.upper())
        if len(target) >= 4 and any(
            fuzz.partial_ratio(target, _letters(h)) >= 92 for h in header if len(h) >= 3
        ):
            return StoreGuess(slugify(name), name, True)
        if len(target) < 4 and any(re.search(rf"\b{re.escape(target)}\b", h) for h in header):
            return StoreGuess(slugify(name), name, True)
    if _walmart_shaped(rows):
        return StoreGuess("walmart", "Walmart", False)
    name = _header_name(header)
    return StoreGuess(slugify(name) if name else None, name, False)


def _walmart_shaped(rows: list[str]) -> bool:
    """Several '<desc> <12 digits> <flag> <price> <tax>' rows: Walmart (or Sam's)."""
    shaped = sum(1 for r in rows if re.search(r"\b\d{12}\s?[A-Z]{0,2}\s+\d+\.\d{2}", r))
    return shaped >= 3


def _header_name(header: list[str]) -> str | None:
    """Best guess at a store name: the first wordy line at the top."""
    for text in header[:4]:
        letters = _letters(text)
        if len(letters) < 4 or len(letters) > 32 or _HEADER_SKIP.search(text):
            continue
        if sum(c.isalpha() for c in text) < 0.7 * len(text.replace(" ", "")):
            continue
        return letters.title()
    return None
