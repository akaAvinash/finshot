"""Regression tests for QA tooling defects found in review (PR #48).

Each test pins one behaviour of the harness, the CI scripts or the oracles, so the
deterministic engine cannot silently weaken.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from decimal import Decimal as D
from pathlib import Path

import pytest

from qa.ai_agent import analysis
from qa.ai_agent.providers import Completion, GuardedLLM, Limits, LLMUnavailable
from qa.config.settings import QaSettings, UnsafeTargetError
from qa.core.contract import Contract
from qa.core.faults import TcpProxy
from qa.core.redaction import redact
from qa.core.totp import uri_exposes_phone
from qa.financial_oracles.oracles import Fill, Side, apply_fills, money, profit_factor, unrealized_pnl
from qa.reporting.results import TestResult, parse_junit
from qa.scripts import morning_report, nightly_candidates, npm_audit_junit
from qa.scripts.dependency_audit import audit_cases

pytestmark = [pytest.mark.suite("framework"), pytest.mark.severity("high")]

SCHEMA = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}


class _Provider:
    name, model = "fake", "fake-1"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def complete(self, system, user, max_tokens, timeout):
        self.calls += 1
        return Completion(self.replies.pop(0), 1000, 200)


def _limits(**kw):
    base = dict(daily_budget_usd=1.0, input_usd_per_mtok=4.0, output_usd_per_mtok=20.0, max_tokens=500)
    return Limits(**{**base, **kw})


# --- gate provenance -------------------------------------------------------------------


@pytest.mark.req("QA-GATE-001")
def test_gate_requires_tested_sha_when_expected_sha_is_given():
    r = [TestResult("qa", "a::b", "passed", 0.0)]
    assert analysis.merge_eligibility(r, required_sources=["qa"], tested_sha=None, expected_sha=None).verdict == (
        "ELIGIBLE"
    ), "local reports without SHAs stay valid"
    gate = analysis.merge_eligibility(r, required_sources=["qa"], tested_sha=None, expected_sha="a" * 40)
    assert gate.verdict == "NOT_ELIGIBLE" and "which commit" in gate.reasons[0]


# --- AI guard --------------------------------------------------------------------------


@pytest.mark.req("QA-AI-005")
def test_corrupt_cache_entry_is_a_miss(tmp_path):
    p = _Provider(['{"ok": true}', '{"ok": true}'])
    llm = GuardedLLM(p, _limits(), tmp_path)
    assert llm.ask_json("r", "s", "data", SCHEMA) == {"ok": True}
    (entry,) = (tmp_path / "cache").glob("*.json")
    entry.write_text('{"ok": tr')  # interrupted write
    assert GuardedLLM(p, _limits(), tmp_path).ask_json("r", "s", "data", SCHEMA) == {"ok": True}
    assert p.calls == 2, "the corrupt entry was discarded and the provider asked again"


@pytest.mark.req("QA-AI-006")
@pytest.mark.parametrize("limit", ["calls", "budget"])
def test_limits_are_checked_before_every_retry(tmp_path, limit):
    p = _Provider(["not json", '{"ok": true}'])
    if limit == "calls":
        llm = GuardedLLM(p, _limits(max_retries=1, max_calls_per_run=1, breaker_threshold=5), tmp_path)
        match = "call limit"
    else:
        # Enough budget for one worst-case attempt, not for two after the first is recorded.
        llm = GuardedLLM(p, _limits(max_retries=1, breaker_threshold=5, daily_budget_usd=0.0165), tmp_path)
        match = "budget"
    with pytest.raises(LLMUnavailable, match=match):
        llm.ask_json("r", "s", "data", SCHEMA)
    assert p.calls == 1, "the retry must not run past a limit"


@pytest.mark.req("QA-AI-006")
def test_breaker_opening_stops_the_retry(tmp_path):
    p = _Provider(["not json", '{"ok": true}'])
    llm = GuardedLLM(p, _limits(max_retries=1, breaker_threshold=1), tmp_path)
    with pytest.raises(LLMUnavailable):
        llm.ask_json("r", "s", "data", SCHEMA)
    assert p.calls == 1, "an open breaker must stop the retry"


# --- disposable-target guard -------------------------------------------------------------


@pytest.mark.req("QA-POL-002")
@pytest.mark.parametrize(
    "query", ["dbname=tradeo", "host=prod.example.invalid", "service=prod", "hostaddr=10.0.0.5", "DBNAME=x"]
)
def test_database_url_query_cannot_redirect_the_target(query):
    s = QaSettings(
        database_url=f"postgresql+asyncpg://u:p@localhost/qa_ok?{query}",
        redis_url="redis://localhost:6379/14",
        backend_python="python",
        artifacts_dir=Path("."),
        allow_destructive=False,
    )
    with pytest.raises(UnsafeTargetError, match="override"):
        s.assert_disposable()


@pytest.mark.req("QA-POL-002")
def test_plain_disposable_url_is_accepted():
    QaSettings(
        database_url="postgresql+asyncpg://u:p@localhost/qa_ok?ssl=disable",
        redis_url="redis://localhost:6379/14",
        backend_python="python",
        artifacts_dir=Path("."),
        allow_destructive=False,
    ).assert_disposable()


# --- contract validator ------------------------------------------------------------------


def _doc(tmp: Path, name: str, required: str) -> Path:
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/api/v1/thing": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}},
                        }
                    }
                }
            }
        },
        "components": {"schemas": {"Thing": {"type": "object", "required": [required]}}},
    }
    p = tmp / f"{name}.yaml"
    p.write_text(json.dumps(doc))
    return p


@pytest.mark.req("QA-FW-002")
def test_validators_are_scoped_to_their_contract(tmp_path):
    a, b = Contract(_doc(tmp_path, "a", "alpha")), Contract(_doc(tmp_path, "b", "beta"))
    assert a.validate("GET", "/api/v1/thing", 200, "application/json", {"alpha": 1}) == []
    assert b.validate("GET", "/api/v1/thing", 200, "application/json", {"alpha": 1}), "b requires beta"
    assert b.validate("GET", "/api/v1/thing", 200, "application/json", {"beta": 1}) == []


# --- fault proxy -------------------------------------------------------------------------


class _Echo:
    def __init__(self):
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.port = self.srv.getsockname()[1]
        self.received = 0
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            while data := conn.recv(4096):
                self.received += len(data)
                conn.sendall(data)


@pytest.mark.slow
@pytest.mark.req("QA-FW-005")
def test_proxy_keeps_idle_connections_open():
    echo = _Echo()
    proxy = TcpProxy("127.0.0.1", echo.port)
    proxy.start()
    try:
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=10) as c:
            c.sendall(b"a")
            assert c.recv(1) == b"a"
            time.sleep(6)  # longer than the 5 s connect timeout
            c.sendall(b"b")
            assert c.recv(1) == b"b", "idle link was dropped by the proxy"
    finally:
        proxy.stop()


@pytest.mark.req("QA-FW-005")
def test_cut_during_connect_never_registers_the_link(monkeypatch):
    echo = _Echo()
    proxy = TcpProxy("127.0.0.1", echo.port)
    real = socket.create_connection
    hook_ran = threading.Event()

    def connect_then_cut(addr, timeout=None):
        conn = real(addr, timeout=timeout)
        hook_ran.set()
        proxy.cut()  # outage starts between the upstream connect and registration
        return conn

    monkeypatch.setattr("qa.core.faults.socket.create_connection", connect_then_cut)
    proxy.start()
    try:
        c = real(("127.0.0.1", proxy.port), timeout=5)  # the real function, not the patched one
        with c:
            c.settimeout(2)
            try:
                c.sendall(b"xyz")
                got = c.recv(3)
            except OSError:
                got = b""
        assert hook_ran.wait(2), "the proxy never reached its upstream connect, so the race was not exercised"
        time.sleep(0.3)
        assert got == b"" and echo.received == 0, "bytes crossed a cut proxy"
    finally:
        proxy.stop()


# --- redaction ---------------------------------------------------------------------------


@pytest.mark.req("QA-FW-003")
@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
        ('{"authorization": "Bearer abc.def.ghi"}', "abc.def.ghi"),
        ("'Authorization': 'Token zz9-secret'", "zz9-secret"),
    ],
)
def test_authorization_credentials_are_fully_redacted(raw, secret):
    assert secret not in redact(raw)


# --- JUnit ingestion ---------------------------------------------------------------------


@pytest.mark.req("QA-AI-001")
def test_nested_suites_count_each_case_once(tmp_path):
    p = tmp_path / "nested.xml"
    p.write_text(
        '<testsuites><testsuite name="outer"><testcase classname="a" name="one"/>'
        '<testsuite name="inner"><testcase classname="b" name="two"/></testsuite></testsuite></testsuites>'
    )
    assert sorted(r.nodeid for r in parse_junit(p)) == ["a::one", "b::two"]


# --- dependency audit --------------------------------------------------------------------


@pytest.mark.req("SEC-DEP-001")
def test_failed_audit_is_never_reported_clean():
    for stdout in ("", "not json", '{"dependencies": []}'):
        cases, failures = audit_cases(2, stdout, "network error")
        assert failures == 1 and "pip-audit-ran" in cases[0], stdout
    vuln = {"dependencies": [{"name": "x", "version": "1", "vulns": [{"id": "V-1", "fix_versions": ["2"]}]}]}
    cases, failures = audit_cases(1, json.dumps(vuln), "")
    assert failures == 1 and "x:V-1" in cases[0], "real findings from a non-zero exit are kept"
    assert audit_cases(0, '{"dependencies": [{"name": "x", "vulns": []}]}', "")[1] == 0


# --- nightly candidate discovery ---------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@qa.tradeo.invalid"}
    env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@qa.tradeo.invalid"}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.req("QA-GATE-004")
def test_integration_merge_chains_two_conflict_free_heads(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    heads = []
    for name in ("a", "b"):
        _git(repo, "checkout", "-q", "-b", name, base)
        (repo / f"{name}.txt").write_text(name)
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", name)
        heads.append(_git(repo, "rev-parse", "HEAD"))
    monkeypatch.chdir(repo)
    ok, why = nightly_candidates.merges_cleanly(base, heads, fetch=False)
    assert ok, why


@pytest.mark.req("QA-GATE-004")
def test_nightly_limit_does_not_make_a_pr_untestable():
    report = [{"pr": n, "testable": True, "status": "test"} for n in range(1, 8)]
    chosen = nightly_candidates.apply_nightly_limit(report, 6)
    assert [e["pr"] for e in chosen] == [1, 2, 3, 4, 5, 6]
    seventh = report[6]
    assert seventh["status"].startswith("not scheduled") and seventh["testable"], "explicit request can still run"


@pytest.mark.req("QA-GATE-004")
def test_open_pr_discovery_follows_pagination(monkeypatch):
    pages = {1: [{"number": n} for n in range(100)], 2: [{"number": n} for n in range(100, 130)]}
    seen = []

    def fake_gh(path, token):
        page = int(path.rsplit("page=", 1)[1])
        seen.append(page)
        return pages.get(page, [])

    monkeypatch.setattr(nightly_candidates, "gh", fake_gh)
    prs = nightly_candidates.open_prs("o/r", "t")
    assert len(prs) == 130 and seen == [1, 2]


# --- financial oracles -------------------------------------------------------------------


@pytest.mark.req("FIN-PNL-001")
def test_cost_basis_is_not_rounded_before_realised_pnl():
    # The average cost 100/3 has no exact decimal form. Closing at 40 then 30 realises
    # (40 - 100/3) + 2 * (30 - 100/3) = 0 exactly; a rounded cost basis leaves a residue.
    fills = [Fill(Side.BUY, 1, D("33")), Fill(Side.BUY, 1, D("33")), Fill(Side.BUY, 1, D("34"))]
    state = apply_fills([*fills, Fill(Side.SELL, 1, D("40")), Fill(Side.SELL, 2, D("30"))])
    assert state.quantity == 0
    assert state.realized_pnl == D("0")


@pytest.mark.req("FIN-PF-001")
def test_profit_factor_accepts_one_shot_iterators():
    assert profit_factor(iter([D("100"), D("-50")])) == D("2")
    assert profit_factor([D("100"), D("-50")]) == D("2")


@pytest.mark.req("FIN-CHG-002")
@pytest.mark.parametrize(("x", "want"), [("1.005", "1.01"), ("-1.005", "-1.01"), ("2.675", "2.68"), ("0.004", "0.00")])
def test_money_half_paise_ties_round_away_from_zero(x, want):
    assert money(D(x)) == D(want)


@pytest.mark.req("FIN-PNL-001")
def test_unrealised_pnl_uses_the_exact_cost_basis():
    # avg = (1.00 + 5 * 1.01) / 6 is not a finite decimal. 3 shares left, marked 0.98:
    # exact unrealised P&L is -0.085, which rounds away from zero to -0.09.
    state = apply_fills([Fill(Side.BUY, 1, D("1.00")), Fill(Side.BUY, 5, D("1.01")), Fill(Side.SELL, 3, D("1.01"))])
    assert state.quantity == 3
    assert money(unrealized_pnl(state, D("0.98"))) == D("-0.09")
    short = apply_fills([Fill(Side.SELL, 1, D("1.00")), Fill(Side.SELL, 5, D("1.01")), Fill(Side.BUY, 3, D("1.01"))])
    # Short mirror: exact -0.065 is a tie and rounds away from zero; a rounded average would give -0.06.
    assert money(unrealized_pnl(short, D("1.03"))) == D("-0.07")


# --- QR URI privacy helper -----------------------------------------------------------------


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-TOTP-002")
def test_uri_privacy_check_sees_a_percent_encoded_full_phone():
    leaked = "otpauth://totp/Tradeo:%2B919876543210?secret=ABCDEFGHIJKLMNOP&issuer=Tradeo"
    assert "+919876543210" not in leaked, "the raw URI alone would hide the encoded number"
    assert "label" in uri_exposes_phone(leaked, "+919876543210")
    masked = "otpauth://totp/Tradeo:%2B91XXXXXX3210?secret=ABCDEFGHIJKLMNOP&issuer=Tradeo"
    assert uri_exposes_phone(masked, "+919876543210") == []


# --- nested JUnit: testsuite root ----------------------------------------------------------


@pytest.mark.req("QA-AI-001")
def test_nested_failure_under_a_testsuite_root_is_not_lost(tmp_path):
    p = tmp_path / "root-suite.xml"
    p.write_text(
        '<testsuite name="outer"><testcase classname="a" name="ok"/>'
        '<testsuite name="inner"><testcase classname="b" name="bad">'
        '<properties><property name="severity" value="critical"/></properties><failure message="x"/></testcase>'
        "</testsuite></testsuite>"
    )
    results = parse_junit(p)
    assert sorted(r.nodeid for r in results) == ["a::ok", "b::bad"]
    gate = analysis.merge_eligibility(results, required_sources=[], tested_sha=None, expected_sha=None)
    assert gate.verdict == "NOT_ELIGIBLE"


# --- incomplete audits block, findings do not -----------------------------------------------


def _gate(cases_xml: str, tmp_path: Path):
    p = tmp_path / "audit.xml"
    p.write_text(f'<testsuites><testsuite name="x">{cases_xml}</testsuite></testsuites>')
    return analysis.merge_eligibility(
        parse_junit(p, source="dependency-audit"),
        required_sources=["dependency-audit"],
        tested_sha=None,
        expected_sha=None,
    )


@pytest.mark.req("SEC-DEP-001")
def test_incomplete_pip_audit_blocks_but_findings_only_warn(tmp_path):
    incomplete, _ = audit_cases(2, "", "network error")
    assert _gate("".join(incomplete), tmp_path).verdict == "NOT_ELIGIBLE"
    vuln = {"dependencies": [{"name": "x", "version": "1", "vulns": [{"id": "V-1", "fix_versions": ["2"]}]}]}
    found, _ = audit_cases(1, json.dumps(vuln), "")
    gate = _gate("".join(found), tmp_path)
    assert gate.verdict == "ELIGIBLE" and gate.warnings, "high findings are non-blocking warnings"


@pytest.mark.req("SEC-DEP-001")
def test_npm_audit_severity_is_kept_and_only_critical_blocks(tmp_path):
    def run(vulns, rc):
        cases, _ = npm_audit_junit.audit_cases(rc, json.dumps({"vulnerabilities": vulns}))
        return _gate("".join(cases), tmp_path)

    high = {"lodash": {"severity": "high", "range": "<4", "via": ["Prototype pollution"]}}
    crit = {"evil": {"severity": "critical", "range": "*", "via": [{"title": "RCE"}]}}
    assert run(high, 1).verdict == "ELIGIBLE" and run(high, 1).warnings
    assert run(crit, 1).verdict == "NOT_ELIGIBLE"
    assert run({}, 0).verdict == "ELIGIBLE"
    broken, _ = npm_audit_junit.audit_cases(1, '{"error": {"code": "ENOAUDIT"}}')
    assert _gate("".join(broken), tmp_path).verdict == "NOT_ELIGIBLE", "a failed npm audit is incomplete, not clean"
    empty, _ = npm_audit_junit.audit_cases(1, "")
    assert _gate("".join(empty), tmp_path).verdict == "NOT_ELIGIBLE"


# --- morning report gate inputs -------------------------------------------------------------

_M = {"label": "pr-9", "checkout_sha": "b" * 40, "merge_sha": "c" * 40, "pr": 9}


def _cmd(**kw):
    args = dict(run_e2e=False, candidate_result="success", current_sha="c" * 40)
    return morning_report.supervisor_cmd(_M, ["a.xml"], "out", "url", **{**args, **kw})


def _after(cmd, flag):
    return cmd[cmd.index(flag) + 1 :]


@pytest.mark.req("QA-GATE-001")
def test_e2e_result_set_is_required_only_when_e2e_ran():
    assert "frontend-e2e" not in _after(_cmd(run_e2e=False), "--required")[:8]
    assert "frontend-e2e" in _after(_cmd(run_e2e=True), "--required")[:8]
    # A candidate whose build failed before Playwright wrote frontend-e2e.xml is not eligible.
    r = [TestResult(s, "a::b", "passed", 0.0) for s in morning_report.REQUIRED]
    gate = analysis.merge_eligibility(
        r, required_sources=morning_report.required_sources(True), tested_sha=None, expected_sha=None
    )
    assert gate.verdict == "NOT_ELIGIBLE" and "frontend-e2e" in gate.reasons[0]


@pytest.mark.req("QA-GATE-003")
def test_cancelled_candidate_is_not_eligible_but_plain_failures_stay_warnings():
    cancelled = _after(_cmd(candidate_result="cancelled"), "--jobs")
    assert json.loads(cancelled[0]) == {"candidate": "cancelled"}
    assert "--jobs" not in _cmd(candidate_result="failure"), "non-critical failures must not block"
    assert "--jobs" not in _cmd(candidate_result="success")
    gate = analysis.merge_eligibility(
        [TestResult("qa", "a::b", "passed", 0.0)],
        required_sources=["qa"],
        tested_sha=None,
        expected_sha=None,
        job_outcomes=json.loads(cancelled[0]),
    )
    assert gate.verdict == "NOT_ELIGIBLE"


@pytest.mark.req("QA-GATE-004")
def test_report_compares_against_the_current_commit_and_fails_closed():
    assert _after(_cmd(current_sha="c" * 40), "--expected-sha")[0] == "c" * 40
    unknown = _after(_cmd(current_sha=None), "--expected-sha")[0]
    gate = analysis.merge_eligibility(
        [TestResult("qa", "a::b", "passed", 0.0)], required_sources=[], tested_sha="c" * 40, expected_sha=unknown
    )
    assert gate.verdict == "NOT_ELIGIBLE", "a failed lookup must not read as current"
    newer = analysis.merge_eligibility(
        [TestResult("qa", "a::b", "passed", 0.0)], required_sources=[], tested_sha="c" * 40, expected_sha="d" * 40
    )
    assert newer.verdict == "NOT_ELIGIBLE" and "stale" in newer.reasons[0]


# --- workflow shell: merge script -----------------------------------------------------------


@pytest.mark.req("QA-GATE-004")
def test_merge_script_stops_at_the_first_failed_fetch(tmp_path):
    script = Path(__file__).parents[2] / "scripts" / "merge_heads.sh"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "f").write_text("x")
    _git(repo, "add", "f")
    _git(repo, "commit", "-qm", "base")
    # `origin` points nowhere, so every fetch fails; the second sha must never be reached.
    _git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))
    log = tmp_path / "attempts"
    wrapper = tmp_path / "git"
    real_git = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    wrapper.write_text(f'#!/bin/bash\ncase " $* " in *" fetch "*) echo "$@" >> {log};; esac\nexec {real_git} "$@"\n')
    wrapper.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FETCH_TOKEN": "t",
        "HEAD_SHA": f"{'a' * 40} {'b' * 40}",
    }
    proc = subprocess.run(["bash", str(script)], cwd=repo, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert len(log.read_text().splitlines()) == 1, "a failed fetch must stop the run before the next head"
    bad = subprocess.run(
        ["bash", str(script)], cwd=repo, env={**env, "HEAD_SHA": "not-a-sha"}, capture_output=True, text=True
    )
    assert bad.returncode == 2
