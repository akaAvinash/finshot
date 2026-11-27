"""Read-only broker adapter protocol, the provider registry and the demo adapter.

The protocol deliberately has no order placement, modification or cancel
methods. Live adapters (Zerodha, Fyers) are a later, separately approved phase
and need real OAuth, server-held credentials and the broker's current rules.

Authorization is two steps (`authorize_url`, then `exchange`), because every
real provider redirects the browser out and back. `authorize` and
`fetch_account` are the original one-step demo calls, still used by the
deprecated `/brokers/preview` endpoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import urlencode

BrokerId = Literal["zerodha", "fyers"]
Scope = Literal["profile_read", "holdings_read", "orders_read"]
Capability = Literal["profile_read", "holdings_read", "positions_read", "orders_read", "funds_read"]

PROVIDERS: tuple[BrokerId, ...] = ("zerodha", "fyers")
READ_SCOPES: tuple[Scope, ...] = ("profile_read", "holdings_read", "orders_read")
CAPABILITIES: tuple[Capability, ...] = (
    "profile_read",
    "holdings_read",
    "positions_read",
    "orders_read",
    "funds_read",
)


class BrokerUnavailableError(Exception):
    """The broker source cannot serve the request (disabled, down, timed out)."""


class BrokerAuthInvalidError(Exception):
    """The provider reports the stored authorization invalid (logged out, revoked)."""


class BrokerAuthorizationFailedError(Exception):
    """The provider rejected the parameters returned to the callback page."""


class BrokerRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int = 30) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = retry_after_seconds


class BrokerMalformedResponseError(Exception):
    """The provider answered with something the adapter cannot map."""


class BrokerCapabilityUnsupportedError(Exception):
    """The provider cannot do what was asked."""


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """One entry of the provider registry."""

    id: str
    display_name: str
    capabilities: tuple[Capability, ...]
    max_connections: int = 1
    available: bool = True


@dataclass(frozen=True, slots=True)
class AccountGrant:
    """What a successful (re)authorization yields. Never holds credentials.

    `account_ref` is the provider's own account reference, used to recognise
    the same account again. It is never sent to a client; `masked_account_id`
    is the display form."""

    masked_account_id: str
    scopes: tuple[Capability, ...]
    expires_at: datetime
    account_ref: str = ""


@dataclass(frozen=True, slots=True)
class AccountData:
    """Read-only account data fetched during a preview sync. Quantities and
    prices are not modelled here: the demo source returns empty collections
    rather than invented positions."""

    masked_account_id: str
    holdings_count: int
    open_orders_count: int


@dataclass(frozen=True, slots=True)
class PortfolioData:
    """A provider portfolio in Tradeo's canonical shapes (the contract's
    `BrokerHolding`, `BrokerPosition`, `BrokerOrderRecord` and `BrokerFunds`,
    in their JSON form). A section the adapter was not asked for, or the
    connection is not granted, is None."""

    account_ref: str
    holdings: list[dict[str, Any]] | None = None
    positions: list[dict[str, Any]] | None = None
    orders: list[dict[str, Any]] | None = None
    funds: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BrokerAdapter(Protocol):
    """Read-only operations against the broker providers."""

    def providers(self) -> Sequence[ProviderSpec]: ...

    def authorize_url(self, provider: str, state: str, callback_path: str) -> str: ...

    async def exchange(
        self, provider: str, params: Mapping[str, str], now: datetime
    ) -> AccountGrant: ...

    async def fetch_portfolio(
        self,
        provider: str,
        account_ref: str,
        capabilities: Sequence[Capability],
        now: datetime,
    ) -> PortfolioData: ...

    async def revoke(self, provider: str, account_ref: str) -> None: ...

    async def authorize(self, provider: BrokerId, now: datetime) -> AccountGrant: ...

    async def fetch_account(self, provider: BrokerId, masked_account_id: str) -> AccountData: ...


# Fixed demo labels, matching the frontend broker mock. Not real accounts.
_DEMO_MASKS: dict[BrokerId, str] = {"zerodha": "•••• 4821", "fyers": "•••• 0956"}
_DEMO_NAMES: dict[BrokerId, str] = {"zerodha": "Zerodha (demo)", "fyers": "Fyers (demo)"}
# No `funds_read`: the demo has no funds to report, so that section stays null.
DEMO_CAPABILITIES: tuple[Capability, ...] = (
    "profile_read",
    "holdings_read",
    "positions_read",
    "orders_read",
)
DEMO_SESSION_HOURS = 8


class DemoBrokerAdapter:
    """Simulates broker authorization and sync. Makes no network calls."""

    def providers(self) -> Sequence[ProviderSpec]:
        return tuple(ProviderSpec(p, _DEMO_NAMES[p], DEMO_CAPABILITIES) for p in PROVIDERS)

    def authorize_url(self, provider: str, state: str, callback_path: str) -> str:
        """The app's own callback page with a demo code: no external site."""
        return f"{callback_path}?{urlencode({'state': state, 'code': f'demo-{provider}'})}"

    async def exchange(
        self, provider: str, params: Mapping[str, str], now: datetime
    ) -> AccountGrant:
        if params.get("code") != f"demo-{provider}":
            raise BrokerAuthorizationFailedError("the demo code does not match")
        grant = await self.authorize(_demo_id(provider), now)
        return AccountGrant(
            masked_account_id=grant.masked_account_id,
            scopes=DEMO_CAPABILITIES,
            expires_at=grant.expires_at,
            account_ref=grant.account_ref,
        )

    async def fetch_portfolio(
        self,
        provider: str,
        account_ref: str,
        capabilities: Sequence[Capability],
        now: datetime,
    ) -> PortfolioData:
        # Empty on purpose: no invented positions.
        return PortfolioData(
            account_ref=account_ref,
            holdings=[] if "holdings_read" in capabilities else None,
            positions=[] if "positions_read" in capabilities else None,
            orders=[] if "orders_read" in capabilities else None,
            funds=None,
        )

    async def revoke(self, provider: str, account_ref: str) -> None:
        return None

    async def authorize(self, provider: BrokerId, now: datetime) -> AccountGrant:
        return AccountGrant(
            masked_account_id=_DEMO_MASKS[provider],
            scopes=READ_SCOPES,
            expires_at=now + timedelta(hours=DEMO_SESSION_HOURS),
            account_ref=_DEMO_MASKS[provider],
        )

    async def fetch_account(self, provider: BrokerId, masked_account_id: str) -> AccountData:
        return AccountData(
            masked_account_id=masked_account_id, holdings_count=0, open_orders_count=0
        )


def _demo_id(provider: str) -> BrokerId:
    if provider not in _DEMO_MASKS:
        raise BrokerAuthorizationFailedError("unknown demo provider")
    return provider
