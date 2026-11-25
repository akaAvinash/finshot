# QA master plan

Owner: independent QA (separate from Claude backend and Codex frontend work).
Scope: demo, sandbox and paper only. No live orders, no production, no real broker connectivity.

## Principles

1. Deterministic tests decide outcomes. AI output is advice and never overrides a failed test.
2. Expected values never come from the code under test (`qa/` cannot import `backend/app`; policy test enforces it).
3. Unimplemented features are *specified* or *not implemented* in the traceability matrix, never "passed".
4. Failed, cancelled, stale, missing or skipped-mandatory results do not count as a pass.
5. Product defects are reported, not fixed by QA; QA framework defects are fixed in `qa/`.

## Phases

| Phase | Goal | Acceptance | Status (25 Nov 2026) |
|---|---|---|---|
| 0 Audit | Know what exists | Audit report | Done: `QA_AUDIT_REPORT.md` |
| 1 Foundation | Reusable black-box framework | Starts backend, validates contract, self-tests pass | Done |
| 2 Auth qualification | Independent auth E2E (API level) | Every implemented auth rule has a passing or failing test with evidence | Done for API level; browser journey (AUTH-UI-001) specified |
| 3 AI agent MVP | Ingest, analyse, report, deterministic fallback | Works with no provider; guardrails tested | Done |
| 4 Continuous QA | PR, main, nightly, manual workflows | Workflows lint-clean; first run on GitHub | Written, actionlint clean; first GitHub run happens on the PR |
| 5 Baseline regression | Pinned candidate fully run | Report with real numbers | Done locally at `1cabcc0` (see `QA_HANDOFF.md`) |
| 6 Expansion | Engines as they land | Traceability rows move from specified to automated | Ongoing |

## Next expansion order

1. Financial cross-checks against the live API (paper ledger, reports CSV, backtest metrics) using the oracles.
2. Authorization route inventory from the contract (every non-auth operation: 401 / setup / CSRF).
3. Browser auth journey in Playwright against the real backend (not preview mode).
4. Broker adapter conformance suite (runs on demo adapters now, every real adapter later).
5. Locust baseline and ZAP baseline in the nightly run.
