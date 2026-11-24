"""/api/v1/market/* through the real FastAPI app (no database or Redis needed)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.market.demo import DemoMarketDataProvider
from app.market.schemas import TIMEFRAMES, Instrument, MarketCandle, MarketCandles
from tests.conftest import SettingsFactory
from tests.market_support import (
    MARKET,
    FailingProvider,
    SlowProvider,
    StubProvider,
    candles_url,
    market_client,
)

EXPECTED_IDS = [
    "NSE:NIFTY50",
    "NSE:BANKNIFTY",
    "NSE:FINNIFTY",
    "NSE:INDIAVIX",
    "NSE:RELIANCE",
    "NSE:HDFCBANK",
    "NSE:SBIN",
    "NSE:TCS",
    "NSE:INFY",
    "NSE:ICICIBANK",
    "NSE:BHARTIARTL",
    "NSE:ITC",
]
INDEXES = {"NSE:NIFTY50", "NSE:BANKNIFTY", "NSE:FINNIFTY", "NSE:INDIAVIX"}
SESSION_OPEN = timedelta(hours=3, minutes=45)  # 09:15 IST
SESSION_CLOSE = timedelta(hours=10)  # 15:30 IST
INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
# Sessions of history per timeframe x bars per 375-minute session.
EXPECTED_COUNTS = {"1m": 375, "5m": 75, "15m": 75, "30m": 65, "1h": 63, "1D": 38}


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() == timedelta(0), value
    return parsed


def ids(response: Any) -> list[str]:
    return [item["id"] for item in response.json()["instruments"]]


def assert_error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert isinstance(body["message"], str) and body["message"]
    assert body["requestId"] == response.headers["X-Request-ID"]
    assert set(body) == {"code", "message", "requestId"}


# --- Instruments -------------------------------------------------------------


def test_lists_whole_catalog_in_stable_order(client: TestClient) -> None:
    response = client.get(f"{MARKET}/instruments")
    assert response.status_code == 200
    assert ids(response) == EXPECTED_IDS
    for item in response.json()["instruments"]:
        assert item["exchange"] == "NSE" and item["currency"] == "INR"
        assert item["kind"] == ("index" if item["id"] in INDEXES else "equity")
        assert isinstance(item["aliases"], list)
    nifty = response.json()["instruments"][0]
    assert nifty == {
        "id": "NSE:NIFTY50",
        "symbol": "NIFTY 50",
        "name": "Nifty 50 Index",
        "exchange": "NSE",
        "kind": "index",
        "currency": "INR",
        "aliases": ["NIFTY"],
    }


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("reliance", "NSE:RELIANCE"),
        ("RELIANCE", "NSE:RELIANCE"),
        ("ReLiAnCe", "NSE:RELIANCE"),
        ("ril", "NSE:RELIANCE"),  # alias
        ("nse:tcs", "NSE:TCS"),  # exchange-qualified ID
        ("NSE:TCS", "NSE:TCS"),
        ("nifty 50", "NSE:NIFTY50"),  # symbol with a space
        ("bank nifty", "NSE:BANKNIFTY"),  # alias with a space
        ("state bank", "NSE:SBIN"),  # name prefix
        ("airtel", "NSE:BHARTIARTL"),
        ("india vix", "NSE:INDIAVIX"),
    ],
)
def test_search_is_case_insensitive_across_fields(
    client: TestClient, query: str, first: str
) -> None:
    response = client.get(f"{MARKET}/instruments", params={"query": query})
    assert response.status_code == 200
    assert ids(response)[0] == first


def test_search_ranks_exact_before_prefix_before_substring(client: TestClient) -> None:
    # NIFTY is an exact alias of NIFTY50 (rank 0). BANKNIFTY and FINNIFTY have
    # aliases starting with NIFTY (rank 1) and keep catalog order between them.
    found = ids(client.get(f"{MARKET}/instruments", params={"query": "nifty"}))
    assert found == ["NSE:NIFTY50", "NSE:BANKNIFTY", "NSE:FINNIFTY"]

    # "ank" only appears inside names and symbols (rank 3).
    assert ids(client.get(f"{MARKET}/instruments", params={"query": "ank"})) == [
        "NSE:BANKNIFTY",
        "NSE:HDFCBANK",
        "NSE:SBIN",
        "NSE:ICICIBANK",
    ]

    hdfc = ids(client.get(f"{MARKET}/instruments", params={"query": "hdfc"}))
    assert hdfc == ["NSE:HDFCBANK"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", EXPECTED_IDS),
        ("   ", EXPECTED_IDS),
        ("zzzz", []),
        ("!!", []),  # no letters or digits matches nothing
    ],
)
def test_blank_and_unmatched_queries(client: TestClient, query: str, expected: list[str]) -> None:
    response = client.get(f"{MARKET}/instruments", params={"query": query})
    assert response.status_code == 200
    assert ids(response) == expected


def test_query_length_limit(client: TestClient) -> None:
    assert client.get(f"{MARKET}/instruments", params={"query": "a" * 100}).status_code == 200
    assert_error(
        client.get(f"{MARKET}/instruments", params={"query": "a" * 101}), 400, "INVALID_REQUEST"
    )


# --- Overview ----------------------------------------------------------------


def test_overview_is_a_dated_demo_snapshot(client: TestClient) -> None:
    response = client.get(f"{MARKET}/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "demo"
    assert parse_time(body["asOf"]) == datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
    assert body["session"] == {
        "exchange": "NSE",
        "status": "closed",
        "timezone": "Asia/Kolkata",
        "opensAt": "2026-11-23T03:45:00Z",
        "closesAt": "2026-11-23T10:00:00Z",
    }
    assert [quote["instrumentId"] for quote in body["quotes"]] == EXPECTED_IDS


def test_overview_quotes_are_internally_consistent(client: TestClient) -> None:
    quotes = client.get(f"{MARKET}/overview").json()["quotes"]
    for quote in quotes:
        assert quote["low"] <= min(quote["open"], quote["price"])
        assert quote["high"] >= max(quote["open"], quote["price"])
        assert quote["change"] == pytest.approx(quote["price"] - quote["previousClose"], abs=0.006)
        assert quote["changePercent"] == pytest.approx(
            quote["change"] / quote["previousClose"] * 100, abs=0.006
        )
        expected_trend = "up" if quote["change"] > 0 else "down" if quote["change"] < 0 else "flat"
        assert quote["trend"] == expected_trend
        if quote["instrumentId"] in INDEXES:
            assert quote["volume"] is None
        else:
            assert isinstance(quote["volume"], int) and quote["volume"] > 0
    by_id = {quote["instrumentId"]: quote for quote in quotes}
    assert by_id["NSE:RELIANCE"]["price"] == 1429.65
    assert by_id["NSE:RELIANCE"]["previousClose"] == 1432.23
    assert by_id["NSE:RELIANCE"]["volume"] == 8235640
    assert by_id["NSE:ITC"]["trend"] == "flat"


# --- Candles -----------------------------------------------------------------


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
@pytest.mark.parametrize("instrument_id", ["NSE:RELIANCE", "NSE:NIFTY50", "NSE:INDIAVIX"])
def test_candles_for_every_timeframe(
    client: TestClient, instrument_id: str, timeframe: str
) -> None:
    response = client.get(candles_url(instrument_id, timeframe))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["instrumentId"] == instrument_id
    assert body["timeframe"] == timeframe
    assert body["source"] == "demo"
    assert body["freshness"] == "fresh"
    as_of = parse_time(body["asOf"])
    assert as_of == datetime(2026, 11, 23, 10, 0, tzinfo=UTC)

    candles = body["candles"]
    assert len(candles) == EXPECTED_COUNTS[timeframe]
    times = [parse_time(candle["time"]) for candle in candles]
    assert times == sorted(set(times)), "ascending with distinct timestamps"
    assert times[-1] < as_of

    for candle, time in zip(candles, times, strict=True):
        assert 0 <= candle["low"] <= min(candle["open"], candle["close"])
        assert candle["high"] >= max(candle["open"], candle["close"])
        if instrument_id in INDEXES:
            assert candle["volume"] is None
        else:
            assert isinstance(candle["volume"], int) and candle["volume"] >= 0
        session_start = datetime.combine(time.date(), datetime.min.time(), UTC) + SESSION_OPEN
        assert time.weekday() < 5
        if timeframe == "1D":
            assert time == session_start
        else:
            offset = time - session_start
            assert timedelta(0) <= offset < SESSION_CLOSE - SESSION_OPEN
            assert offset % timedelta(minutes=INTERVAL[timeframe]) == timedelta(0)


def test_last_daily_candle_matches_overview_quote(client: TestClient) -> None:
    quotes = {q["instrumentId"]: q for q in client.get(f"{MARKET}/overview").json()["quotes"]}
    for instrument_id in ("NSE:RELIANCE", "NSE:NIFTY50"):
        last = client.get(candles_url(instrument_id, "1D")).json()["candles"][-1]
        quote = quotes[instrument_id]
        assert (last["open"], last["high"], last["low"], last["close"], last["volume"]) == (
            quote["open"],
            quote["high"],
            quote["low"],
            quote["price"],
            quote["volume"],
        )


def test_intraday_volume_sums_to_the_session_total(client: TestClient) -> None:
    quote = next(
        q
        for q in client.get(f"{MARKET}/overview").json()["quotes"]
        if q["instrumentId"] == "NSE:TCS"
    )
    for timeframe in ("1m", "5m"):
        candles = client.get(candles_url("NSE:TCS", timeframe)).json()["candles"]
        assert sum(candle["volume"] for candle in candles) == quote["volume"]


def test_candles_are_deterministic_across_app_instances(make_settings: SettingsFactory) -> None:
    bodies = []
    for _ in range(2):
        with market_client(make_settings) as client:
            bodies.append(client.get(candles_url("NSE:SBIN", "15m")).content)
    assert bodies[0] == bodies[1]


def test_percent_encoded_instrument_id_is_accepted(client: TestClient) -> None:
    response = client.get(f"{MARKET}/instruments/NSE%3ATCS/candles?timeframe=1h")
    assert response.status_code == 200
    assert response.json()["instrumentId"] == "NSE:TCS"


def test_stale_snapshot_is_labeled(make_settings: SettingsFactory) -> None:
    with market_client(make_settings, DemoMarketDataProvider("stale")) as client:
        body = client.get(candles_url("NSE:INFY", "1D")).json()
    assert body["freshness"] == "stale"
    # 2026-11-23 is a Monday; the previous session is Friday 2026-11-20.
    assert parse_time(body["asOf"]) == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert parse_time(body["candles"][-1]["time"]) == datetime(2026, 11, 20, 3, 45, tzinfo=UTC)


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_empty_history_is_an_empty_array(make_settings: SettingsFactory, timeframe: str) -> None:
    with market_client(make_settings, DemoMarketDataProvider("empty")) as client:
        response = client.get(candles_url("NSE:RELIANCE", timeframe))
    assert response.status_code == 200
    assert response.json()["candles"] == []
    assert response.json()["timeframe"] == timeframe


# --- Errors ------------------------------------------------------------------


@pytest.mark.parametrize("instrument_id", ["NSE:UNKNOWN", "NSE:RELIANCE-EQ", "NSE:M&M"])
def test_unknown_instrument_is_404(client: TestClient, instrument_id: str) -> None:
    url = candles_url(instrument_id.replace("&", "%26"), "1D")
    assert_error(client.get(url), 404, "UNKNOWN_INSTRUMENT")


@pytest.mark.parametrize(
    "url",
    [
        candles_url("NSE:RELIANCE"),  # timeframe missing
        candles_url("NSE:RELIANCE", ""),
        candles_url("NSE:RELIANCE", "1d"),  # timeframes are case-sensitive
        candles_url("NSE:RELIANCE", "2h"),
        candles_url("NSE:RELIANCE", "1D") + "&timeframe=bogus",  # last value wins
        candles_url("nse:reliance", "1D"),  # IDs are upper case
        candles_url("RELIANCE", "1D"),  # not exchange-qualified
        candles_url("BSE:RELIANCE", "1D"),
        candles_url("NSE:", "1D"),
        candles_url("NSE:REL%20IANCE", "1D"),
    ],
)
def test_invalid_candle_requests_are_400(client: TestClient, url: str) -> None:
    assert_error(client.get(url), 400, "INVALID_REQUEST")


def test_error_echoes_inbound_request_id(client: TestClient) -> None:
    response = client.get(candles_url("NSE:NOPE", "1D"), headers={"X-Request-ID": "trace-123"})
    assert_error(response, 404, "UNKNOWN_INSTRUMENT")
    assert response.json()["requestId"] == "trace-123"


ALL_ENDPOINTS = [f"{MARKET}/instruments", f"{MARKET}/overview", candles_url("NSE:TCS", "1D")]


@pytest.fixture
def disabled_client(make_settings: SettingsFactory) -> Iterator[TestClient]:
    with market_client(make_settings, market_data_provider="disabled") as client:
        yield client


@pytest.mark.parametrize("url", ALL_ENDPOINTS)
def test_disabled_provider_is_503(disabled_client: TestClient, url: str) -> None:
    assert_error(disabled_client.get(url), 503, "MARKET_DATA_UNAVAILABLE")


@pytest.mark.parametrize("url", ALL_ENDPOINTS)
def test_provider_outage_is_503(make_settings: SettingsFactory, url: str) -> None:
    with market_client(make_settings, FailingProvider()) as client:
        response = client.get(url)
    assert_error(response, 503, "MARKET_DATA_UNAVAILABLE")
    assert "feed down" not in response.text


@pytest.mark.parametrize("url", ALL_ENDPOINTS)
def test_provider_timeout_is_503(make_settings: SettingsFactory, url: str) -> None:
    with market_client(make_settings, SlowProvider(), market_data_timeout_seconds=0.05) as client:
        assert_error(client.get(url), 503, "MARKET_DATA_UNAVAILABLE")


def test_invalid_candle_request_is_400_even_when_provider_is_down(
    disabled_client: TestClient,
) -> None:
    assert_error(disabled_client.get(candles_url("NSE:TCS", "9m")), 400, "INVALID_REQUEST")


def _candles(**overrides: Any) -> MarketCandles:
    values: dict[str, Any] = {
        "instrument_id": "NSE:TCS",
        "timeframe": "1D",
        "source": "market",
        "as_of": datetime(2026, 11, 23, 10, tzinfo=UTC),
        "freshness": "fresh",
        "candles": [],
    }
    values.update(overrides)
    return MarketCandles(**values)


def _bar(day: int, **overrides: Any) -> MarketCandle:
    values: dict[str, Any] = {
        "time": datetime(2026, 11, day, 3, 45, tzinfo=UTC),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 100,
    }
    values.update(overrides)
    return MarketCandle(**values)


@pytest.mark.parametrize(
    "build",
    [
        lambda: _candles(candles=[_bar(20), _bar(19)]),  # descending
        lambda: _candles(candles=[_bar(20), _bar(20)]),  # duplicate timestamp
        lambda: _candles(candles=[_bar(20, high=9.5)]),  # high below open/close
        lambda: _candles(candles=[_bar(20, low=10.2)]),  # low above open
        lambda: _candles(candles=[_bar(20, volume=-1)]),
        lambda: _candles(candles=[_bar(20, open=-1.0, low=-2.0)]),
        lambda: _candles(candles=[_bar(20, time=datetime(2026, 11, 20, 9, 15))]),  # naive
        lambda: _candles(instrument_id="NSE:OTHER"),  # history for another instrument
        lambda: _candles(timeframe="1h"),  # history for another timeframe
    ],
)
def test_bad_provider_data_is_never_served(make_settings: SettingsFactory, build: Any) -> None:
    provider = StubProvider(candles=lambda _i, _t: build())
    with market_client(make_settings, provider) as client:
        response = client.get(candles_url("NSE:TCS", "1D"))
    assert_error(response, 503, "MARKET_DATA_UNAVAILABLE")


def test_live_source_label_passes_through(make_settings: SettingsFactory) -> None:
    """A non-demo provider is reported as source=market, unchanged."""
    instrument = Instrument(id="NSE:TCS", symbol="TCS", name="Tata Consultancy", kind="equity")
    provider = StubProvider(
        instruments=lambda: (instrument,),
        candles=lambda _i, _t: _candles(candles=[_bar(19), _bar(20)]),
    )
    with market_client(make_settings, provider) as client:
        assert ids(client.get(f"{MARKET}/instruments", params={"query": "tata"})) == ["NSE:TCS"]
        body = client.get(candles_url("NSE:TCS", "1D")).json()
    assert body["source"] == "market"
    assert len(body["candles"]) == 2


def test_market_endpoints_are_read_only(client: TestClient) -> None:
    for url in ALL_ENDPOINTS:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, url).status_code == 405
