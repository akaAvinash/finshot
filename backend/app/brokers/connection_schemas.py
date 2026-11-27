"""Wire models for /api/v1/broker-connections, camelCase as in
contracts/openapi.yaml (contract 0.11.0)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.brokers.adapter import Capability

ProviderIdStr = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
ConnectionAction = Literal["sync", "disconnect"]
EventAction = Literal["connect", "reconnect", "sync", "disconnect", "expire"]
MAX_EVENTS = 50


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Strict(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ProviderOut(_Wire):
    id: str
    display_name: str
    environment: Literal["DEMO"] = "DEMO"
    capabilities: list[Capability]
    max_connections: int
    available: bool


class ConnectionOut(_Wire):
    connection_id: uuid.UUID
    provider_id: str
    status: Literal["connected", "expired"]
    status_reason: Literal["EXPIRED", "AUTH_INVALIDATED"] | None
    masked_account_id: str
    capabilities: list[Capability]
    connected_at: datetime
    expires_at: datetime
    last_synced_at: datetime | None


class EventOut(_Wire):
    id: str
    connection_id: uuid.UUID
    provider_id: str
    action: EventAction
    at: datetime


class SnapshotOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["DEMO"] = "DEMO"
    as_of: datetime
    providers: list[ProviderOut]
    connections: list[ConnectionOut]
    events: list[EventOut] = Field(max_length=MAX_EVENTS)


class AuthorizationStartIn(_Strict):
    """Exactly one of `providerId` (new connection) or `connectionId`."""

    provider_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    connection_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> AuthorizationStartIn:
        if (self.provider_id is None) == (self.connection_id is None):
            raise ValueError("exactly one of providerId and connectionId")
        return self


class AuthorizationOut(_Wire):
    authorization_id: uuid.UUID
    provider_id: str
    authorize_url: str
    expires_at: datetime


class AuthorizationCallbackIn(_Strict):
    state: str = Field(min_length=16, max_length=256)
    params: dict[str, Any] = Field(max_length=10)

    @model_validator(mode="after")
    def _string_values(self) -> AuthorizationCallbackIn:
        for value in self.params.values():
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError("params values are strings of at most 512 characters")
        return self


class AuthorizationResultOut(_Wire):
    connection_id: uuid.UUID
    snapshot: SnapshotOut


class ConnectionActionIn(_Strict):
    action: ConnectionAction


class PortfolioOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["DEMO"] = "DEMO"
    connection_id: uuid.UUID
    as_of: datetime | None
    holdings: list[dict[str, Any]] | None
    positions: list[dict[str, Any]] | None
    orders: list[dict[str, Any]] | None
    funds: dict[str, Any] | None
