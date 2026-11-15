"""Text helpers shared by the store parsers.

Everything here works on one reconstructed row at a time and is deliberately
forgiving: OCR mixes up O/0, l/1, S/5 and B/8 inside numbers, drops or doubles
spaces, reads a decimal point as a comma, and glues a tax flag onto a price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

# Characters OCR commonly returns in place of a digit (row text is upper-cased).
_CONFUSABLE = "OQDILJ|SBZ"
_DIGIT_MAP = str.maketrans(
    {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "J": "1",
        "|": "1",
        "S": "5",
        "B": "8",
        "Z": "2",
    }
)
DC = rf"[0-9{re.escape(_CONFUSABLE)}]"
# A money amount: up to 4 integer digits, a decimal separator, exactly 2 decimals.
AMOUNT = rf"(?:\$\s?)?{DC}{{1,4}}\s?[.,]\s?{DC}{{2}}"

_AMOUNT_RE = re.compile(rf"(?<![0-9A-Z.,]){AMOUNT}(?![0-9])")
_TRAILING_RE = re.compile(
    rf"^(?P<head>.*?)(?:(?<=\s)|^)(?P<neg1>-\s?)?(?P<amt>{AMOUNT})"
    r"\s*(?P<neg2>-)?\s*(?P<flag>[A-Z]{1,2}|\*)?\s*$"
)
_FLAG_NOT_TAX = {"LB", "OZ", "KG", "EA", "CT"}


def fix_word_zeros(text: str) -> str:
    """'KS 0RG EGGS' -> 'KS ORG EGGS': a lone 0 inside a word is the letter O."""
    return re.sub(r"(?<![0-9.,])0(?=[A-Z])|(?<=[A-Z])0(?![0-9.,])", "O", text)


def clean(text: str) -> str:
    """Upper-case, unify dashes/quotes and collapse runs of spaces."""
    text = text.upper().replace("—", "-").replace("–", "-").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def fix_digits(token: str) -> str | None:
    """Turn an OCR'd numeric token into digits, or None if it isn't numeric enough."""
    core = token.replace("$", "").replace(" ", "")
    letters = sum(1 for c in core if c in _CONFUSABLE)
    digits = sum(1 for c in core if c.isdigit())
    if digits == 0 or letters > digits:
        return None
    return core.translate(_DIGIT_MAP)


def to_amount(token: str) -> float | None:
    fixed = fix_digits(token)
    if fixed is None:
        return None
    fixed = fixed.replace(",", ".")
    try:
        return round(float(fixed), 2)
    except ValueError:
        return None


def to_number(token: str) -> float | None:
    fixed = fix_digits(token)
    try:
        return float(fixed.replace(",", ".")) if fixed else None
    except ValueError:
        return None


@dataclass
class Trailing:
    head: str  # text before the amount
    amount: float
    negative: bool
    flag: str | None  # tax / food-stamp flag printed after the price


def trailing_amount(text: str) -> Trailing | None:
    """Split ``'GV WHL MLK 007874235186 F 3.48 N'`` into head + price + flag."""
    m = _TRAILING_RE.match(text)
    if not m:
        return None
    flag = m.group("flag")
    if flag in _FLAG_NOT_TAX:
        return None
    amount = to_amount(m.group("amt"))
    if amount is None:
        return None
    negative = bool(m.group("neg1") or m.group("neg2"))
    return Trailing(m.group("head").strip(), amount, negative, flag)


def has_amount(text: str) -> bool:
    return any(to_amount(m.group(0)) is not None for m in _AMOUNT_RE.finditer(text))


def amounts(text: str) -> list[float]:
    found = (to_amount(m.group(0)) for m in _AMOUNT_RE.finditer(text))
    return [a for a in found if a is not None]


# --- quantity and weight lines ---------------------------------------------------

_UNIT = r"(?P<{name}>LBS?|1B|IB|KG|OZ|G)"
_WEIGHT_RE = re.compile(
    rf"(?P<w>{DC}{{1,3}}[.,]{DC}{{1,3}})\s*{_UNIT.format(name='u')}\.?\s*@\s*"
    rf"(?:(?P<per>{DC}{{1,2}})\s*[A-Z0-9]{{0,3}}\s*/\s*)?(?P<price>{AMOUNT})"
    rf"(?:\s*/\s*{_UNIT.format(name='u2')})?"
)
_QTY_RE = re.compile(
    rf"^(?:QTY\s*)?(?P<n>\d{{1,3}})\s*(?:@|AT|X)\s*(?:(?P<k>\d{{1,2}})\s*(?:/|FOR)\s*)?"
    rf"(?P<price>{AMOUNT})"
)


def _unit(raw: str | None) -> str:
    if raw is None:
        return "lb"
    raw = raw.rstrip("S")
    return {"1B": "lb", "IB": "lb", "LB": "lb"}.get(raw, raw.lower())


@dataclass
class WeightInfo:
    weight: float
    unit: str
    unit_price: float  # per one weight unit
    total: float | None  # extended price printed on the same row, if any


def parse_weight(text: str) -> WeightInfo | None:
    """``'1.23 LB @ 1 LB /0.58  0.71'`` or ``'2.31 LB @ 1.99 /LB'``."""
    m = _WEIGHT_RE.search(text)
    if not m:
        return None
    weight = to_number(m.group("w"))
    price = to_amount(m.group("price"))
    if weight is None or price is None or weight <= 0:
        return None
    per = fix_digits(m.group("per")) if m.group("per") else None
    if per and per.isdigit() and int(per) > 1:
        price = price / int(per)
    rest = text[m.end() :]
    tail = trailing_amount(rest) if rest.strip() else None
    return WeightInfo(
        round(weight, 3), _unit(m.group("u")), round(price, 4), tail.amount if tail else None
    )


@dataclass
class QtyInfo:
    quantity: int
    unit_price: float
    total: float | None


def parse_qty(text: str) -> QtyInfo | None:
    """``'2 AT 1 FOR 0.98  1.96'`` (Walmart) or ``'2 @ 2/5.00'`` (Kroger)."""
    m = _QTY_RE.match(text)
    if not m:
        return None
    n = int(m.group("n"))
    price = to_amount(m.group("price"))
    if price is None or not 1 <= n <= 200:
        return None
    k = int(m.group("k")) if m.group("k") else 1
    unit = price / k if k else price
    rest = text[m.end() :]
    tail = trailing_amount(rest) if rest.strip() else None
    return QtyInfo(n, round(unit, 4), tail.amount if tail else None)


# --- summary rows (subtotal, tax, total, item count) --------------------------------


def _letters(text: str) -> str:
    """Letters-only form of a row's label, with in-word OCR digits fixed."""
    head = re.split(rf"\s(?:-?{AMOUNT})", text, maxsplit=1)[0]
    head = re.sub(r"(?<=[A-Z])0|0(?=[A-Z])", "O", head)
    head = re.sub(r"(?<=[A-Z])1|1(?=[A-Z])", "I", head)
    return re.sub(r"[^A-Z# ]", " ", head)


