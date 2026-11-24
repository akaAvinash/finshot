"""/api/v1/market/* read-only endpoints, as specified in contracts/openapi.yaml.

No authentication (the contract declares none for Markets). Errors use the
shared envelope: 400 INVALID_REQUEST, 404 UNKNOWN_INSTRUMENT,
503 MARKET_DATA_UNAVAILABLE."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import ValidationError

from app.core.errors import ApiError
from app.market.provider import MarketDataProvider, MarketDataUnavailableError
from app.market.schemas import (
    INSTRUMENT_ID_PATTERN,
    SEARCH_QUERY_MAX_LENGTH,
    InstrumentList,
    MarketCandles,
    MarketOverview,
    Timeframe,
)
from app.market.search import search_instruments

router = APIRouter(prefix="/api/v1/market", tags=["market"])
logger = structlog.get_logger(__name__)

_ERROR_RESPONSES: dict[int | str, dict[str, str]] = {
    400: {"description": "The request parameters are invalid."},
    503: {"description": "The requested market data is temporarily unavailable."},
}


def get_market_provider(request: Request) -> MarketDataProvider:
    provider: MarketDataProvider = request.app.state.market_provider
    return provider


Provider = Annotated[MarketDataProvider, Depends(get_market_provider)]


def _unavailable() -> ApiError:
    return ApiError(
        503, "MARKET_DATA_UNAVAILABLE", "Market data is temporarily unavailable. Try again shortly."
    )


async def _call[T](request: Request, operation: str, awaitable: Awaitable[T]) -> T:
    """Run a provider call. An outage, a timeout or data that fails the
    response models' validation all become 503; details go to the log only."""
    timeout = request.app.state.settings.market_data_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            return await awaitable
    except MarketDataUnavailableError:
        logger.warning("market_data_unavailable", operation=operation, reason="provider")
    except TimeoutError:
        logger.warning("market_data_unavailable", operation=operation, reason="timeout")
    except ValidationError as exc:
        logger.error("market_data_invalid", operation=operation, error_count=exc.error_count())
    raise _unavailable()


@router.get(
    "/instruments",
    response_model=InstrumentList,
    operation_id="getMarketInstruments",
    responses=_ERROR_RESPONSES,
)
async def list_instruments(
    request: Request,
    provider: Provider,
    query: Annotated[
        str | None,
        Query(
            max_length=SEARCH_QUERY_MAX_LENGTH,
            description="Case-insensitive search by symbol, instrument ID, name or alias.",
        ),
    ] = None,
) -> InstrumentList:
    catalog = await _call(request, "list_instruments", provider.list_instruments())
    return InstrumentList(instruments=search_instruments(catalog, query))


@router.get(
    "/overview",
    response_model=MarketOverview,
    operation_id="getMarketOverview",
    responses={503: _ERROR_RESPONSES[503]},
)
async def get_overview(request: Request, provider: Provider) -> MarketOverview:
    return await _call(request, "get_overview", provider.get_overview())


@router.get(
    "/instruments/{instrumentId}/candles",
    response_model=MarketCandles,
    operation_id="getMarketCandles",
    responses={
        **_ERROR_RESPONSES,
        404: {"description": "The identifier is valid but absent from the catalog."},
    },
)
async def get_candles(
    request: Request,
    provider: Provider,
    instrument_id: Annotated[
        str,
        Path(
            alias="instrumentId",
            pattern=INSTRUMENT_ID_PATTERN,
            description="Stable exchange-qualified instrument identifier.",
        ),
    ],
    timeframe: Annotated[Timeframe, Query()],
) -> MarketCandles:
    history = await _call(request, "get_candles", provider.get_candles(instrument_id, timeframe))
    if history is None:
        raise ApiError(404, "UNKNOWN_INSTRUMENT", "No instrument has this identifier.")
    if history.instrument_id != instrument_id or history.timeframe != timeframe:
        logger.error("market_data_invalid", operation="get_candles", reason="mismatched_history")
        raise _unavailable()
    return history
