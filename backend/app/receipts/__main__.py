"""``python -m app.receipts <photo> [<photo> ...]``: show how a receipt was read.

Prints the reconstructed rows and the parsed result, which is usually enough to
see why a receipt came out wrong (a missed row, a misread price, the wrong store).
Several photos are treated as one long receipt, top to bottom.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .pipeline import parse_receipt_images


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    receipt = parse_receipt_images([Path(a) for a in argv])
    print("--- rows as read " + "-" * 44)
    print(receipt.raw_text)
    print("--- parsed " + "-" * 50)
    print(f"store: {receipt.store_name} ({receipt.store_key})   date: {receipt.purchased_on}")
    print(f"subtotal: {receipt.subtotal}   tax: {receipt.tax}   total: {receipt.total}")
    for line in receipt.lines:
        price = "?" if line.total_price is None else f"{line.total_price:.2f}"
        extra = []
        if line.item_code:
            extra.append(f"code {line.item_code}")
        if line.weight is not None:
            extra.append(f"{line.weight:g} {line.weight_unit}")
        if line.discount:
            extra.append(f"saved {line.discount:.2f}")
        suffix = f"  [{', '.join(extra)}]" if extra else ""
        print(f"  {line.quantity:g} x {line.description:<30} {price:>8}{suffix}")
    print(f"confidence: {receipt.confidence:.2f}")
    for warning in receipt.warnings:
        print(f"  ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
