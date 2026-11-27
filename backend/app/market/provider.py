"""The market data provider interface.

Routes depend on this protocol only. A provider supplies reference data, a
dated quote snapshot and candle history; search, input validation and error
mapping live in the API layer so every provider behaves the same way.

Providers signal an outage by raising `MarketDataUnavailableError`. The API
also treats a timeout or a response that fails model validation as
unavailable (503), so a broken provider never returns bad data."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.market.schemas import Instrument, MarketCandles, MarketOverview, Source, Timeframe


class MarketDataUnavailableError(Exception):
    """The provider cannot serve market data right now."""


@runtime_checkable
class MarketDataProvider(Protocol):
    source: Source
    """Where the data comes from. Reported as `source` on the instrument list."""

    async def list_instruments(self) -> Sequence[Instrument]:
        """The whole instrument catalog, in a stable order."""
        ...

    async def get_overview(self) -> MarketOverview:
        """A dated quote and exchange-session snapshot for the catalog."""
        ...

    async def get_candles(self, instrument_id: str, timeframe: Timeframe) -> MarketCandles | None:
        """Candle history for a catalog instrument. Returns None when the
        instrument is not in the catalog; an empty `candles` list when it is
        but has no history for this timeframe."""
        ...


class DisabledMarketDataProvider:
    """Serves nothing: every call is unavailable. Selected by
    MARKET_DATA_PROVIDER=disabled."""

    source: Source = "demo"

    async def list_instruments(self) -> Sequence[Instrument]:
        raise MarketDataUnavailableError("market data is disabled")

    async def get_overview(self) -> MarketOverview:
        raise MarketDataUnavailableError("market data is disabled")

    async def get_candles(self, instrument_id: str, timeframe: Timeframe) -> MarketCandles | None:
        raise MarketDataUnavailableError("market data is disabled")
