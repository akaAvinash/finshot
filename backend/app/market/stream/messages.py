"""Frames sent on the owner market stream, matching the MarketSnapshot,
MarketUpdate and MarketStatus payloads in contracts/live-market-stream.asyncapi.yaml."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import model_validator

from app.market.schemas import (
    InstrumentQuote,
    MarketCandle,
    MarketCandles,
    Timeframe,
    UtcDateTime,
    _Wire,
)
from app.market.stream.ticks import FeedState


class MarketSnapshotFrame(_Wire):
    type: Literal["snapshot"] = "snapshot"
    as_of: UtcDateTime
    quote: InstrumentQuote
    history: MarketCandles

    @model_validator(mode="after")
    def _market_history(self) -> Self:
        if self.history.source != "market":
            raise ValueError("stream history must have source market")
        if self.history.instrument_id != self.quote.instrument_id:
            raise ValueError("history must match the quote's instrument")
        return self


class MarketUpdateFrame(_Wire):
    type: Literal["update"] = "update"
    timeframe: Timeframe
    as_of: UtcDateTime
    quote: InstrumentQuote
    candle: MarketCandle


class MarketStatusFrame(_Wire):
    type: Literal["status"] = "status"
    state: FeedState
    sent_at: UtcDateTime


def wire(frame: _Wire) -> dict[str, Any]:
    data: dict[str, Any] = frame.model_dump(mode="json", by_alias=True)
    return data
