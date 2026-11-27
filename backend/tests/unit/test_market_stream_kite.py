"""Kite Connect source: binary ticker parsing, historical candles, the token
exchange command, and that credentials never reach logs."""

from __future__ import annotations

import json
import stat
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.market.stream import kite_session
from app.market.stream.kite import KiteTickSource, parse_history, parse_ticker_frame
from app.market.stream.source import SourceUnavailableError
from tests.conftest import SettingsFactory

NIFTY_TOKEN = 256265  # segment byte 9 = indices
RELIANCE_TOKEN = 738561  # segment byte 1 = NSE equity
NOW = datetime(2026, 11, 27, 5, 0, tzinfo=UTC)  # 10:30 IST, Friday
STAMP = int(NOW.timestamp())


def index_packet(full: bool = True) -> bytes:
    fields = [NIFTY_TOKEN, 2448110, 2452000, 2430000, 2435000, 2434961, 13149]
    packet = struct.pack(">7I", *fields)
    return packet + struct.pack(">I", STAMP) if full else packet


def equity_packet(full: bool = True) -> bytes:
    quote = [RELIANCE_TOKEN, 142965, 10, 142900, 8235640, 1, 2, 143000, 143500, 142000, 143223]
    packet = struct.pack(">11I", *quote)
    if not full:
        return packet
    extra = struct.pack(">5I", STAMP - 1, 0, 0, 0, STAMP)
    return packet + extra + b"\x00" * 120  # 5-level depth


def frame(*packets: bytes) -> bytes:
    body = b"".join(struct.pack(">H", len(p)) + p for p in packets)
    return struct.pack(">H", len(packets)) + body


def test_parses_index_and_equity_full_packets() -> None:
    nifty, reliance = parse_ticker_frame(frame(index_packet(), equity_packet()))
    assert (nifty.token, nifty.price, nifty.high, nifty.low, nifty.open) == (
        NIFTY_TOKEN,
        24481.10,
        24520.00,
        24300.00,
        24350.00,
    )
    assert nifty.previous_close == 24349.61 and nifty.volume is None
    assert nifty.exchange_time == NOW
    assert (reliance.price, reliance.volume, reliance.open, reliance.high, reliance.low) == (
        1429.65,
        8235640,
        1430.00,
        1435.00,
        1420.00,
    )
    assert reliance.previous_close == 1432.23 and reliance.exchange_time == NOW


def test_quote_mode_packets_have_no_exchange_time() -> None:
    (nifty, reliance) = parse_ticker_frame(frame(index_packet(False), equity_packet(False)))
    assert nifty.exchange_time is None and reliance.exchange_time is None


@pytest.mark.parametrize(
    "data",
    [
        b"\x00",
        b"",
        frame(struct.pack(">2I", RELIANCE_TOKEN, 1)),
        b"\x00\x02\x00\x2c" + b"\x00" * 10,
    ],
)
def test_heartbeats_ltp_packets_and_truncated_frames_yield_nothing(data: bytes) -> None:
    assert parse_ticker_frame(data) == []


def test_parse_history_normalises_daily_bars_and_drops_bad_rows() -> None:
    payload = {
        "status": "success",
        "data": {
            "candles": [
                ["2026-11-26T00:00:00+0530", 100, 105, 99, 104, 1000],
                ["2026-11-27T00:00:00+0530", 104, 103, 99, 101, 900],  # high < open: dropped
                ["garbage"],
            ]
        },
    }
    (candle,) = parse_history(payload, "1D")
    assert candle.time == datetime(2026, 11, 26, 3, 45, tzinfo=UTC)  # 09:15 IST
    minute = parse_history(
        {"data": {"candles": [["2026-11-27T09:16:00+0530", 1, 2, 1, 2, 5]]}}, "1m"
    )
    assert minute[0].time == datetime(2026, 11, 27, 3, 46, tzinfo=UTC)


INSTRUMENTS_CSV = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,"
    "lot_size,instrument_type,segment,exchange\n"
    f"{NIFTY_TOKEN},1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
    f"{RELIANCE_TOKEN},2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
    "999,9,RELIANCE,DUPLICATE IN ANOTHER EXCHANGE,0,,0,0.05,1,EQ,BSE,BSE\n"
)


