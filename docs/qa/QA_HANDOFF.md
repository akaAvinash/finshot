# QA handoff (2026-11-25)

Branch `claude/project-thread-yx1ikc`, based on `main` at `1cabcc0`. Not merged; merging needs owner approval.

## What exists

| Deliverable | Where |
|---|---|
| Deterministic QA engine (black-box backend harness, SMTP sink, RFC 6238 oracle, OpenAPI response validator, TCP fault proxy, redaction) | `qa/core/` |
| Authentication baseline (registration, authenticator, recovery, sessions, CSRF, cookies, throttles, isolation, outages) | `qa/tests/authentication`, `qa/tests/security`, `qa/tests/reliability` |
| Independent financial oracles (Decimal, Hypothesis) | `qa/financial_oracles`, `qa/tests/financial` |
| AI QA agent: supervisor, rule-based analysis, guarded provider layer with deterministic fallback | `qa/ai_agent` |
| Reports: `qa-report.json`, `qa-summary.md`, `defects.md`, morning report | `qa/reporting`, `qa/scripts/morning_report.py` |
| CI: nightly matrix over main and open PRs, morning report, `qa/nightly` status per PR (blocks on critical only) | `.github/workflows/qa-nightly.yml`, `qa-suite.yml` |
| Requirements (151 rows) and generated catalogs | `qa/policies/requirements.csv`, `docs/qa/*.csv` |

## Initial execution results (local cloud sandbox, main `1cabcc0`)

All numbers are from actual runs; nothing unexecuted is counted.

| Suite | Passed | Failed | Notes |
|---|---|---|---|
| backend (existing pytest) | 777 | 0 | 242 s |
| frontend unit (vitest) | 72 | 0 | lint and typecheck clean |
| qa (incl. slow) | 120 | 1 | 432 s; failure is DEF-001 |
| secret-scan | 9 rules | 0 | after allowlisting 2 test/pattern false positives and a confirmed `change-me` placeholder |
| dependency-audit | 0 | 4 | cryptography 46.0.7 advisories (DEF-002) |

Gate verdict on this baseline under the critical-only policy: **ELIGIBLE** (DEF-001 and DEF-002 are listed as non-blocking warnings). Playwright e2e and the frontend build were not run locally.

## Defects

| ID | Severity | Summary |
|---|---|---|
| DEF-001 | low | When Redis or Postgres is down, the 500 `INTERNAL_ERROR` response has no `X-Request-ID` and no security headers, and uvicorn drops the keep-alive connection. Fail-closed behaviour itself is correct. |
| DEF-002 | high (unscored) | `backend/pyproject.toml` pins `cryptography>=43,<47`; installed 46.0.7 has PYSEC-2026-3552/3553/3554 and GHSA-537c-gmf6-5ccf (fixed in 48.0.1 to 50.0.0). Severity is the audit default because pip-audit carries no CVSS; impact on Tradeo's usage is not assessed. Backend-owned fix. |

pip 24.0 advisories in the CI virtualenv are printed as tooling, not gated.

## Coverage gaps

46 requirements are `specified` or `not_implemented` (see the generated traceability CSV). Largest: Universal Broker, Market Data, Auth (7, mainly real SMTP, SMS, performance and UI flows), Backtesting, Platform. MCP gateway does not exist yet. UI auth flows are not covered by Playwright yet.

## Owner actions

1. Review and merge the QA PR; the nightly schedule only runs from the default branch.
2. Decide whether to make `qa/nightly` a required check (repository setting). If required, a PR pushed after the nightly run waits for the next night or a manual run.
3. Optional: set `QA_AI_PROVIDER`, `QA_AI_DAILY_BUDGET_USD` and an API key secret to enable AI notes.
4. Optional: authorise one rate-limited real-SMTP test to a mailbox you own.
5. Ask the backend thread to fix DEF-001 and bump `cryptography` (DEF-002), or accept the risk.

## Next tasks

- Playwright auth journeys against the built frontend with the mock backend.
- Broker adapter conformance suite against the demo adapter (BRK-001).
- Backtest and paper-ledger oracle comparisons via the public API.
- Locust smoke for PERF-001 once targets are confirmed.
- Hostile MCP server fixture when the gateway lands.
