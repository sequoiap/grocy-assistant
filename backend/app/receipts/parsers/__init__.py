"""Store detection and per-store parsers."""

from __future__ import annotations

from ..layout import Row
from .base import BaseParser, Outcome
from .costco import CostcoParser
from .detect import StoreGuess, detect_store
from .generic import GenericParser
from .kroger import KrogerParser
from .walmart import WalmartParser

PARSERS: dict[str, type[BaseParser]] = {
    "walmart": WalmartParser,
    "costco": CostcoParser,
    "kroger": KrogerParser,
}


def parse_rows(rows: list[Row]) -> Outcome:
    guess = detect_store([r.text for r in rows])
    parser_cls = PARSERS.get(guess.key or "", GenericParser)
    outcome = parser_cls(rows, guess.name).parse()
    outcome.store_key = guess.key
    outcome.store_name = guess.name
    if guess.key in PARSERS and not guess.certain:
        outcome.warnings.append(
            f"The store name wasn't readable; guessed {guess.name} from the receipt layout"
        )
    return outcome


__all__ = ["Outcome", "StoreGuess", "detect_store", "parse_rows"]
