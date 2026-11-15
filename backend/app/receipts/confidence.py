"""How much to trust a parse, from checks that are independent of the parser.

The strongest evidence is arithmetic: if the item prices add up to the printed
subtotal to the cent, the parse is almost certainly right, because OCR errors
and missed rows practically never cancel out exactly. Without that check we
cap the score below the AI-fallback threshold (0.6), because a receipt we
cannot reconcile is one we cannot vouch for.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .parsers.base import Outcome

# Scores at or above this mean "trust it"; the orchestrator's default threshold is 0.6.
UNVERIFIED_CAP = 0.55


@dataclass
class Evidence:
    items_sum: float
    reconcile: float | None  # 1.0 exact, partial credit when close, None = no figures
    count_ok: bool | None
    ocr: float
    understood: float
    lines: float
    store: float


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _units(out: Outcome) -> float:
    return sum(1 if line.weight is not None else line.quantity for line in out.lines)


def _reconcile(out: Outcome, items_sum: float, warnings: list[str]) -> float | None:
    targets: list[tuple[float, str]] = []
    if out.subtotal is not None:
        targets.append((out.subtotal, "the receipt subtotal"))
    if out.total is not None and out.tax is not None:
        targets.append((round(out.total - out.tax, 2), "the receipt total minus tax"))
    if out.total is not None and out.tax is None:
        targets.append((out.total, "the receipt total"))
    if not targets:
        warnings.append(
            "Couldn't find a subtotal or total on the receipt, so the item prices "
            "can't be double-checked"
        )
        return None
    diff, target, label = min((abs(items_sum - t), t, label) for t, label in targets)
    if diff <= 0.011:
        if out.subtotal is not None and out.tax is not None and out.total is not None:
            if abs(out.subtotal + out.tax - out.total) > 0.011:
                warnings.append(
                    f"Subtotal {_money(out.subtotal)} plus tax {_money(out.tax)} doesn't "
                    f"equal the total {_money(out.total)}; check the tax amount"
                )
        return 1.0
    warnings.append(f"Item prices add up to {_money(items_sum)} but {label} is {_money(target)}")
    if out.total is not None and out.tax is None and items_sum < out.total:
        # Possibly just a missed tax row; not as damning as a real mismatch.
        return 0.5
    rel = diff / max(abs(target), 1.0)
    return max(0.0, 0.9 - 8 * rel) if diff <= 0.06 else max(0.0, 0.7 - 6 * rel)


def gather(out: Outcome, warnings: list[str]) -> Evidence:
    priced = [line.total_price for line in out.lines if line.total_price is not None]
    items_sum = round(sum(priced), 2)
    reconcile = _reconcile(out, items_sum, warnings)

    count_ok: bool | None = None
    if out.items_sold is not None:
        units = _units(out)
        count_ok = abs(units - out.items_sold) < 0.5
        if not count_ok:
            warnings.append(
                f"The receipt says {out.items_sold:g} items were sold but {units:g} were read"
            )

    scores = out.row_scores or [line.confidence for line in out.lines]
    ocr = statistics.fmean(scores) if scores else 0.0
    if scores and ocr < 0.8:
        warnings.append(
            f"The photo is hard to read (OCR confidence {ocr:.0%}); a sharper, flatter, "
            "evenly lit photo will help"
        )
    understood = out.understood_rows / out.price_rows if out.price_rows else 0.0
    if out.unparsed:
        sample = "; ".join(f'"{t}"' for t in out.unparsed[:3])
        more = f" and {len(out.unparsed) - 3} more" if len(out.unparsed) > 3 else ""
        warnings.append(f"Couldn't make sense of {len(out.unparsed)} row(s): {sample}{more}")
    lines = statistics.fmean(line.confidence for line in out.lines) if out.lines else 0.0
    store = 1.0 if out.store_key else 0.5
    return Evidence(items_sum, reconcile, count_ok, ocr, understood, lines, store)


def score(out: Outcome) -> tuple[float, list[str]]:
    """Overall confidence 0..1 and the warnings explaining it."""
    warnings: list[str] = []
    if not out.lines:
        return 0.0, ["No items were found on this receipt"]
    ev = gather(out, warnings)
    quality = statistics.fmean([ev.ocr, ev.understood, ev.lines])
    if ev.reconcile == 1.0:
        value = 0.8 + 0.2 * quality
        if ev.count_ok is False:
            value -= 0.12
        elif ev.count_ok is True:
            value += 0.03
    elif ev.reconcile is None:
        value = min(UNVERIFIED_CAP, 0.55 * quality + 0.1 * ev.store)
    else:
        value = 0.35 * ev.reconcile + 0.3 * quality + 0.05 * ev.store
        if ev.count_ok is True:
            value += 0.05
        # Close but not exact (a misread cent, a rounding quirk) may still pass.
        value = min(value, 0.62 if ev.reconcile >= 0.85 else UNVERIFIED_CAP)
    if out.store_key is None:
        value -= 0.05
    return round(max(0.0, min(1.0, value)), 3), warnings
