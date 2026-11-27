"""Check the market endpoints against contracts/openapi.yaml (the source of truth).

Real responses from the running app are validated with the contract's own
JSON Schemas, and every status code the app returns must be one the contract
declares for that operation."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.market.demo import DemoMarketDataProvider
from app.market.schemas import TIMEFRAMES
from tests.conftest import SettingsFactory
from tests.market_support import (
    MARKET,
    FailingProvider,
    candles_url,
    load_contract,
    market_client,
    schema_errors,
)

CANDLES_PATH = f"{MARKET}/instruments/{{instrumentId}}/candles"


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return load_contract()


def market_operations(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        path: operations["get"]
        for path, operations in contract["paths"].items()
        if path.startswith(f"{MARKET}/")
    }


# Cross-cutting rules the contract states once (X-Request-ID, 500 INTERNAL_ERROR) and
# every route follows through middleware, so the served schema need not repeat them.
CROSS_CUTTING_RESPONSES = {"500"}
REQUEST_ID_HEADER = "X-Request-ID"


def resolved_parameters(
    contract: dict[str, Any], operation: dict[str, Any]
) -> list[dict[str, Any]]:
    """The operation's parameters with `$ref`s resolved, minus the request-ID header."""
    out: list[dict[str, Any]] = []
    for parameter in operation.get("parameters", []):
        if "$ref" in parameter:
            parameter = contract["components"]["parameters"][parameter["$ref"].rsplit("/", 1)[-1]]
        if parameter["in"] == "header" and parameter["name"] == REQUEST_ID_HEADER:
            continue
        out.append(parameter)
    return out


def declared(contract: dict[str, Any], path: str, status: int) -> dict[str, Any]:
    responses = market_operations(contract)[path]["responses"]
    assert str(status) in responses, f"{status} is not declared for {path}"
    response: dict[str, Any] = responses[str(status)]
    if "$ref" in response:
        name = response["$ref"].rsplit("/", 1)[-1]
        response = contract["components"]["responses"][name]
    return response


def schema_name(response: dict[str, Any]) -> str:
    ref: str = response["content"]["application/json"]["schema"]["$ref"]
    return ref.rsplit("/", 1)[-1]


def check(contract: dict[str, Any], path: str, response: Any) -> None:
    spec = declared(contract, path, response.status_code)
    errors = schema_errors(contract, schema_name(spec), response.json())
    assert not errors, errors


def test_contract_lists_three_read_only_market_operations(contract: dict[str, Any]) -> None:
    assert set(market_operations(contract)) == {
        f"{MARKET}/instruments",
        f"{MARKET}/overview",
        CANDLES_PATH,
    }
    for path, operations in contract["paths"].items():
        if path.startswith(f"{MARKET}/"):
            assert set(operations) == {"get"}, path


def test_every_market_operation_is_served(contract: dict[str, Any], client: TestClient) -> None:
    served = client.get("/openapi.json").json()["paths"]
    for path, operation in market_operations(contract).items():
        assert path in served, f"{path} missing from the API"
        assert set(served[path]) == {"get"}
        mine = served[path]["get"]
        assert mine["operationId"] == operation["operationId"]
        assert {
            (p["name"], p["in"], p.get("required", False)) for p in mine.get("parameters", [])
        } == {
            (p["name"], p["in"], p.get("required", False))
            for p in resolved_parameters(contract, operation)
        }
        documented = {code for code in mine["responses"] if code != "422"}
        assert documented == set(operation["responses"]) - CROSS_CUTTING_RESPONSES, path


def test_success_responses_match_contract(contract: dict[str, Any], client: TestClient) -> None:
    check(contract, f"{MARKET}/instruments", client.get(f"{MARKET}/instruments"))
    check(
        contract,
        f"{MARKET}/instruments",
        client.get(f"{MARKET}/instruments", params={"query": "nifty"}),
    )
    check(
        contract,
        f"{MARKET}/instruments",
        client.get(f"{MARKET}/instruments", params={"query": "zzz"}),
    )
    check(contract, f"{MARKET}/overview", client.get(f"{MARKET}/overview"))


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_candles_match_contract_for_every_instrument(
    contract: dict[str, Any], client: TestClient, timeframe: str
) -> None:
    for item in client.get(f"{MARKET}/instruments").json()["instruments"]:
        response = client.get(candles_url(item["id"], timeframe))
        assert response.status_code == 200
        check(contract, CANDLES_PATH, response)


@pytest.mark.parametrize("scenario", ["stale", "empty"])
def test_stale_and_empty_candles_match_contract(
    contract: dict[str, Any], make_settings: SettingsFactory, scenario: Any
) -> None:
    with market_client(make_settings, DemoMarketDataProvider(scenario)) as client:
        check(contract, CANDLES_PATH, client.get(candles_url("NSE:ITC", "5m")))


def test_error_responses_match_contract(
    contract: dict[str, Any], client: TestClient, make_settings: SettingsFactory
) -> None:
    cases = [
        (f"{MARKET}/instruments", client.get(f"{MARKET}/instruments?query={'x' * 101}"), 400),
        (CANDLES_PATH, client.get(candles_url("NSE:TCS", "1w")), 400),
        (CANDLES_PATH, client.get(candles_url("tcs", "1D")), 400),
        (CANDLES_PATH, client.get(candles_url("NSE:NOPE", "1D")), 404),
    ]
    with market_client(make_settings, FailingProvider()) as down:
        cases += [
            (f"{MARKET}/instruments", down.get(f"{MARKET}/instruments"), 503),
            (f"{MARKET}/overview", down.get(f"{MARKET}/overview"), 503),
            (CANDLES_PATH, down.get(candles_url("NSE:TCS", "1D")), 503),
        ]
    for path, response, status in cases:
        assert response.status_code == status, (path, response.text)
        check(contract, path, response)
