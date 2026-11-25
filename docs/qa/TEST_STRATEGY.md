# Test strategy

## Levels and owners

| Level | Where | Owner | Runs |
|---|---|---|---|
| Unit / component | `backend/tests/unit`, `frontend/tests/{unit,component}` | Product teams | PR, main, nightly (reused by QA CI) |
| Backend integration | `backend/tests/integration` (real Postgres/Redis) | Backend | PR, main, nightly |
| Independent API/E2E | `qa/tests/authentication`, `security`, `reliability` | QA | PR (`not slow`), main, nightly (all) |
| Browser E2E | `frontend/tests/e2e` (preview mode) | Frontend | main, nightly |
| Financial oracles | `qa/tests/financial` | QA | every run |
| Static / supply chain | ruff, eslint, tsc, secret scan, pip-audit, npm audit | QA CI | every run |

## Techniques used (with examples)

| Technique | Example |
|---|---|
| Positive / negative | registration succeeds; wrong code 401 |
| Boundary values | phone `+91[6-9]` + 9 digits vs 8/10 digits; OTP 5/6/7 digits; daily loss exactly at Rs 25,000 |
| Equivalence partitioning | uninvited / invited-no-email / invited / has-authenticator numbers |
| Decision table | TOTP sign-in failure causes all map to one 401 body |
| State transition | no authenticator → pending → active → recovered (none) → re-enrolled |
| Property-based (Hypothesis) | P&L conservation, sizing never exceeds risk budget, drawdown bounds |
| Contract | every response validated against OpenAPI 3.1 schemas and documented status codes |
| Concurrency | three parallel logins with one TOTP code → exactly one session |
| Fault injection | Redis / Postgres cut mid-session; SMTP 4xx/5xx |
| Error guessing | hostile JSON (SQL-ish, NUL, arrays, 5000-char numbers) |
| Security | log leakage scan across a full lifecycle; cookie attributes; CSRF variants; enumeration |
| Regression | nightly full run of all suites on main and each open PR |

Not yet used: pairwise (no multi-parameter config surface under test yet), mutation testing
(planned: mutmut on `qa/financial_oracles` and `backend/app/auth` nightly), performance (Locust plan only).

## Test data

Synthetic only: phones `+9199<run><n>`, emails `@qa.tradeo.invalid`, per-run `AUTH_SECRET_KEY`,
SMTP sink credentials generated per run. CI database password is a fixed non-secret string.

## Flakiness policy

No automatic retries in gating runs. A retry may be run separately to collect evidence; the
original failure stays in the report and the test is listed as a flaky candidate.
