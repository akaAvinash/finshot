# Backend handoff

Updated 2026-11-24 (UTC), with phase C3. The repository on `main` is the source of truth;
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
| C2: demo backtest jobs | #18 contract, #19 |

## Open

| Phase | PRs |
|---|---|
| C3: paper trading and automatic checks | #20 contract, implementation PR on `feat/paper-risk` (merge after #20) |

## Merge policy

Since 2026-11-24 the owner allows Claude to merge its own backend PRs once
every review thread is resolved, CodeRabbit is clean on the latest commit and
Ruff, strict mypy and the full pytest suite (real Postgres and Redis) pass.
Merge commits, one PR per phase, contract PRs before implementation PRs.
Still pause for infrastructure changes, real credentials, production deploys
and live trading.

## Blockers

- Frontend wiring (Next.js same-origin proxy, switching the broker,
  strategy, backtest and paper clients from the mocks) is Codex's work and
  is not done by the backend.

## Next backend task

Reconciliation and reports (kit order after paper execution and risk:
reconciliation and reports, agents, alerts, hardening). Needs its own
contract PR first.

## Automatic checks and paper trading (C3) notes

- Owner decision (2026-11-24): both strategy checks are automatic server
  rules, with no manual approval or admin role. Thresholds live in
  `app/strategies/rules.py`; migration `0006` holds a frozen copy for
  re-evaluating drafts that existed before it.
- `riskReview` is set on create and save-draft. The backtest check is set by
  the backtest worker, in the transaction that completes a draft run, under
  the strategy row lock (so a save-draft committed meanwhile wins).
- `app/paper/engine.py` holds the pure replay rules; `app/paper/service.py`
  the commands and the tick worker (`PAPER_WORKER_ENABLED`, one demo session
  per running engine every `PAPER_TICK_SECONDS`, claims with `SKIP LOCKED`).
- `paper_trades` and `paper_events` are append-only (trigger). `assign`
  starts a new replay number; the workspace shows only the current replay's
  orders and trades.
- `contracts/auto-trading.openapi.yaml` (the frontend proposal) can be
  removed by the frontend owner once the client uses the main contract.

## Backtests (C2) notes

- `app/backtests/engine.py` is a line-by-line port of
  `frontend/src/lib/backtesting.ts`. `tests/unit/data/backtest_golden.json`
  holds results from the frontend code; regenerate them with Node 22
  (`--experimental-strip-types`) if the frontend engine changes.
- Runs always replay the deterministic demo daily candles, whatever
  `MARKET_DATA_PROVIDER` says.
- An in-process asyncio worker (`BACKTEST_WORKER_ENABLED`, default on) claims
  queued runs with `FOR UPDATE SKIP LOCKED`, so several app processes are
  safe. Runs `running` longer than `BACKTEST_STALE_AFTER_SECONDS` (300) are
  failed as abandoned.
- `contracts/backtesting.openapi.yaml` (the frontend proposal) can be removed
  by the frontend owner once the client uses the main contract.

## Known issues

- Migration `0002` (auth) created its check constraints with doubled names
  (`ck_users_ck_users_phone_format`). Harmless, but a rename migration would
  tidy it. `0003` to `0006` use `op.f()` and have tests for exact names.

## Running checks locally (no Docker needed)

```bash
service postgresql start && service redis-server start
export TEST_DATABASE_URL=postgresql+asyncpg://tradeo:<pw>@localhost:5432/tradeo_test
export TEST_REDIS_URL=redis://localhost:6379/15
ruff check . && ruff format --check . && mypy app && pytest
```

Integration tests truncate tables and flush the Redis database: use throwaway
instances only.
