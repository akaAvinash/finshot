"""Phase C1 strategy endpoints over real PostgreSQL and Redis.

The API cannot pass a backtest or approve a risk review yet, so tests that
exercise activation mark the draft's checks directly in the database, the way
the later backtest and risk phases will."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

BASE = "/api/v1/strategies/preview"
COMMANDS = f"{BASE}/commands"
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
BACKEND_DIR = Path(__file__).resolve().parents[2]

PARAMS: dict[str, Any] = {
    "name": "NIFTY Momentum",
    "description": "Intraday breakouts with confirmation from the trend.",
    "instrument": "NIFTY 50",
    "timeframe": "15m",
    "riskTier": "medium",
    "positionSizeBps": 900,
    "stopLossBps": 125,
}


def _db() -> str:
    return os.environ["TEST_DATABASE_URL"]


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def send(browser: Browser, body: dict[str, Any], **kwargs: Any) -> Any:
    return browser.post(COMMANDS, json=body, **kwargs)


def create(browser: Browser, **overrides: Any) -> dict[str, Any]:
    response = send(browser, {"action": "create", "parameters": {**PARAMS, **overrides}})
    assert response.status_code == 200, response.text
    strategy: dict[str, Any] = response.json()["strategies"][-1]
    return strategy


def approve(strategy_id: str, backtest: str = "passed", review: str = "approved") -> None:
    db_rows(
        _db(),
        "UPDATE strategies SET draft_backtest = :b, draft_risk_review = :r WHERE id = :id",
        b=backtest,
        r=review,
        id=strategy_id,
    )


def find(snapshot: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = [s for s in snapshot["strategies"] if s["id"] == strategy_id]
    (strategy,) = matches
    return strategy


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


def check(contract: dict[str, Any], schema_name: str, payload: Any) -> None:
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = list(validator.iter_errors(payload))
    assert not errors, [e.message for e in errors]


# ------------------------------------------------------------------ auth and CSRF


def test_requires_a_session(browser: Browser, contract: Any) -> None:
    response = browser.get(BASE)
    assert response.status_code == 401
    check(contract, "StrategyError", response.json())
    browser.get_csrf()
    assert send(browser, {"action": "create", "parameters": PARAMS}).status_code == 401


def test_write_requires_session_csrf_token(browser: Browser) -> None:
    browser.login()
    response = send(
        browser, {"action": "create", "parameters": PARAMS}, headers=browser.headers(csrf="")
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert db_rows(_db(), "SELECT 1 FROM strategies") == []


# ---------------------------------------------------------------------- behavior


def test_new_user_has_no_strategies(browser: Browser, clock: FakeClock, contract: Any) -> None:
    browser.login()
    body = browser.get(BASE).json()
    check(contract, "StrategyResult", body)
    assert body["status"] == "ready"
    assert body["data"]["strategies"] == []
    assert parse(body["data"]["asOf"]) == clock.now


def test_create_makes_an_unreviewed_draft(browser: Browser, contract: Any) -> None:
    browser.login()
    response = send(
        browser,
        {
            "action": "create",
            "parameters": {**PARAMS, "name": "  Spaced name  ", "description": "  d  "},
        },
    )
    assert response.status_code == 200, response.text
    check(contract, "StrategySnapshot", response.json())
    (strategy,) = response.json()["strategies"]
    assert strategy["status"] == "draft"
    assert strategy["versions"] == []
    assert strategy["metrics"] is None
    assert strategy["draft"]["backtest"] == "unavailable"
    assert strategy["draft"]["riskReview"] == "pending"
    assert strategy["draft"]["parameters"] == {**PARAMS, "name": "Spaced name", "description": "d"}
    audit = db_rows(_db(), "SELECT action, resource FROM audit_events WHERE action LIKE 'strat%'")
    assert audit == [{"action": "strategy.create", "resource": f"strategy:{strategy['id']}"}]


def test_activation_needs_backtest_and_risk_review(browser: Browser) -> None:
    browser.login()
    strategy = create(browser)
    for backtest, review in [
        ("unavailable", "pending"),
        ("passed", "pending"),
        ("failed", "approved"),
        ("passed", "rejected"),
    ]:
        approve(strategy["id"], backtest, review)
        response = send(browser, {"action": "activate", "id": strategy["id"]})
        assert response.status_code == 409, (backtest, review)
        assert response.json()["code"] == "STRATEGY_CONFLICT"
    assert db_rows(_db(), "SELECT 1 FROM strategy_versions") == []
    assert find(browser.get(BASE).json()["data"], strategy["id"])["status"] == "draft"


def test_version_lifecycle(browser: Browser, clock: FakeClock, contract: Any) -> None:
    browser.login()
    strategy = create(browser)
    sid = strategy["id"]
    approve(sid)

    clock.advance(60)
    active = send(browser, {"action": "activate", "id": sid})
    assert active.status_code == 200, active.text
    check(contract, "StrategySnapshot", active.json())
    s = find(active.json(), sid)
    assert s["status"] == "active" and s["draft"] is None
    assert s["versions"] == [
        {
            "number": 1,
            "activatedAt": s["versions"][0]["activatedAt"],
            "parameters": PARAMS,
            "backtest": "passed",
            "riskReview": "approved",
        }
    ]
    assert parse(s["versions"][0]["activatedAt"]) == clock.now
    (row,) = db_rows(_db(), "SELECT parameters, parameters_hash FROM strategy_versions")
    canonical = json.dumps(row["parameters"], sort_keys=True, separators=(",", ":"))
    assert row["parameters_hash"] == hashlib.sha256(canonical.encode()).hexdigest()

    assert send(browser, {"action": "activate", "id": sid}).status_code == 409  # already active

    # A replacement draft while active keeps the strategy running version 1.
    edited = send(
        browser, {"action": "save-draft", "id": sid, "parameters": {**PARAMS, "stopLossBps": 150}}
    ).json()
    s = find(edited, sid)
    assert s["status"] == "active" and len(s["versions"]) == 1
    assert s["draft"]["backtest"] == "unavailable" and s["draft"]["riskReview"] == "pending"

    paused = find(send(browser, {"action": "pause", "id": sid}).json(), sid)
    assert paused["status"] == "paused"
    assert send(browser, {"action": "pause", "id": sid}).status_code == 409

    # Paused with an unreviewed draft: activation is blocked.
    assert send(browser, {"action": "activate", "id": sid}).status_code == 409
    approve(sid)
    clock.advance(60)
    s = find(send(browser, {"action": "activate", "id": sid}).json(), sid)
    assert [v["number"] for v in s["versions"]] == [1, 2]
    assert s["versions"][1]["parameters"]["stopLossBps"] == 150
    assert s["versions"][0]["parameters"]["stopLossBps"] == 125  # history unchanged


def test_paused_strategy_without_draft_reactivates_same_version(browser: Browser) -> None:
    browser.login()
    sid = create(browser)["id"]
    approve(sid)
    send(browser, {"action": "activate", "id": sid})
    send(browser, {"action": "pause", "id": sid})
    s = find(send(browser, {"action": "activate", "id": sid}).json(), sid)
    assert s["status"] == "active"
    assert [v["number"] for v in s["versions"]] == [1]


def test_save_draft_resets_checks(browser: Browser) -> None:
    browser.login()
    sid = create(browser)["id"]
    approve(sid)
    s = find(send(browser, {"action": "save-draft", "id": sid, "parameters": PARAMS}).json(), sid)
    assert (s["draft"]["backtest"], s["draft"]["riskReview"]) == ("unavailable", "pending")


def test_pause_requires_active(browser: Browser) -> None:
    browser.login()
    sid = create(browser)["id"]
    response = send(browser, {"action": "pause", "id": sid})
    assert response.status_code == 409


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "00000000-0000-4000-8000-000000000000"])
def test_unknown_ids_are_404(browser: Browser, bad_id: str) -> None:
    browser.login()
    for body in (
        {"action": "activate", "id": bad_id},
        {"action": "pause", "id": bad_id},
        {"action": "save-draft", "id": bad_id, "parameters": PARAMS},
    ):
        response = send(browser, body)
        assert response.status_code == 404
        assert response.json()["code"] == "STRATEGY_NOT_FOUND"


def test_users_cannot_see_or_change_each_others_strategies(
    make_app: Callable[..., TestClient],
) -> None:
    client = make_app()
    first, second = Browser(client), Browser(client)
    first.login()
    second.login(phone=OTHER_PHONE)
    sid = create(first)["id"]
    approve(sid)
    assert second.get(BASE).json()["data"]["strategies"] == []
    for body in (
        {"action": "activate", "id": sid},
        {"action": "save-draft", "id": sid, "parameters": PARAMS},
    ):
        assert send(second, body).status_code == 404
    s = find(first.get(BASE).json()["data"], sid)
    assert s["status"] == "draft" and s["draft"]["backtest"] == "passed"


@pytest.mark.parametrize(
    "body",
    [
        {"action": "create", "parameters": {**PARAMS, "name": "  ab  "}},
        {"action": "create", "parameters": {**PARAMS, "name": "x" * 65}},
        {"action": "create", "parameters": {**PARAMS, "description": "d" * 241}},
        {"action": "create", "parameters": {**PARAMS, "instrument": "TCS"}},
        {"action": "create", "parameters": {**PARAMS, "timeframe": "1m"}},
        {"action": "create", "parameters": {**PARAMS, "riskTier": "extreme"}},
        {"action": "create", "parameters": {**PARAMS, "positionSizeBps": 0}},
        {"action": "create", "parameters": {**PARAMS, "positionSizeBps": 10_001}},
        {"action": "create", "parameters": {**PARAMS, "stopLossBps": 9.5}},
        {"action": "create", "parameters": {**PARAMS, "stopLossBps": "125"}},
        {"action": "create", "parameters": {**PARAMS, "stopLossBps": True}},
        {"action": "create", "parameters": {**PARAMS, "extra": 1}},
        {"action": "create", "parameters": {k: v for k, v in PARAMS.items() if k != "name"}},
        {"action": "create"},
        {"action": "delete", "id": "x"},
        {"action": "activate"},
        {"action": "activate", "id": ""},
        {"action": "pause", "id": "x", "parameters": PARAMS},
        {},
    ],
)
def test_invalid_commands_are_400(browser: Browser, body: dict[str, Any]) -> None:
    browser.login()
    response = send(browser, body)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_REQUEST"
    assert db_rows(_db(), "SELECT 1 FROM strategies") == []


def test_strategy_limit_holds_under_concurrency(client: TestClient) -> None:
    browser = Browser(client)
    browser.login()
    user_id = db_rows(_db(), "SELECT id FROM users")[0]["id"]
    db_rows(
        _db(),
        "INSERT INTO strategies (user_id, status, draft_parameters, draft_backtest,"
        " draft_risk_review, created_at, updated_at)"
        " SELECT :u, 'draft', CAST(:p AS jsonb), 'unavailable', 'pending', now(), now()"
        " FROM generate_series(1, 98)",
        u=user_id,
        p=json.dumps(
            {
                "name": "Seeded",
                "description": "",
                "instrument": "SBIN",
                "timeframe": "1D",
                "risk_tier": "low",
                "position_size_bps": 1,
                "stop_loss_bps": 1,
            }
        ),
    )
    active = browser.activate()
    headers = {
        **browser.headers(),
        "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
    }
    active.cookies.clear()

    def attempt(_: int) -> int:
        response = active.post(
            COMMANDS, json={"action": "create", "parameters": PARAMS}, headers=headers
        )
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(8)))
    assert statuses.count(200) == 2
    assert statuses.count(409) == 6
    assert db_rows(_db(), "SELECT count(*) AS n FROM strategies")[0]["n"] == 100


def test_disabled_is_503(make_app: Callable[..., TestClient]) -> None:
    browser = Browser(make_app(strategies_enabled=False))
    browser.login()
    for response in (browser.get(BASE), send(browser, {"action": "create", "parameters": PARAMS})):
        assert response.status_code == 503
        assert response.json()["code"] == "STRATEGY_UNAVAILABLE"


# ---------------------------------------------------------------- contract, DB


def test_every_contract_strategy_operation_is_implemented(contract: Any, browser: Browser) -> None:
    served = browser.get("/openapi.json").json()["paths"]
    for path, operations in contract["paths"].items():
        if not path.startswith("/api/v1/strategies/"):
            continue
        assert path in served, f"{path} missing from the API"
        for method in operations:
            assert method in served[path], f"{method.upper()} {path} missing"


def test_error_bodies_match_contract(browser: Browser, contract: Any) -> None:
    browser.login()
    check(contract, "StrategyError", send(browser, {}).json())
    check(contract, "StrategyError", send(browser, {"action": "pause", "id": "x"}).json())
    sid = create(browser)["id"]
    check(contract, "StrategyError", send(browser, {"action": "pause", "id": sid}).json())


def test_versions_are_immutable_in_the_database(browser: Browser) -> None:
    browser.login()
    sid = create(browser)["id"]
    approve(sid)
    send(browser, {"action": "activate", "id": sid})
    with pytest.raises(Exception, match="immutable"):
        db_rows(_db(), "UPDATE strategy_versions SET number = 7")
    with pytest.raises(Exception, match="draft_complete"):
        db_rows(_db(), "UPDATE strategies SET draft_backtest = 'passed'")
    # Deleting the user still cascades through the versions.
    db_rows(_db(), "DELETE FROM users")
    assert db_rows(_db(), "SELECT 1 FROM strategy_versions") == []
    assert db_rows(_db(), "SELECT 1 FROM strategies") == []


def test_strategy_migration_rolls_back_and_forward(db_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = db_url
    tables = {"strategies", "strategy_versions"}

    def present() -> set[str]:
        rows = db_rows(db_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    assert tables <= present()
    command.downgrade(cfg, "0003")
    assert not (tables & present())
    assert {"broker_connections", "users"} <= present()
    functions = db_rows(
        db_url, "SELECT 1 FROM pg_proc WHERE proname = 'strategy_versions_immutable'"
    )
    assert functions == []
    command.upgrade(cfg, "head")
    assert tables <= present()


def test_check_constraints_keep_their_intended_names() -> None:
    rows = db_rows(
        _db(),
        "SELECT conname FROM pg_constraint WHERE contype = 'c'"
        " AND conrelid::regclass::text IN ('strategies', 'strategy_versions')",
    )
    assert {r["conname"] for r in rows} == {
        "ck_strategies_status_valid",
        "ck_strategies_draft_backtest_valid",
        "ck_strategies_draft_risk_review_valid",
        "ck_strategies_draft_complete",
        "ck_strategy_versions_number_positive",
        "ck_strategy_versions_hash_format",
    }


def test_concurrent_activations_create_one_version(client: TestClient) -> None:
    browser = Browser(client)
    browser.login()
    sid = create(browser)["id"]
    approve(sid)
    active = browser.activate()
    headers = {
        **browser.headers(),
        "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
    }
    active.cookies.clear()

    def attempt(_: int) -> int:
        response = active.post(COMMANDS, json={"action": "activate", "id": sid}, headers=headers)
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(4)))
    assert statuses.count(200) == 1
    assert statuses.count(409) == 3
    assert db_rows(_db(), "SELECT number FROM strategy_versions") == [{"number": 1}]
    (row,) = db_rows(_db(), "SELECT status, draft_parameters FROM strategies")
    assert row == {"status": "active", "draft_parameters": None}
    activations = db_rows(_db(), "SELECT 1 FROM audit_events WHERE action = 'strategy.activate'")
    assert len(activations) == 1


def test_snapshot_reads_one_consistent_state(browser: Browser) -> None:
    """An activation committed between the snapshot's two reads must not show
    the draft and the new version together."""
    browser.login()
    sid = create(browser)["id"]
    service = browser.client.app.state.strategies  # type: ignore[attr-defined]
    stored = json.dumps(
        {
            "name": PARAMS["name"],
            "description": PARAMS["description"],
            "instrument": PARAMS["instrument"],
            "timeframe": PARAMS["timeframe"],
            "risk_tier": PARAMS["riskTier"],
            "position_size_bps": PARAMS["positionSizeBps"],
            "stop_loss_bps": PARAMS["stopLossBps"],
        }
    )

    def commit_activation() -> None:
        sql = (
            "WITH s AS (UPDATE strategies SET status = 'active', draft_parameters = NULL,"
            " draft_backtest = NULL, draft_risk_review = NULL WHERE id = :id"
            " RETURNING id, user_id)"
            " INSERT INTO strategy_versions"
            " (strategy_id, user_id, number, parameters, parameters_hash, activated_at)"
            " SELECT id, user_id, 1, CAST(:p AS jsonb), repeat('a', 64), now() FROM s"
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(db_rows, _db(), sql, id=sid, p=stored).result()

    service._between_snapshot_reads = commit_activation
    try:
        before = find(browser.get(BASE).json()["data"], sid)
    finally:
        service._between_snapshot_reads = None
    assert before["status"] == "draft" and before["draft"] is not None
    assert before["versions"] == []
    after = find(browser.get(BASE).json()["data"], sid)
    assert after["status"] == "active" and after["draft"] is None
    assert [v["number"] for v in after["versions"]] == [1]
