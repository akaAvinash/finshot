"""Wire models for /api/v1/reports, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

JOURNAL_LIMIT = 500

Reason = Literal["entry", "signal-exit", "stop-loss", "end-of-replay"]


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ReportPeriodOut(_Wire):
    from_: date | None = Field(alias="from")
    to: date | None


class ReportSummaryOut(_Wire):
    realised_paise: int
    unrealised_paise: int
    net_paise: int
    fees_paise: int = Field(ge=0)
    fills: int = Field(ge=0)
    closed_trades: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)


class ReportOpenPositionOut(_Wire):
    instrument: str
    quantity: int = Field(ge=1)
    entry_paise: int = Field(ge=1)
    mark_paise: int = Field(ge=1)
    marked_at: datetime
    unrealised_paise: int


class ReportDayOut(_Wire):
    date: date
    realised_paise: int
    fees_paise: int = Field(ge=0)
    fills: int = Field(ge=1)


class ReportStrategyRefOut(_Wire):
    id: str
    name: str
    version: int = Field(ge=1)


class ReportStrategyOut(_Wire):
    strategy: ReportStrategyRefOut | None
    realised_paise: int
    fees_paise: int = Field(ge=0)
    fills: int = Field(ge=1)
    closed_trades: int = Field(ge=0)


class ReportTradeOut(_Wire):
    id: str
    date: date
    replay: int = Field(ge=1)
    strategy: ReportStrategyRefOut | None
    instrument: str
    side: Literal["Buy", "Sell"]
    quantity: int = Field(ge=1)
    fill_paise: int = Field(ge=1)
    fees_paise: int = Field(ge=0)
    pnl_paise: int
    filled_at: datetime
    reason: Reason


class ReportReconciliationOut(_Wire):
    status: Literal["matched", "mismatch"]
    replay: int = Field(ge=1)
    ledger_cash_paise: int
    account_cash_paise: int = Field(ge=0)
    ledger_quantity: int
    account_quantity: int = Field(ge=0)


class PaperReportOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["PAPER"] = "PAPER"
    as_of: datetime
    period: ReportPeriodOut
    summary: ReportSummaryOut
    open_position: ReportOpenPositionOut | None
    daily: list[ReportDayOut]
    strategies: list[ReportStrategyOut]
    journal: list[ReportTradeOut] = Field(max_length=JOURNAL_LIMIT)
    journal_truncated: bool
    reconciliation: ReportReconciliationOut | None


class ReportReadyOut(_Wire):
    status: Literal["ready"] = "ready"
    data: PaperReportOut


class ReportEmptyOut(_Wire):
    status: Literal["empty"] = "empty"
