"""The owner market stream over real sessions: who may connect, the frames
it sends, and how it ends (contracts/live-market-stream.asyncapi.yaml)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.market.schemas import MarketCandle
from app.market.stream.source import MockTickSource, Subscriptions
from tests.support import ORIGIN, OTHER_PHONE, PHONE, Browser, FakeClock, db_rows
from tests.unit.test_market_stream_hub import stream_errors

PATH = "wss://testserver/api/v1/market/stream"
URL = f"{PATH}?instrumentId=NSE:RELIANCE&timeframe=5m"
HEADERS = {"origin": ORIGIN}


def user_id(db_url: str, phone: str) -> str:
    return str(db_rows(db_url, "SELECT id FROM users WHERE phone_e164 = :p", p=phone)[0]["id"])


class SilentSource(MockTickSource):
    """Connects but never ticks."""

    async def run(self, wanted: Subscriptions, emit: Any, heartbeat: Any) -> None:
        heartbeat()
        await asyncio.Event().wait()


class OneTickSource(MockTickSource):
    """One tick per instrument, then only heartbeats: a quiet but live feed."""

    async def run(self, wanted: Subscriptions, emit: Any, heartbeat: Any) -> None:
        sent: set[str] = set()
        while True:
            heartbeat()
            for instrument_id in wanted.ids - sent:
                emit(self._step(instrument_id))
                sent.add(instrument_id)
            await asyncio.sleep(0.05)


class FailingHistorySource(MockTickSource):
    async def history(self, instrument_id: str, timeframe: Any) -> list[MarketCandle]:
        raise RuntimeError("history down")


@pytest.fixture
def owner_stream(
    make_app: Callable[..., TestClient], db_url: str, clock: FakeClock
) -> Callable[..., tuple[TestClient, Browser]]:
    """Sign in on one app, then open a stream-enabled app whose configured
    owner is that account, carrying the browser's cookies over."""

    def make(
        phone: str = PHONE,
        owner_phone: str | None = None,
        ready: bool = True,
        source: Any = None,
        **settings: Any,
    ) -> tuple[TestClient, Browser]:
        signer = Browser(make_app())
        if ready:
            signer.login_ready(phone=phone)
        else:
            signer.login(phone=phone)
        if owner_phone and owner_phone != phone:
            Browser(make_app()).login_ready(phone=owner_phone)
        settings.setdefault("market_stream_mock_tick_seconds", 0.05)
        settings.setdefault("market_stream_snapshot_timeout_seconds", 2)
        client = make_app(
            market_stream_enabled=True,
            market_stream_owner_user_id=user_id(db_url, owner_phone or phone),
            **settings,
        )
        if source is not None:
            hub = client.app.state.market_stream  # type: ignore[attr-defined]

            async def swap() -> None:
                await hub.stop()
                hub.source = source
                hub.start()

            client.portal.call(swap)  # type: ignore[union-attr]
        browser = Browser(client)
        browser.jar = signer.jar
        browser.activate()
        return client, browser

    return make


def denial(client: TestClient, url: str = URL, headers: dict[str, str] | None = None) -> Any:
    with (
        pytest.raises(WebSocketDenialResponse) as denied,
        client.websocket_connect(url, headers=headers or HEADERS),
    ):
        pass
    return denied.value


def test_owner_gets_snapshot_status_then_updates(
    owner_stream: Callable[..., tuple[TestClient, Browser]],
) -> None:
    client, _ = owner_stream()
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert stream_errors("MarketSnapshot", snapshot) == []
        history = snapshot["history"]
        assert (history["instrumentId"], history["timeframe"], history["source"]) == (
            "NSE:RELIANCE",
            "5m",
            "market",
        )
        assert snapshot["quote"]["instrumentId"] == "NSE:RELIANCE"
        status = ws.receive_json()
        assert status["type"] == "status" and status["state"] == "live"
        assert stream_errors("MarketStatus", status) == []
        update = ws.receive_json()
        assert update["type"] == "update" and update["timeframe"] == "5m"
        assert stream_errors("MarketUpdate", update) == []
        # The update replaces the last history bar or appends a later one.
        assert update["candle"]["time"] >= history["candles"][-1]["time"]


def test_missing_or_ended_session_is_401(
    owner_stream: Callable[..., tuple[TestClient, Browser]], db_url: str
) -> None:
    client, _ = owner_stream()
    db_rows(db_url, "UPDATE sessions SET revoked_at = now()")
    assert denial(client).status_code == 401
    client.cookies.clear()
    assert denial(client).json()["code"] == "UNAUTHENTICATED"


def test_other_accounts_are_403(owner_stream: Callable[..., tuple[TestClient, Browser]]) -> None:
    client, _ = owner_stream(phone=OTHER_PHONE, owner_phone=PHONE)
    denied = denial(client)
    assert denied.status_code == 403 and denied.json()["code"] == "MARKET_STREAM_FORBIDDEN"


def test_owner_pending_authenticator_setup_is_403(
    owner_stream: Callable[..., tuple[TestClient, Browser]],
) -> None:
    client, _ = owner_stream(ready=False)
    assert denial(client).status_code == 403


