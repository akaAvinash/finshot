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

## Open

| PR | Branch | Base | Status |
|---|---|---|---|
| #13 Broker endpoints in the API contract | `feat/brokers-contract` | `main` | Contract-only. CodeRabbit findings fixed. Awaiting owner review. |
| #14 Phase B2 demo broker connections | `feat/backend-brokers` | `feat/brokers-contract` | Draft. CodeRabbit's second round fixed in f910710 (fresh-session result read, stricter no-write test). Retarget to `main` after #13 merges. |
| #15 Strategy endpoints in the API contract | `feat/strategies-contract` | `feat/backend-brokers` | Contract-only, draft (stacked to avoid `openapi.yaml` conflicts). Awaiting owner review. |
| #16 Phase C1 strategy drafts and versions | `feat/backend-strategies` | `feat/strategies-contract` | Draft. Same fresh-session fix (82afaa1). |

Merge order: #13 → #14 → #15 → #16. Retarget each to `main` after the one
before it merges.

## Blockers

- Each PR in the stack depends on the one before it.
- Strategy activation stays blocked (409) until backtest jobs and a risk
  review flow exist. Who approves a risk review is an open product decision.
- Frontend wiring (Next.js same-origin proxy, switching the broker client from
  the mock) is Codex's work and is not done by the backend.

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
