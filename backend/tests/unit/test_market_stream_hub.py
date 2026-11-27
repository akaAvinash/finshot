"""The stream hub, the mock feed, the Kite ticker loop against a local
WebSocket server, settings rules, and frames against the AsyncAPI contract."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import SecretStr, ValidationError
from websockets.asyncio.server import ServerConnection, serve

from app.market.schemas import TIMEFRAMES, MarketCandle, MarketCandles
from app.market.stream import kite as kite_module
from app.market.stream.hub import MarketStreamHub
from app.market.stream.messages import (
    MarketSnapshotFrame,
    MarketStatusFrame,
    MarketUpdateFrame,
    wire,
)
from app.market.stream.source import MockTickSource, Subscriptions
from app.market.stream.ticks import CandleBuilder, Tick, quote_from_tick
from tests.conftest import SettingsFactory
from tests.unit.test_market_stream_kite import (
    INSTRUMENTS_CSV,
    RELIANCE_TOKEN,
    equity_packet,
    frame,
)

ROOT = Path(__file__).resolve().parents[3] / "contracts"
NOW = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_tick(instrument_id: str = "NSE:RELIANCE", seconds: float = 0, price: float = 100) -> Tick:
    return Tick(instrument_id, price, 99, 101, 98, 99.5, 1000, NOW + timedelta(seconds=seconds))


class ScriptedSource:
    always_open = False

    def __init__(self) -> None:
        self.emit: Callable[[Tick], None] | None = None
        self.wanted: Subscriptions | None = None
        self.runs = 0
        self.fail_first = 0

    def instrument_ids(self) -> frozenset[str]:
        return frozenset({"NSE:RELIANCE", "NSE:TCS"})

    async def history(self, instrument_id: str, timeframe: Any) -> list[MarketCandle]:
        return []

    async def run(self, wanted: Subscriptions, emit: Any, heartbeat: Any) -> None:
        self.runs += 1
        if self.runs <= self.fail_first:
            raise ConnectionError("upstream down")
        self.wanted, self.emit = wanted, emit
        heartbeat()
        await asyncio.Event().wait()


async def started(hub: MarketStreamHub, source: ScriptedSource) -> None:
    hub.start()
    for _ in range(200):
        if source.emit is not None:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("source never started")


async def test_subscriptions_follow_subscribers_and_fan_out() -> None:
    source = ScriptedSource()
    hub = MarketStreamHub(source, clock=Clock())
    await started(hub, source)
    assert source.wanted is not None and source.emit is not None
    async with hub.subscribe("NSE:RELIANCE") as a, hub.subscribe("NSE:RELIANCE") as b:
        assert source.wanted.ids == {"NSE:RELIANCE"} and hub.connection_count == 2
        source.emit(make_tick())
        source.emit(make_tick("NSE:TCS"))  # nobody subscribed to TCS
        assert a.queue.qsize() == b.queue.qsize() == 1
        source.emit(make_tick(seconds=-5))  # older than the latest: dropped
        assert a.queue.qsize() == 1
    assert source.wanted.ids == set() and hub.connection_count == 0
    assert hub.latest("NSE:RELIANCE") is None  # no leftovers for a later subscriber
    await hub.stop()


async def test_slow_subscriber_overflows() -> None:
    source = ScriptedSource()
    hub = MarketStreamHub(source, clock=Clock(), queue_size=8)
    await started(hub, source)
    assert source.emit is not None
    async with hub.subscribe("NSE:RELIANCE") as sub:
        for second in range(9):
            source.emit(make_tick(seconds=second))
        assert sub.overflowed.is_set() and sub.queue.qsize() == 8
    await hub.stop()


async def test_wait_for_tick() -> None:
    source = ScriptedSource()
    hub = MarketStreamHub(source, clock=Clock())
    await started(hub, source)
    assert source.emit is not None
    async with hub.subscribe("NSE:RELIANCE"):
        assert await hub.wait_for_tick("NSE:RELIANCE", wait_seconds=0.01) is None
        emit = source.emit
        asyncio.get_running_loop().call_later(0.01, lambda: emit(make_tick()))
        tick = await hub.wait_for_tick("NSE:RELIANCE", wait_seconds=1)
        assert tick is not None and tick.price == 100
    await hub.stop()


async def test_state_transitions() -> None:
    clock = Clock(datetime(2026, 11, 27, 5, 0, tzinfo=UTC))  # 10:30 IST Friday
    source = ScriptedSource()
    hub = MarketStreamHub(source, clock=clock, stale_after_seconds=30)
    assert hub.state() == "unavailable"
    await started(hub, source)
    assert hub.state() == "live"
    clock.now += timedelta(seconds=31)
    assert hub.state() == "stale"
    clock.now = datetime(2026, 11, 27, 11, 0, tzinfo=UTC)  # 16:30 IST
    assert hub.state() == "closed"
    await hub.stop()
    assert hub.state() == "unavailable"


async def test_reconnects_after_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep

    async def fast_sleep(delay: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr("app.market.stream.hub.asyncio.sleep", fast_sleep)
    source = ScriptedSource()
    source.fail_first = 2
    hub = MarketStreamHub(source, clock=Clock())
    await started(hub, source)
    assert source.runs == 3 and hub.state() == "live"
    await hub.stop()


async def test_mock_source_history_joins_live_price() -> None:
    clock = Clock()
    source = MockTickSource(clock, tick_seconds=0.01, seed=1)
    for timeframe in TIMEFRAMES:
        candles = await source.history("NSE:RELIANCE", timeframe)
        MarketCandles(
            instrument_id="NSE:RELIANCE",
            timeframe=timeframe,
            source="market",
            as_of=NOW,
            freshness="fresh",
            candles=candles,
        )  # validates order and OHLC
        assert candles[-1].close == 1429.65
    index = await source.history("NSE:NIFTY50", "5m")
    assert all(candle.volume is None for candle in index)

    wanted = Subscriptions()
    wanted.set({"NSE:RELIANCE"})
    ticks: list[Tick] = []
    task = asyncio.create_task(source.run(wanted, ticks.append, lambda: None))
    await asyncio.sleep(0.05)
    task.cancel()
    assert ticks and all(t.instrument_id == "NSE:RELIANCE" for t in ticks)
    for t in ticks:
        quote_from_tick(t)  # every mock tick makes a valid quote


async def test_kite_ticker_subscribes_and_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[Any] = []
    paths: list[str] = []
    three = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        assert ws.request is not None
        paths.append(ws.request.path)
        async for message in ws:
            received.append(json.loads(message))
            if len(received) >= 3:
                three.set()
            if received[-1]["a"] == "mode":
                await ws.send(b"\x00")  # heartbeat
                await ws.send(json.dumps({"type": "order", "data": {}}))
                await ws.send(frame(equity_packet()))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(kite_module, "TICKER_URL", f"ws://127.0.0.1:{port}")
        token_file = tmp_path / "token"
        token_file.write_text("tok")
        transport = httpx.MockTransport(lambda r: httpx.Response(200, text=INSTRUMENTS_CSV))
        source = kite_module.KiteTickSource(
            api_key=SecretStr("key"),
            access_token_file=str(token_file),
            clock=Clock(),
            http=httpx.AsyncClient(transport=transport),
        )
        wanted = Subscriptions()
        wanted.set({"NSE:RELIANCE"})
        ticks: list[Tick] = []
        beats: list[int] = []
        got = asyncio.Event()

        def emit(tick: Tick) -> None:
            ticks.append(tick)
            got.set()

        task = asyncio.create_task(source.run(wanted, emit, lambda: beats.append(1)))
        async with asyncio.timeout(5):
            await got.wait()
        wanted.set(set())
        async with asyncio.timeout(5):
            await three.wait()
        task.cancel()
        await source.aclose()

    assert paths == ["/?api_key=key&access_token=tok"]
    assert received == [
        {"a": "subscribe", "v": [RELIANCE_TOKEN]},
        {"a": "mode", "v": ["full", [RELIANCE_TOKEN]]},
        {"a": "unsubscribe", "v": [RELIANCE_TOKEN]},
    ]
    assert ticks[0].instrument_id == "NSE:RELIANCE" and ticks[0].price == 1429.65
    assert len(beats) == 3  # heartbeat, order message, tick frame


# --------------------------------------------------------------- settings


def test_stream_needs_owner(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match="MARKET_STREAM_OWNER_USER_ID"):
        make_settings(market_stream_enabled=True)
    assert make_settings().market_stream_enabled is False


def test_kite_needs_credentials(make_settings: SettingsFactory) -> None:
    owner = uuid.uuid4()
    with pytest.raises(ValidationError, match="KITE_API_KEY, KITE_ACCESS_TOKEN_FILE"):
        make_settings(
            market_stream_enabled=True,
            market_stream_owner_user_id=owner,
            market_stream_provider="kite",
        )
    settings = make_settings(
        market_stream_enabled=True,
        market_stream_owner_user_id=owner,
        market_stream_provider="kite",
        kite_api_key="k",
        kite_access_token_file="/run/secrets/kite",
    )
    assert "k" not in repr(settings.kite_api_key)


def test_mock_stream_refused_in_production(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match="mock market stream"):
        make_settings(
            app_env="production",
            market_stream_enabled=True,
            market_stream_owner_user_id=uuid.uuid4(),
            database_url="postgresql+asyncpg://u:pw@db/t",
            redis_url="redis://:pw@redis/0",
            log_format="json",
            allowed_hosts=["api.example.com"],
        )


# --------------------------------------------------------------- contract


def _stream_schemas() -> dict[str, Any]:
    stream = yaml.safe_load((ROOT / "live-market-stream.asyncapi.yaml").read_text())
    openapi = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    text = json.dumps(stream["components"]["messages"]).replace(
        "./openapi.yaml#/components/schemas/", "#/components/schemas/"
    )
    messages = json.loads(text)
    return {"messages": messages, "components": openapi["components"]}


def stream_errors(message: str, payload: Any) -> list[str]:
    loaded = _stream_schemas()
    schema = {**loaded["messages"][message]["payload"], "components": loaded["components"]}
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(payload)]


async def test_frames_match_the_asyncapi_contract() -> None:
    source = MockTickSource(Clock(), seed=3)
    candles = await source.history("NSE:RELIANCE", "5m")
    tick = make_tick(price=1430.5)
    snapshot = MarketSnapshotFrame(
        as_of=tick.exchange_time,
        quote=quote_from_tick(tick),
        history=MarketCandles(
            instrument_id="NSE:RELIANCE",
            timeframe="5m",
            source="market",
            as_of=tick.exchange_time,
            freshness="fresh",
            candles=candles,
        ),
    )
    assert stream_errors("MarketSnapshot", wire(snapshot)) == []
    candle = CandleBuilder("5m", candles[-1]).apply(tick)
    assert candle is not None
    update = MarketUpdateFrame(
        timeframe="5m", as_of=tick.exchange_time, quote=quote_from_tick(tick), candle=candle
    )
    assert stream_errors("MarketUpdate", wire(update)) == []
    for state in ("live", "closed", "stale", "unavailable"):
        status = MarketStatusFrame(state=state, sent_at=NOW)  # type: ignore[arg-type]
        assert stream_errors("MarketStatus", wire(status)) == []


def test_snapshot_history_must_be_market_data() -> None:
    tick = make_tick()
    with pytest.raises(ValidationError, match="source market"):
        MarketSnapshotFrame(
            as_of=NOW,
            quote=quote_from_tick(tick),
            history=MarketCandles(
                instrument_id="NSE:RELIANCE",
                timeframe="5m",
                source="demo",
                as_of=NOW,
                freshness="fresh",
                candles=[],
            ),
        )