@pytest.mark.parametrize(
    "query",
    [
        "instrumentId=NSE:RELIANCE",
        "instrumentId=NSE:RELIANCE&timeframe=2m",
        "instrumentId=reliance&timeframe=5m",
        "instrumentId=NSE:UNKNOWN&timeframe=5m",
        "instrumentId=NSE:RELIANCE&timeframe=5m&extra=1",
        "instrumentId=NSE:RELIANCE&timeframe=5m&timeframe=1m",
    ],
)
def test_invalid_selection_is_400(
    owner_stream: Callable[..., tuple[TestClient, Browser]], query: str
) -> None:
    client, _ = owner_stream()
    denied = denial(client, f"{PATH}?{query}")
    assert denied.status_code == 400 and denied.json()["code"] == "INVALID_REQUEST"


def test_no_first_tick_is_503(
    owner_stream: Callable[..., tuple[TestClient, Browser]], clock: FakeClock
) -> None:
    client, _ = owner_stream(source=SilentSource(clock), market_stream_snapshot_timeout_seconds=0.2)
    denied = denial(client)
    assert denied.status_code == 503 and denied.json()["code"] == "MARKET_STREAM_UNAVAILABLE"
    assert denied.headers["retry-after"] == "5"


def test_history_failure_is_503(
    owner_stream: Callable[..., tuple[TestClient, Browser]], clock: FakeClock
) -> None:
    client, _ = owner_stream(source=FailingHistorySource(clock, tick_seconds=0.05))
    assert denial(client).status_code == 503


def test_connection_cap_is_503(owner_stream: Callable[..., tuple[TestClient, Browser]]) -> None:
    client, _ = owner_stream(market_stream_max_connections=1)
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        ws.receive_json()
        assert denial(client).status_code == 503


def receive_until_close(ws: Any, seconds: float = 5) -> int:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            ws.receive_json()
        except WebSocketDisconnect as closed:
            return closed.code
    raise AssertionError("the stream did not close")


def test_revoked_session_closes_4401(
    owner_stream: Callable[..., tuple[TestClient, Browser]], db_url: str
) -> None:
    client, _ = owner_stream(market_stream_session_recheck_seconds=1)
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        ws.receive_json()
        db_rows(db_url, "UPDATE sessions SET revoked_at = now()")
        assert receive_until_close(ws) == 4401


def test_lost_authenticator_closes_4403(
    owner_stream: Callable[..., tuple[TestClient, Browser]], db_url: str
) -> None:
    client, _ = owner_stream(market_stream_session_recheck_seconds=1)
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        ws.receive_json()
        db_rows(db_url, "DELETE FROM totp_credentials")
        assert receive_until_close(ws) == 4403


def test_open_stream_keeps_the_session_alive(
    owner_stream: Callable[..., tuple[TestClient, Browser]], db_url: str, clock: FakeClock
) -> None:
    """Owner decision 2026-11-27: each recheck renews the session, so an open
    chart is not signed out by the idle timeout (the absolute expiry still holds)."""
    client, _ = owner_stream(market_stream_session_recheck_seconds=1)
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        ws.receive_json()
        before = db_rows(db_url, "SELECT last_seen_at FROM sessions")[0]["last_seen_at"]
        clock.advance(120)
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            ws.receive_json()
        after = db_rows(db_url, "SELECT last_seen_at FROM sessions")[0]["last_seen_at"]
        assert after == clock.now and after > before


def test_client_message_closes_1008(
    owner_stream: Callable[..., tuple[TestClient, Browser]],
) -> None:
    client, _ = owner_stream()
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        ws.receive_json()
        ws.send_text("subscribe NSE:TCS")
        assert receive_until_close(ws) == 1008


def test_idle_feed_sends_periodic_status(
    owner_stream: Callable[..., tuple[TestClient, Browser]], clock: FakeClock
) -> None:
    client, _ = owner_stream(source=OneTickSource(clock), market_stream_heartbeat_seconds=1)
    with client.websocket_connect(URL, headers=HEADERS) as ws:
        assert ws.receive_json()["type"] == "snapshot"
        frames = [ws.receive_json() for _ in range(3)]
        assert [frame["type"] for frame in frames] == ["status"] * 3
        assert {frame["state"] for frame in frames} == {"live"}


def test_refused_upgrade_does_not_renew_the_session(
    owner_stream: Callable[..., tuple[TestClient, Browser]], db_url: str, clock: FakeClock
) -> None:
    client, _ = owner_stream(phone=OTHER_PHONE, owner_phone=PHONE)
    before = db_rows(
        db_url,
        "SELECT s.last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE u.phone_e164 = :p",
        p=OTHER_PHONE,
    )[0]["last_seen_at"]
    clock.advance(120)
    assert denial(client).status_code == 403
    after = db_rows(
        db_url,
        "SELECT s.last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE u.phone_e164 = :p",
        p=OTHER_PHONE,
    )[0]["last_seen_at"]
    assert after == before


def test_refused_selection_does_not_renew_the_owner_session(
    owner_stream: Callable[..., tuple[TestClient, Browser]], db_url: str, clock: FakeClock
) -> None:
    client, _ = owner_stream()
    before = db_rows(db_url, "SELECT last_seen_at FROM sessions")[0]["last_seen_at"]
    clock.advance(120)
    assert denial(client, f"{PATH}?instrumentId=NSE:RELIANCE&timeframe=2m").status_code == 400
    after = db_rows(db_url, "SELECT last_seen_at FROM sessions")[0]["last_seen_at"]
    assert after == before
