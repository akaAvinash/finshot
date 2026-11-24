"""Wire models for /api/v1/backtests/preview, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictInt,
    model_serializer,
)
from pydantic.alias_generators import to_camel

RunStatus = Literal["queued", "running", "completed", "failed"]

MAX_ACTIVE_RUNS = 3
RECENT_RUNS = 20
MIN_CAPITAL_PAISE = 100_000
MAX_CAPITAL_PAISE = 1_000_000_000
MAX_COST_BPS = 500

CostBps = Annotated[StrictInt, Field(ge=0, le=MAX_COST_BPS)]
# Shape only. Calendar validity is checked by the service, so that the
# message matches the frontend's ("Enter valid dates ...").
DateText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BacktestConfig(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=64)
    instrument_id: str = Field(min_length=1, max_length=64)
    # `from` is a Python keyword, so the field is `start` with an explicit alias.
    start: DateText = Field(alias="from")
    end: DateText = Field(alias="to")
    out_of_sample_from: DateText
    capital_paise: Annotated[StrictInt, Field(ge=MIN_CAPITAL_PAISE, le=MAX_CAPITAL_PAISE)]
    fee_bps: CostBps
    slippage_bps: CostBps


class BacktestStrategyOut(_Wire):
    id: str
    name: str
    revision: int | Literal["draft"]
    instrument_id: str
    position_size_bps: int


class BacktestInstrumentOut(_Wire):
    id: str
    symbol: str


class BacktestRunOut(_Wire):
    id: str
    source: Literal["demo"] = "demo"
    environment: Literal["DEMO"] = "DEMO"
    as_of: datetime
    queued_at: datetime
    config: BacktestConfig
    status: RunStatus
    # Stored in wire shape by the worker; omitted from JSON when absent.
    result: dict[str, Any] | None = None
    message: str | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # The contract forbids `result` unless completed and `message` unless
        # failed, so they are left out rather than sent as null. winRateBps
        # inside a result stays null when there were no trades.
        data: dict[str, Any] = handler(self)
        for key in ("result", "message"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class BacktestWorkspaceOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["DEMO"] = "DEMO"
    as_of: datetime
    # Serialized as "from"/"to".
    start: str = Field(serialization_alias="from")
    end: str = Field(serialization_alias="to")
    strategies: list[BacktestStrategyOut]
    instruments: list[BacktestInstrumentOut]
    runs: list[BacktestRunOut]


class BacktestWorkspaceResultOut(_Wire):
    status: Literal["ready", "stale"] = "ready"
    data: BacktestWorkspaceOut
