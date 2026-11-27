"""Wire models for /api/v1/alerts, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.alerts.catalog import Environment, Kind, LinkKind, Severity, Source

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AlertLinkOut(_Wire):
    kind: LinkKind
    id: str


class AlertOut(_Wire):
    id: str
    kind: Kind
    source: Source
    severity: Severity
    environment: Environment | None
    title: str
    message: str
    occurred_at: datetime
    created_at: datetime
    acknowledged_at: datetime | None
    link: AlertLinkOut | None


class AlertUnreadOut(_Wire):
    total: int
    critical: int
    warning: int
    info: int


class AlertPageOut(_Wire):
    as_of: datetime
    items: list[AlertOut]
    next_cursor: str | None
    unread: AlertUnreadOut


class AlertInAppOut(_Wire):
    critical: Literal[True] = True
    warning: bool
    info: bool


Channel = Literal["email", "sms", "push"]
UnavailableReason = Literal["PROVIDER_NOT_CONFIGURED", "NO_DESTINATION"]
DeliveryReason = Literal[
    "PROVIDER_ERROR", "DAILY_LIMIT", "NO_DESTINATION", "PROVIDER_NOT_CONFIGURED", "CHANNEL_DISABLED"
]


class AlertChannelOut(_Wire):
    channel: Channel
    available: bool
    unavailable_reason: UnavailableReason | None
    enabled: bool
    min_severity: Severity
    destination_masked: str | None


class AlertPreferencesOut(_Wire):
    in_app: AlertInAppOut
    channels: list[AlertChannelOut]
    updated_at: datetime | None


class AlertChannelIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    channel: Channel
    enabled: bool = Field(strict=True)
    min_severity: Severity


class AlertChannelsIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    channels: list[AlertChannelIn] = Field(min_length=3, max_length=3)


class AlertDeliveryOut(_Wire):
    id: str
    kind: Literal["alert", "test"]
    alert_id: str | None
    channel: Channel
    status: Literal["pending", "sent", "failed", "skipped"]
    status_reason: DeliveryReason | None
    attempts: int
    simulated: bool
    destination_masked: str | None
    created_at: datetime
    sent_at: datetime | None


class AlertDeliveryListOut(_Wire):
    items: list[AlertDeliveryOut]


class AlertInAppIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    warning: bool = Field(strict=True)
    info: bool = Field(strict=True)


class AlertPreferencesIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    in_app: AlertInAppIn
