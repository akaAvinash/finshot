# Backend handoff

Updated 2026-11-24 (UTC). The repository on `main` is the source of truth;
the development kit is the roadmap.

## Ownership

- `backend/`: Claude. `frontend/`: Codex.
- `contracts/openapi.yaml` changes go in a contract-only PR that the owner
  reviews before the implementation PR merges. Feature PRs never edit the
  contract.

## Done (merged to main)

| Phase | PRs |
|---|---|
| Foundation (FastAPI, Postgres/Alembic, Redis, logging, Docker) | #2 |
| A: auth (OTP, sessions, CSRF, audit) | #4 contract, #7 |
| B1: read-only market data (demo provider) | #10, #12 |
| B2: demo broker connections | #13 contract, #14 |
| C1: strategy drafts and immutable versions | #15 contract, #16 |

## Merge policy

Since 2026-11-24 the owner allows Claude to merge its own backend PRs once
every review thread is resolved, CodeRabbit is clean on the latest commit and
Ruff, strict mypy and the full pytest suite (real Postgres and Redis) pass.
Merge commits, one PR per phase, contract PRs before implementation PRs.
Still pause for infrastructure changes, real credentials, production deploys
and live trading.

## Blockers

- Strategy activation stays blocked (409) until backtest jobs and a risk
  review flow exist. Who approves a risk review is deferred to the risk phase
  (see #15); nothing can set `approved` until then.
- Frontend wiring (Next.js same-origin proxy, switching the broker and
  strategy clients from the mocks) is Codex's work and is not done by the
  backend.

## Next backend task

Backtest jobs (kit order: backtest jobs, then paper execution and risk,
reconciliation and reports, agents, alerts, hardening). Needs its own contract
PR first; `contracts/backtesting.openapi.yaml` holds the frontend's proposal.

## Known issues

- Migration `0002` (auth) created its check constraints with doubled names
  (`ck_users_ck_users_phone_format`). Harmless, but a rename migration would
  tidy it. `0003` and `0004` use `op.f()` and have tests for exact names.

## Running checks locally (no Docker needed)

```bash
service postgresql start && service redis-server start
export TEST_DATABASE_URL=postgresql+asyncpg://tradeo:<pw>@localhost:5432/tradeo_test
export TEST_REDIS_URL=redis://localhost:6379/15
ruff check . && ruff format --check . && mypy app && pytest
```

Integration tests truncate tables and flush the Redis database: use throwaway
instances only.
