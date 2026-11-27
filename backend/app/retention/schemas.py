"""Wire models for /api/v1/settings/data-retention, camelCase as in the contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Category = Literal["alerts", "alertDeliveries", "agentEvents"]
CATEGORIES: tuple[Category, ...] = ("alerts", "alertDeliveries", "agentEvents")


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DataRetentionBoundsOut(_Wire):
    min_days: int
    max_days: int


class DataRetentionDeletedOut(_Wire):
    alerts: int
    alert_deliveries: int
    agent_events: int


class DataRetentionPurgeOut(_Wire):
    at: datetime
    deleted: DataRetentionDeletedOut


class DataRetentionOut(_Wire):
    retention_days: int
    default_days: int
    bounds: DataRetentionBoundsOut
    categories: list[Category]
    last_purge: DataRetentionPurgeOut | None
    updated_at: datetime | None


class DataRetentionIn(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    retention_days: int = Field(strict=True, ge=1, le=36500)
