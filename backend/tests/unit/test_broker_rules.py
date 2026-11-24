"""Pure rules for demo broker connections (no database)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.brokers.adapter import READ_SCOPES, DemoBrokerAdapter
from app.brokers.service import ALLOWED_ACTIONS, status_of

NOW = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("expires_at", "expected"),
    [
        (None, "disconnected"),
        (NOW + timedelta(seconds=1), "connected"),
        (NOW, "expired"),  # expired at the expiry instant, as the contract says
        (NOW - timedelta(hours=1), "expired"),
    ],
)
def test_status_of(expires_at: datetime | None, expected: str) -> None:
    assert status_of(expires_at, NOW) == expected


def test_allowed_actions_match_the_contract() -> None:
    assert ALLOWED_ACTIONS == {
        "connected": {"sync", "disconnect"},
        "expired": {"reconnect", "disconnect"},
        "disconnected": {"connect"},
    }


def test_demo_adapter_grants_read_only_scopes_for_eight_hours() -> None:
    grant = asyncio.run(DemoBrokerAdapter().authorize("fyers", NOW))
    assert grant.masked_account_id == "•••• 0956"
    assert grant.scopes == READ_SCOPES
    assert grant.expires_at == NOW + timedelta(hours=8)


def test_demo_adapter_returns_no_invented_holdings_or_orders() -> None:
    data = asyncio.run(DemoBrokerAdapter().fetch_account("zerodha", "•••• 4821"))
    assert (data.holdings_count, data.open_orders_count) == (0, 0)
