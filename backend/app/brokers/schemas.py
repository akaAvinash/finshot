"""Wire models for /api/v1/brokers/preview, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.brokers.adapter import BrokerId, Scope

BrokerAction = Literal["connect", "reconnect", "sync", "disconnect"]
MAX_EVENTS = 50


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BrokerActionRequest(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    action: BrokerAction


class BrokerAccountOut(_Wire):
    masked_account_id: str = Field(pattern=r"^•••• [0-9]{4}$")
    connected_at: datetime
    expires_at: datetime
    last_synced_at: datetime | None
    scopes: list[Scope]


class BrokerConnectionOut(_Wire):
    provider: BrokerId
    account: BrokerAccountOut | None


class BrokerEventOut(_Wire):
    id: str
    provider: BrokerId
    action: BrokerAction
    at: datetime


class BrokerSnapshotOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["DEMO"] = "DEMO"
    as_of: datetime
    connections: list[BrokerConnectionOut]
    events: list[BrokerEventOut] = Field(max_length=MAX_EVENTS)


class BrokerResultOut(_Wire):
    """The ready branch of BrokerResult. The demo source never emits
    `stale` or `empty`."""

    status: Literal["ready"] = "ready"
    data: BrokerSnapshotOut
