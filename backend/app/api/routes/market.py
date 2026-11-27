"""/api/v1/market/* read-only endpoints, as specified in contracts/openapi.yaml.

No authentication (the contract declares none for Markets). Errors use the
shared envelope: 400 INVALID_REQUEST, 404 UNKNOWN_INSTRUMENT,
503 MARKET_DATA_UNAVAILABLE."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.errors import ApiError
from app.market.provider import MarketDataProvider, MarketDataUnavailableError
from app.market.schemas import (
    INSTRUMENT_ID_PATTERN,
    SEARCH_QUERY_MAX_LENGTH,
    Instrument,
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


def _plain(value: Any) -> Any:
    """Dump models to plain data so validation runs again. Pydantic does not
    re-validate an existing model instance, and an instance may have been
    built with model_construct() or had a list mutated after validation."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_plain(item) for item in value]
    return value


_CATALOG = TypeAdapter(list[Instrument])
_OVERVIEW = TypeAdapter(MarketOverview)
_HISTORY = TypeAdapter(MarketCandles | None)


async def _call[T](
    request: Request, operation: str, awaitable: Awaitable[Any], adapter: TypeAdapter[T]
) -> T:
    """Run a provider call and re-validate its result against the response
    models. An outage, a timeout or invalid data all become 503, so a provider
    can never cause a 500 or reach a client with bad data. Details go to the
    log only."""
    timeout = request.app.state.settings.market_data_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            result = await awaitable
        return adapter.validate_python(_plain(result))
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
    catalog = await _call(request, "list_instruments", provider.list_instruments(), _CATALOG)
    return InstrumentList(source=provider.source, instruments=search_instruments(catalog, query))


@router.get(
    "/overview",
    response_model=MarketOverview,
    operation_id="getMarketOverview",
    responses={503: _ERROR_RESPONSES[503]},
)
async def get_overview(request: Request, provider: Provider) -> MarketOverview:
    return await _call(request, "get_overview", provider.get_overview(), _OVERVIEW)


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
    history = await _call(
        request, "get_candles", provider.get_candles(instrument_id, timeframe), _HISTORY
    )
    if history is None:
        raise ApiError(404, "UNKNOWN_INSTRUMENT", "No instrument has this identifier.")
    if history.instrument_id != instrument_id or history.timeframe != timeframe:
        logger.error("market_data_invalid", operation="get_candles", reason="mismatched_history")
        raise _unavailable()
    return history
