"""Market data models. Field names are camelCase on the wire, matching the
Markets schemas in contracts/openapi.yaml.

The models also enforce the invariants the API promises, so a provider that
returns bad data fails validation instead of reaching a client:
non-negative prices and volumes, OHLC consistency, UTC timestamps, and
candles in ascending order with distinct timestamps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

INSTRUMENT_ID_PATTERN = r"^NSE:[A-Z0-9_.&-]+$"
SEARCH_QUERY_MAX_LENGTH = 100

Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "1D"]
TIMEFRAMES: tuple[Timeframe, ...] = ("1m", "5m", "15m", "30m", "1h", "1D")
Source = Literal["demo", "market"]
Freshness = Literal["fresh", "stale"]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_require_utc)]
InstrumentId = Annotated[str, Field(pattern=INSTRUMENT_ID_PATTERN)]
Price = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Volume = Annotated[int | None, Field(ge=0)]


class _Wire(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )


class Instrument(_Wire):
    id: InstrumentId
    symbol: str = Field(min_length=1)
    name: str = Field(min_length=1)
    exchange: Literal["NSE"] = "NSE"
    kind: Literal["index", "equity"]
    currency: Literal["INR"] = "INR"
    aliases: tuple[str, ...] = ()


class InstrumentList(_Wire):
    instruments: list[Instrument]


class InstrumentQuote(_Wire):
    instrument_id: InstrumentId
    price: Price
    previous_close: Price
    change: float = Field(allow_inf_nan=False)
    change_percent: float = Field(allow_inf_nan=False)
    open: Price
    high: Price
    low: Price
    volume: Volume
    trend: Literal["up", "down", "flat"]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not (self.low <= min(self.open, self.price) and self.high >= max(self.open, self.price)):
            raise ValueError("quote high/low must bound open and price")
        expected = "up" if self.change > 0 else "down" if self.change < 0 else "flat"
        if self.trend != expected:
            raise ValueError("trend must match the sign of change")
        return self


class MarketSession(_Wire):
    exchange: Literal["NSE"] = "NSE"
    status: Literal["preopen", "open", "closed"]
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    opens_at: UtcDateTime
    closes_at: UtcDateTime

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.opens_at >= self.closes_at:
            raise ValueError("session must open before it closes")
        return self


class MarketOverview(_Wire):
    source: Source
    as_of: UtcDateTime
    session: MarketSession
    quotes: list[InstrumentQuote]


class MarketCandle(_Wire):
    time: UtcDateTime
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Volume

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError("candle high/low must bound open and close")
        return self


class MarketCandles(_Wire):
    instrument_id: InstrumentId
    timeframe: Timeframe
    source: Source
    as_of: UtcDateTime
    freshness: Freshness
    candles: list[MarketCandle]

    @model_validator(mode="after")
    def _ascending_unique(self) -> Self:
        times = [candle.time for candle in self.candles]
        if any(later <= earlier for earlier, later in pairwise(times)):
            raise ValueError("candles must be in ascending order with distinct timestamps")
        return self