def _starts_like(words: list[str], target: str, threshold: float = 80) -> bool:
    if not words:
        return False
    n = len(target.split())
    candidate = " ".join(words[:n])
    if candidate == target:
        return True
    return len(target) >= 5 and fuzz.ratio(candidate, target) >= threshold


_NOT_TOTAL = (
    "SAVING",
    "COUPON",
    "NUMBER",
    "ITEMS",
    "DISCOUNT",
    "TAX",
    "TENDER",
    "POINTS",
    "SAVED",
    "PURCHASE",
)


_ITEM_COUNT = re.compile(r"ITEMS?\s*SOLD|NUMBER OF ITEMS|#\s*ITEMS|ITEM COUNT|ITEMS IN TRANSACTION")


@dataclass
class Summary:
    kind: str  # subtotal | tax | total_tax | total | items_sold | savings
    value: float


def summary(text: str) -> Summary | None:
    """Classify subtotal / tax / total / item-count / savings-summary rows."""
    label = _letters(text)
    words = label.split()
    joined = " ".join(words)
    if _ITEM_COUNT.search(joined):
        nums = re.findall(r"\d+", text.split("SOLD")[-1] if "SOLD" in text else text)
        return Summary("items_sold", float(nums[-1])) if nums else None
    tail = trailing_amount(text)
    if tail is None:
        return None
    if _starts_like(words, "SUBTOTAL") or _starts_like(words, "SUB TOTAL"):
        return Summary("subtotal", tail.amount)
    # "TAX 1 6.850 %" can come back as "TAXI"; Costco prints "A 7.25% TAX".
    if re.match(r"^(?:[A-Z] )?(?:SALES |STATE |LOCAL |COUNTY |CITY |TOTAL )?TAXI?\b", joined):
        return Summary("total_tax" if joined.startswith("TOTAL") else "tax", tail.amount)
    if re.match(r"^(?:INSTANT SAVINGS|TOTAL SAVINGS|YOU SAVED|TOTAL COUPONS)", joined):
        return Summary("savings", tail.amount)
    if any(w in joined for w in _NOT_TOTAL) or len(words) > 3:
        return None
    if re.match(r"^(?:BALANCE DUE|AMOUNT DUE|TOTAL DUE|GRAND TOTAL|BAL\b)", joined):
        return Summary("total", tail.amount)
    if _starts_like(words[:1], "TOTAL") or _starts_like(words[:1], "BALANCE"):
        return Summary("total", tail.amount)
    return None