class Recorder:
    def __init__(self, history: dict[str, Any] | None = None, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.history = history or {
            "data": {
                "candles": [
                    ["2026-11-26T10:15:00+0530", 1420, 1425, 1418, 1424, 900],
                    ["2026-11-27T09:15:00+0530", 1430, 1436, 1428, 1431, 1200],
                    ["2026-11-27T10:15:00+0530", 1431, 1433, 1427, 1429.65, 800],
                ]
            }
        }
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"status": "error"})
        if request.url.path == "/instruments/NSE":
            return httpx.Response(200, text=INSTRUMENTS_CSV)
        return httpx.Response(200, json=self.history)


def kite_source(tmp_path: Path, recorder: Recorder) -> KiteTickSource:
    token_file = tmp_path / "kite-token"
    token_file.write_text("access-token-value\n")
    return KiteTickSource(
        api_key=SecretStr("api-key-value"),
        access_token_file=str(token_file),
        clock=lambda: NOW,
        http=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
    )


async def test_history_resolves_tokens_and_keeps_requested_sessions(tmp_path: Path) -> None:
    recorder = Recorder()
    source = kite_source(tmp_path, recorder)
    candles = await source.history("NSE:RELIANCE", "1h")
    assert [c.close for c in candles] == [1424, 1431, 1429.65]
    instruments, historical = recorder.requests
    assert instruments.headers["Authorization"] == "token api-key-value:access-token-value"
    assert instruments.headers["X-Kite-Version"] == "3"
    assert historical.url.path == f"/instruments/historical/{RELIANCE_TOKEN}/60minute"
    assert historical.url.params["to"] == "2026-11-27 10:30:00"  # IST
    # Cached briefly: a second snapshot does not call Kite again.
    await source.history("NSE:RELIANCE", "1h")
    assert len(recorder.requests) == 2
    await source.aclose()


async def test_index_history_has_no_volume(tmp_path: Path) -> None:
    source = kite_source(tmp_path, Recorder())
    candles = await source.history("NSE:NIFTY50", "1h")
    assert candles and all(c.volume is None for c in candles)
    await source.aclose()


async def test_refused_request_is_unavailable_and_logs_no_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = kite_source(tmp_path, Recorder(status=403))
    with pytest.raises(SourceUnavailableError):
        await source.history("NSE:RELIANCE", "5m")
    out = capsys.readouterr()
    assert "access-token-value" not in out.out + out.err
    assert "api-key-value" not in out.out + out.err
    await source.aclose()


async def test_missing_token_file_is_unavailable(tmp_path: Path) -> None:
    source = KiteTickSource(
        api_key=SecretStr("k"),
        access_token_file=str(tmp_path / "absent"),
        clock=lambda: NOW,
        http=httpx.AsyncClient(transport=httpx.MockTransport(Recorder())),
    )
    with pytest.raises(SourceUnavailableError):
        await source.history("NSE:RELIANCE", "5m")
    await source.aclose()


def test_ticks_map_tokens_to_catalog_ids(tmp_path: Path) -> None:
    source = kite_source(tmp_path, Recorder())
    source._ids_by_token = {RELIANCE_TOKEN: "NSE:RELIANCE"}
    (raw,) = parse_ticker_frame(frame(equity_packet()))
    tick = source._to_tick(raw)
    assert tick is not None and tick.instrument_id == "NSE:RELIANCE"
    (unknown,) = parse_ticker_frame(frame(index_packet()))
    assert source._to_tick(unknown) is None


def test_order_messages_on_the_ticker_are_dropped() -> None:
    KiteTickSource._text_message(json.dumps({"type": "order", "data": {"order_id": "1"}}))
    KiteTickSource._text_message("not json")


def test_token_exchange_writes_private_file(
    tmp_path: Path, make_settings: SettingsFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "secrets" / "kite-token"
    settings: Settings = make_settings(
        kite_api_key="key", kite_api_secret="secret", kite_access_token_file=str(target)
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"access_token": "fresh-token"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        kite_session.exchange(settings, " req-token ", client)
    body = dict(httpx.QueryParams(seen[0].content.decode()))
    assert body["request_token"] == "req-token"
    assert body["checksum"] == kite_session.checksum("key", "req-token", "secret")
    assert target.read_text() == "fresh-token"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert "fresh-token" not in capsys.readouterr().out


def test_token_exchange_refusal_keeps_old_token(
    tmp_path: Path, make_settings: SettingsFactory
) -> None:
    target = tmp_path / "kite-token"
    target.write_text("old")
    settings = make_settings(
        kite_api_key="key", kite_api_secret="secret", kite_access_token_file=str(target)
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(403, json={}))
    with httpx.Client(transport=transport) as client, pytest.raises(SystemExit):
        kite_session.exchange(settings, "bad", client)
    assert target.read_text() == "old"
