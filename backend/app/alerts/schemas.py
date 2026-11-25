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


class AlertChannelOut(_Wire):
    channel: Literal["email", "sms", "push"]
    available: Literal[False] = False
    enabled: Literal[False] = False


class AlertPreferencesOut(_Wire):
    in_app: AlertInAppOut
    channels: list[AlertChannelOut] = Field(
        default_factory=lambda: [
            AlertChannelOut(channel="email"),
            AlertChannelOut(channel="sms"),
            AlertChannelOut(channel="push"),
        ]
    )
    updated_at: datetime | None


class AlertInAppIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    warning: bool = Field(strict=True)
    info: bool = Field(strict=True)


class AlertPreferencesIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    in_app: AlertInAppIn