# --- rows that are never items ------------------------------------------------------

_NOISE_RE = re.compile(
    r"\b(?:VISA|MASTERCARD|MASTER CARD|AMEX|AMERICAN EXPRESS|DISCOVER|DEBIT|CREDIT|"
    r"CASH(?! ?EW)|TEND(?:ER(?:ED)?)?|CHANGE(?: DUE)?|EBT|SNAP|GIFT ?CARD|ACCOUNT|ACCT|"
    r"APPROVAL|APPR|AUTH(?:ORIZATION)?|REF(?:ERENCE)?\s*#|TERMINAL|TRANSACTION|TRANS\s*(?:ID|#)|"
    r"AID\s*:?\s*A0|PAYMENT|CARD\s*#|CHIP READ|CONTACTLESS|PIN VERIFIED|SIGNATURE|FUEL|"
    r"POINTS|REWARDS?|SURVEY|FEEDBACK|WWW|HTTPS?|THANK|CASHIER|STORE\s*#|ST\s?#|OP\s?#|"
    r"TE\s?#|TR\s?#|TC\s?#|REG(?:ISTER)?\s*#|MANAGER|VALIDATION|BALANCE REMAINING|"
    r"REMAINING BAL|SAVINGS TODAY|ANNUAL|YEAR TO DATE|MEMBERSHIP|MEMBER\s*#?\s*\d|"
    r"NETWORK ID|BATCH)(?:\b|(?<=#))"
)


def is_noise(text: str) -> bool:
    return bool(_NOISE_RE.search(text))


# --- dates --------------------------------------------------------------------------

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})\s?[/\-.]\s?(\d{1,2})\s?[/\-.]\s?(\d{4}|\d{2})(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)")
_TEXT_DATE = re.compile(r"\b([A-Z]{3})[A-Z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b")
_TIME = re.compile(r"\d{1,2}:\d{2}")


def _valid(y: int, m: int, d: int) -> str | None:
    if not (1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2099):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def find_date(texts: list[str]) -> str | None:
    """First plausible purchase date; rows that also carry a time win."""
    candidates: list[tuple[int, str]] = []
    for text in texts:
        for m in _ISO_DATE.finditer(text):
            if iso := _valid(int(m[1]), int(m[2]), int(m[3])):
                candidates.append((0 if _TIME.search(text) else 1, iso))
        for m in _NUMERIC_DATE.finditer(text):
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            if iso := _valid(year, int(m[1]), int(m[2])):
                candidates.append((0 if _TIME.search(text) else 1, iso))
        for m in _TEXT_DATE.finditer(text):
            if m[1] in _MONTHS and (iso := _valid(int(m[3]), _MONTHS[m[1]], int(m[2]))):
                candidates.append((0 if _TIME.search(text) else 1, iso))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]
