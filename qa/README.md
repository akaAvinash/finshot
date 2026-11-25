# Tradeo independent QA framework

Black-box quality checks for Tradeo, independent of the product code: the
framework never imports `backend/app`. It starts the backend as a separate
process, drives it over HTTP and the documented operator CLI, and checks every
response against `contracts/openapi.yaml`.

## Run it locally

Requirements: Python 3.12, PostgreSQL 16, Redis 7, `psql` on PATH. The
database and Redis **must be disposable**: the harness drops the database
schema and flushes the Redis DB. A database whose name does not start with
`qa_` is refused.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e 'backend[dev]' -r qa/requirements.txt
createdb qa_tradeo
export QA_DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/qa_tradeo
export QA_REDIS_URL=redis://localhost:6379/14

python -m pytest -c qa/pytest.ini qa/tests -m "not slow"   # PR scope, ~4 min
python -m pytest -c qa/pytest.ini qa/tests                 # everything incl. expiry waits, ~9 min
python -m pytest -c qa/pytest.ini qa/tests/financial qa/tests/framework qa/tests/policy   # no services needed
```

Without `QA_DATABASE_URL`/`QA_REDIS_URL`, service tests are reported as
**blocked** (never passed). Set `QA_REQUIRE_SERVICES=1` (CI does) to fail instead.

## Layout

| Path | What |
|---|---|
| `config/` | Environment-only settings; refuses non-disposable targets |
| `core/sut.py` | Starts the backend (uvicorn), runs alembic and the operator CLI |
| `core/client.py` | Browser-like client: `__Host-` cookie jar, CSRF, contract validation, redacted evidence |
| `core/mail.py` | Local SMTP sink: the backend's real SMTP provider delivers here; failure mode for outages |
| `core/totp.py` | Independent RFC 6238 oracle and a simulated authenticator app |
| `core/faults.py` | TCP fault proxy for Postgres/Redis outages |
| `core/actors.py` | Synthetic people (`+9199…` numbers, `.invalid` emails) |
| `financial_oracles/` | Decimal reference calculations (P&L, charges, sizing, drawdown) |
| `ai_agent/` | Deterministic analysis + optional, budget-capped LLM review |
| `reporting/` | JUnit ingestion and Markdown rendering |
| `scripts/` | Secret scan, dependency audit, nightly candidate discovery, morning report, catalog builder |
| `policies/requirements.csv` | The requirement list (source for `docs/qa/REQUIREMENTS_TRACEABILITY.csv`) |
| `tests/` | authentication, security, reliability, financial, framework, policy |

## Adding a test

Mark it: `@pytest.mark.req("ID")`, `@pytest.mark.severity("critical|high|medium|low")`,
module-level `pytest.mark.suite(...)`, and `critical_gate` if it must pass for
merge. Add the requirement to `policies/requirements.csv`, then
`python qa/scripts/build_catalog.py`. The policy suite fails if the generated
CSVs are stale.

## Reports

```bash
python -m qa.ai_agent.supervisor --junit out/*.xml --out out/report --required backend qa frontend-unit
```

Writes `qa-report.json`, `qa-summary.md` and `defects.md`. See `docs/qa/`.
