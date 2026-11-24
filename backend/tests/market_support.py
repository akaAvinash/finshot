"""Helpers for the market data tests: contract schema checks and fake providers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.main import create_app
from app.market.provider import MarketDataProvider, MarketDataUnavailableError
from app.market.schemas import Instrument, MarketCandles, MarketOverview, Timeframe
from tests.conftest import SettingsFactory

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
MARKET = "/api/v1/market"


def load_contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


def schema_errors(contract: dict[str, Any], schema_name: str, payload: Any) -> list[str]:
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(payload)]


def candles_url(instrument_id: str, timeframe: str | None = None) -> str:
    url = f"{MARKET}/instruments/{instrument_id}/candles"
    return url if timeframe is None else f"{url}?timeframe={timeframe}"


@contextmanager
def market_client(
    make_settings: SettingsFactory,
    provider: MarketDataProvider | None = None,
    **settings: Any,
) -> Iterator[TestClient]:
    app = create_app(make_settings(**settings), market_provider=provider)
    with TestClient(app) as client:
        yield client


class FailingProvider:
    """Every call reports an outage, like a feed that is down."""

    async def list_instruments(self) -> Sequence[Instrument]:
        raise MarketDataUnavailableError("feed down")

    async def get_overview(self) -> MarketOverview:
        raise MarketDataUnavailableError("feed down")

    async def get_candles(self, instrument_id: str, timeframe: Timeframe) -> MarketCandles | None:
        raise MarketDataUnavailableError("feed down")


class SlowProvider:
    """Never answers within the configured timeout."""

    async def _hang(self) -> Any:
        await asyncio.sleep(10)

    async def list_instruments(self) -> Sequence[Instrument]:
        result: Sequence[Instrument] = await self._hang()
        return result

    async def get_overview(self) -> MarketOverview:
        result: MarketOverview = await self._hang()
        return result

    async def get_candles(self, instrument_id: str, timeframe: Timeframe) -> MarketCandles | None:
        result: MarketCandles | None = await self._hang()
        return result


class StubProvider:
    """Returns whatever the test builds; builders run inside the call, so a
    model validation error surfaces where a real provider's would."""

    def __init__(
        self,
        *,
        instruments: Callable[[], Sequence[Instrument]] = tuple,
        overview: Callable[[], MarketOverview] | None = None,
        candles: Callable[[str, Timeframe], MarketCandles | None] = lambda _i, _t: None,
    ) -> None:
        self._instruments = instruments
        self._overview = overview
        self._candles = candles

    async def list_instruments(self) -> Sequence[Instrument]:
        return self._instruments()

    async def get_overview(self) -> MarketOverview:
        assert self._overview is not None
        return self._overview()

    async def get_candles(self, instrument_id: str, timeframe: Timeframe) -> MarketCandles | None:
        return self._candles(instrument_id, timeframe)
