"""Read-only broker adapter protocol and the demo adapter.

The protocol deliberately has no order placement, modification or cancel
methods. Live adapters (Zerodha, Fyers) are a later, separately approved phase
and need real OAuth, server-held credentials and the broker's current rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

BrokerId = Literal["zerodha", "fyers"]
Scope = Literal["profile_read", "holdings_read", "orders_read"]

PROVIDERS: tuple[BrokerId, ...] = ("zerodha", "fyers")
READ_SCOPES: tuple[Scope, ...] = ("profile_read", "holdings_read", "orders_read")


class BrokerUnavailableError(Exception):
    """The broker source cannot serve the request (disabled, down, timed out)."""


@dataclass(frozen=True, slots=True)
class AccountGrant:
    """What a successful (re)authorization yields. Never holds credentials."""

    masked_account_id: str
    scopes: tuple[Scope, ...]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AccountData:
    """Read-only account data fetched during a sync. Quantities and prices
    are not modelled yet: the demo source returns empty collections rather
    than invented positions."""

    masked_account_id: str
    holdings_count: int
    open_orders_count: int


class BrokerAdapter(Protocol):
    """Read-only operations against one broker for one user."""

    async def authorize(self, provider: BrokerId, now: datetime) -> AccountGrant: ...

    async def fetch_account(self, provider: BrokerId, masked_account_id: str) -> AccountData: ...


# Fixed demo labels, matching the frontend broker mock. Not real accounts.
_DEMO_MASKS: dict[BrokerId, str] = {"zerodha": "•••• 4821", "fyers": "•••• 0956"}
DEMO_SESSION_HOURS = 8


class DemoBrokerAdapter:
    """Simulates broker authorization and sync. Makes no network calls."""

    async def authorize(self, provider: BrokerId, now: datetime) -> AccountGrant:
        return AccountGrant(
            masked_account_id=_DEMO_MASKS[provider],
            scopes=READ_SCOPES,
            expires_at=now + timedelta(hours=DEMO_SESSION_HOURS),
        )

    async def fetch_account(self, provider: BrokerId, masked_account_id: str) -> AccountData:
        return AccountData(
            masked_account_id=masked_account_id, holdings_count=0, open_orders_count=0
        )
