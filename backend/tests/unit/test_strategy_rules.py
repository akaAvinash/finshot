"""Pure strategy rules (no database)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.strategies.schemas import StrategyCommand, StrategyParameters
from app.strategies.service import activation_blocker, parameters_hash

PARAMS = {
    "name": "NIFTY Momentum",
    "description": "",
    "instrument": "NIFTY 50",
    "timeframe": "15m",
    "riskTier": "medium",
    "positionSizeBps": 900,
    "stopLossBps": 125,
}


def test_only_passed_and_approved_can_activate() -> None:
    assert activation_blocker("passed", "approved") is None
    for backtest, review in [
        ("unavailable", "pending"),
        ("failed", "approved"),
        ("passed", "pending"),
        ("passed", "rejected"),
        (None, None),
    ]:
        assert activation_blocker(backtest, review)


def test_parameters_hash_is_stable_and_order_independent() -> None:
    a = parameters_hash({"a": 1, "b": "x"})
    assert a == parameters_hash({"b": "x", "a": 1})
    assert len(a) == 64 and a != parameters_hash({"a": 2, "b": "x"})


def test_command_union_routes_on_action() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(StrategyCommand)
    assert type(adapter.validate_python({"action": "pause", "id": "s"})).__name__ == (
        "StatusCommand"
    )
    with pytest.raises(ValidationError):
        adapter.validate_python({"action": "pause"})


def test_names_are_trimmed_before_length_checks() -> None:
    assert StrategyParameters.model_validate({**PARAMS, "name": "  abc "}).name == "abc"
    with pytest.raises(ValidationError):
        StrategyParameters.model_validate({**PARAMS, "name": "  ab  "})
