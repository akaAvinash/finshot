"""Instrument search. Same rules as frontend/src/lib/market/search.ts, so the
demo client and the API rank results identically.

Matching ignores case and every character other than A-Z and 0-9, so
"nifty 50", "NIFTY50" and "nse:nifty50" all find NSE:NIFTY50. Ranking:
0 exact symbol/ID/alias, 1 symbol/ID/alias prefix, 2 name prefix,
3 substring anywhere. Ties keep catalog order."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.market.schemas import Instrument

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalize(value: str) -> str:
    return _NON_ALNUM.sub("", value.upper())


def _score(instrument: Instrument, term: str) -> int | None:
    symbol = normalize(instrument.symbol)
    identifiers = [normalize(value) for value in (instrument.id, *instrument.aliases)]
    name = normalize(instrument.name)
    if symbol == term or term in identifiers:
        return 0
    if symbol.startswith(term) or any(value.startswith(term) for value in identifiers):
        return 1
    if name.startswith(term):
        return 2
    if any(term in value for value in (symbol, name, *identifiers)):
        return 3
    return None


def search_instruments(instruments: Sequence[Instrument], query: str | None) -> list[Instrument]:
    """No query, or a blank one, returns the whole catalog. A query with no
    letters or digits (for example "!!") matches nothing."""
    if query is None or not query.strip():
        return list(instruments)
    term = normalize(query)
    if not term:
        return []
    ranked: list[tuple[int, int, Instrument]] = []
    for index, item in enumerate(instruments):
        score = _score(item, term)
        if score is not None:
            ranked.append((score, index, item))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in ranked]
