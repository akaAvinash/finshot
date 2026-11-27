"""Paper Trade Controls: per-user limits that can only tighten the engine's
fixed paper ceilings (contracts/openapi.yaml, Trade controls tag).

Pure rules and wire models; storage and locking are in `PaperService`. Amounts
are paise, ratios basis points. Nothing here reaches a broker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictInt
from pydantic.alias_generators import to_camel

from app.paper import engine as rules

Field_ = Literal[
    "lossLimitPaise",
    "tradeLimit",
    "profitLimitPaise",
    "maxConsecutiveLosses",
    "stopLossBps",
    "takeProfitBps",
    "maxRiskPerTradePaise",
    "maxPositionSizeBps",
]
FIELDS: tuple[str, ...] = get_args(Field_)

PROFIT_CAP_CEILING_PAISE = 100_000_000  # ₹10,00,000, the paper capital
MAX_CONSECUTIVE_LOSSES_CEILING = 10
HISTORY_LIMIT = 50


@dataclass(frozen=True)
class Bound:
    minimum: int
    maximum: int
    nullable: bool = False


# The server's inclusive bounds. Configuration, reported on every read.
BOUNDS: dict[str, Bound] = {
    "lossLimitPaise": Bound(1, rules.LOSS_LIMIT_PAISE),
    "tradeLimit": Bound(1, rules.TRADE_LIMIT),
    "profitLimitPaise": Bound(1, PROFIT_CAP_CEILING_PAISE, nullable=True),
    "maxConsecutiveLosses": Bound(0, MAX_CONSECUTIVE_LOSSES_CEILING),
    "stopLossBps": Bound(1, 9_999, nullable=True),
    "takeProfitBps": Bound(1, 10_000, nullable=True),
    "maxRiskPerTradePaise": Bound(1, rules.PER_TRADE_RISK_PAISE),
    "maxPositionSizeBps": Bound(1, rules.BASIS_POINTS),
}

DEFAULTS: dict[str, int | None] = {
    "lossLimitPaise": rules.LOSS_LIMIT_PAISE,
    "tradeLimit": rules.TRADE_LIMIT,
    "profitLimitPaise": None,
    "maxConsecutiveLosses": 0,
    "stopLossBps": None,
    "takeProfitBps": None,
    "maxRiskPerTradePaise": rules.PER_TRADE_RISK_PAISE,
    "maxPositionSizeBps": rules.BASIS_POINTS,
}

# Wire field -> database column.
COLUMNS: dict[str, str] = {
    "lossLimitPaise": "loss_limit_paise",
    "tradeLimit": "trade_limit",
    "profitLimitPaise": "profit_limit_paise",
    "maxConsecutiveLosses": "max_consecutive_losses",
    "stopLossBps": "stop_loss_bps",
    "takeProfitBps": "take_profit_bps",
    "maxRiskPerTradePaise": "max_risk_per_trade_paise",
    "maxPositionSizeBps": "max_position_size_bps",
}


class _Wire(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True
    )


class TradeControlsIn(_Wire):
    """Structural ranges only (the contract's schema). The server's bounds are
    checked separately so they can report every offending field."""

    loss_limit_paise: Annotated[StrictInt, Field(ge=1)]
    trade_limit: Annotated[StrictInt, Field(ge=1)]
    profit_limit_paise: Annotated[StrictInt, Field(ge=1)] | None
    max_consecutive_losses: Annotated[StrictInt, Field(ge=0)]
    stop_loss_bps: Annotated[StrictInt, Field(ge=1, le=9_999)] | None
    take_profit_bps: Annotated[StrictInt, Field(ge=1, le=10_000)] | None
    max_risk_per_trade_paise: Annotated[StrictInt, Field(ge=1)]
    max_position_size_bps: Annotated[StrictInt, Field(ge=1, le=10_000)]

    def values(self) -> dict[str, int | None]:
        return {name: getattr(self, column) for name, column in COLUMNS.items()}


class TradeControlsUpdateIn(_Wire):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    controls: TradeControlsIn


class BoundOut(_Wire):
    minimum: int
    maximum: int
    nullable: bool


class TradeControlsOut(_Wire):
    loss_limit_paise: int
    trade_limit: int
    profit_limit_paise: int | None
    max_consecutive_losses: int
    stop_loss_bps: int | None
    take_profit_bps: int | None
    max_risk_per_trade_paise: int
    max_position_size_bps: int

    @classmethod
    def from_values(cls, values: dict[str, int | None]) -> TradeControlsOut:
        return cls.model_validate({COLUMNS[name]: value for name, value in values.items()})


class TradeControlsBoundsOut(_Wire):
    loss_limit_paise: BoundOut
    trade_limit: BoundOut
    profit_limit_paise: BoundOut
    max_consecutive_losses: BoundOut
    stop_loss_bps: BoundOut
    take_profit_bps: BoundOut
    max_risk_per_trade_paise: BoundOut
    max_position_size_bps: BoundOut


class TradeControlsSettingsOut(_Wire):
    environment: Literal["PAPER"] = "PAPER"
    revision: int = Field(ge=0)
    updated_at: datetime | None
    controls: TradeControlsOut
    defaults: TradeControlsOut
    bounds: TradeControlsBoundsOut


class ChangedFieldOut(_Wire):
    field: Field_
    from_: int | None = Field(serialization_alias="from", validation_alias="from")
    to: int | None


class TradeControlsChangeOut(_Wire):
    revision: int = Field(ge=1)
    changed_at: datetime
    fields: list[ChangedFieldOut] = Field(min_length=1)


class TradeControlsHistoryOut(_Wire):
    changes: list[TradeControlsChangeOut]


def bounds_out() -> TradeControlsBoundsOut:
    return TradeControlsBoundsOut.model_validate(
        {
            COLUMNS[name]: {"minimum": b.minimum, "maximum": b.maximum, "nullable": b.nullable}
            for name, b in BOUNDS.items()
        }
    )


def out_of_bounds(values: dict[str, int | None]) -> list[dict[str, Any]]:
    """One entry per field outside the server's bounds, in contract order."""
    problems: list[dict[str, Any]] = []
    for name in FIELDS:
        value, bound = values[name], BOUNDS[name]
        if value is None:
            ok = bound.nullable
        else:
            ok = bound.minimum <= value <= bound.maximum
        if not ok:
            problems.append(
                {
                    "field": name,
                    "bound": {
                        "minimum": bound.minimum,
                        "maximum": bound.maximum,
                        "nullable": bound.nullable,
                    },
                }
            )
    return problems


def changed_fields(old: dict[str, int | None], new: dict[str, int | None]) -> list[dict[str, Any]]:
    return [
        {"field": name, "from": old[name], "to": new[name]}
        for name in FIELDS
        if old[name] != new[name]
    ]


def limits_for(
    values: dict[str, int | None], version_size_bps: int, version_stop_bps: int
) -> tuple[rules.Limits, int, int]:
    """The engine limits, effective position size and effective stop loss for
    a user's controls and the pinned strategy version."""
    stop = values["stopLossBps"]
    limits = rules.Limits(
        loss_limit_paise=_int(values["lossLimitPaise"]),
        trade_limit=_int(values["tradeLimit"]),
        profit_limit_paise=values["profitLimitPaise"],
        max_consecutive_losses=_int(values["maxConsecutiveLosses"]),
        take_profit_bps=values["takeProfitBps"],
        per_trade_risk_paise=_int(values["maxRiskPerTradePaise"]),
    )
    size = min(version_size_bps, _int(values["maxPositionSizeBps"]))
    return limits, size, version_stop_bps if stop is None else min(version_stop_bps, stop)


def _int(value: int | None) -> int:
    if value is None:
        raise ValueError("a required Trade Control is null")
    return value
