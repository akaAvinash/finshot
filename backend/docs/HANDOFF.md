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
| #13 Broker endpoints in the API contract | `feat/brokers-contract` | `main` | Contract-only. Awaiting owner review. |
| Phase B2 demo broker connections | `feat/backend-brokers` | `feat/brokers-contract` | Draft. Retarget to `main` after #13 merges. |

Merge order: #13, then B2 (after retargeting to `main`).

## Blockers

- B2 cannot merge before the contract PR #13.
- Frontend wiring (Next.js same-origin proxy, switching the broker client from
  the mock) is Codex's work and is not done by the backend.

## Next backend task

Strategy versions (kit order: strategy configs, then backtest jobs, paper
execution and risk, reconciliation and reports, agents, alerts, hardening).
Needs its own contract PR first. `contracts/strategies.openapi.yaml` holds the
frontend's proposal to start from.

## Running checks locally (no Docker needed)

```bash
service postgresql start && service redis-server start
export TEST_DATABASE_URL=postgresql+asyncpg://tradeo:<pw>@localhost:5432/tradeo_test
export TEST_REDIS_URL=redis://localhost:6379/15
ruff check . && ruff format --check . && mypy app && pytest
```

Integration tests truncate tables and flush the Redis database: use throwaway
instances only.
