# Backend handoff

Updated 2026-11-25 (UTC), with phase E2 (alerts). The repository on `main` is the source of truth;
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
| C3: paper trading and automatic checks | #20 contract, #21 |
| D: paper reports and reconciliation | #22 contract, #24 |
| E1: advisory agents | #25 contract, #27 |
| E2: alerts | #30 contract, this PR (migration `0009`) |

## Open

None. (E2 is listed as done because it merges with this file.)

## Review notes

CodeRabbit leaves a "changes requested" review that stays in force until it
approves a later commit. Once every thread is resolved, a new commit or
`@coderabbitai full review` makes it review again and approve. A change of
base (another PR merging first) dismisses its approval, so ask again then.

## Merge policy

Since 2026-11-24 the owner allows Claude to merge its own backend PRs once
every review thread is resolved, CodeRabbit is clean on the latest commit and
Ruff, strict mypy and the full pytest suite (real Postgres and Redis) pass.
Merge commits, one PR per phase, contract PRs before implementation PRs.
Still pause for infrastructure changes, real credentials, production deploys
and live trading.

## Blockers

- Frontend wiring (Next.js same-origin proxy, switching the broker,
  strategy, backtest, paper and reports clients from the mocks) is Codex's work and
  is not done by the backend.

## Next backend task

1. Staging-only OTP provider (owner decision 2026-11-25): codes for
   allowlisted synthetic numbers written to a server-only file and read with
   SSH (`./ops otp`); only when `APP_ENV=staging`; never SMS or logs.
2. Settings contract PR (profile, timezone; notification preferences are
   already `/api/v1/alerts/preferences`).
3. Staging upgrade, waiting on owner approval and Codex #29: pg_dump, deploy
   main, migrate `0002` to head, real `PUBLIC_ORIGIN`,
   `TRUSTED_PROXY_HOPS=1`, workers on. Rollback: restore the dump and redeploy
   release `9e5cf9b`.
4. Hardening (kit order).

## Staging (read-only check, 2026-11-25)

- Reached only from the owner's machine (Tailscale); the cloud sessions have
  no route. The staging tooling (`~/tradeo-staging/repo/backend/staging/ops`)
  lives on the server, not in this repository.
- Runs release `9e5cf9b` (#9 era) at migration `0002`: api, postgres and redis
  only, `OTP_PROVIDER=disabled`, placeholder `PUBLIC_ORIGIN`
  (`https://tradeo-staging.invalid`), `TRUSTED_PROXY_HOPS` unset (0).
  `./ops verify` passes all four checks.

## Alerts (E2) notes

- `alerts` (migration `0009`): one row per alert, unique
  (user, dedupe key). Rows change only by a first acknowledgement (trigger
  `alerts_acknowledge_only()`); DELETE stays for user cascades.
  `alert_preferences`: one row per user who saved; no row means defaults.
- Producers in the source transaction (`app/alerts/producer.py`, ON CONFLICT
  DO NOTHING): paper halt, risk-limit block (once per replayed session,
  `StepResult.risk_blocked`), cash-cancelled queued buy, stop-loss fill,
  strategy-inactive pause, replay finished; broker disconnect; sign-in;
  logout-all.
- The worker (`ALERT_WORKER_ENABLED`, `ALERT_WORKER_POLL_SECONDS`) is
  stateless: one INSERT ... SELECT per kind for expired broker connections
  (dedupe on connection id and expiry, so a reconnect can alert again) and
  execution-monitor `RECONCILIATION_MISMATCH` agent events. Safe to run in
  several processes.
- `ALERTS_ENABLED=false` returns 503 on every alert endpoint and stops the
  worker; producers keep recording.
- Preferences hide `warning`/`info` at read time (never `critical`); cursors
  embed a fingerprint of filters and preferences. Email, SMS and push are
  reported unavailable.
- No backfill of producer activity: activity before `0009` raises no alert.
  Exceptions, both on the worker's first pass: broker connections already
  expired, and every existing execution-monitor `RECONCILIATION_MISMATCH`
  event that has no alert yet (each alert's `occurredAt` is the event's
  original time). No stale-market
  alert: there is no live feed.

## Advisory agents (E1) notes

- Four deterministic, rule-based agents in `app/agents/rules.py` (pure
  functions, unit tested): market scanner, strategy analyst, risk explainer,
  execution monitor. No language model, network call, broker or credential.
- Advisory only: the worker reads paper tables and writes only
  `agent_events`, `agent_runs` and `agent_worker` (migration `0008`). It
  never locks or writes paper rows, and nothing in `app/paper` reads agent
  tables. The halt and risk engine do not depend on agents.
- The in-process worker (`AGENT_WORKER_ENABLED`, poll
  `AGENT_WORKER_POLL_SECONDS`) claims one user whose `paper_accounts.updated_at`
  differs from `agent_runs.data_as_of`, with FOR UPDATE SKIP LOCKED on the
  `agent_runs` row. Events insert with ON CONFLICT DO NOTHING on
  (user, agent, dedupe key), so re-evaluation never duplicates. When nothing
  is pending it records the pass end in `agent_worker` (one row), which
  health uses to report a stopped worker as `stale`.
- `paper_replay_finishes` (also migration `0008`, append-only) is written by
  the paper engine in the tick that finishes a replay, so the strategy
  analyst summarises every finished replay even if the user reassigns before
  the agents run. Backfill covers only each account's current finished
  replay. The market scanner also uses it: finished replays it has not
  fully scanned are scanned before the current one. A replay abandoned
  part-way (reassigned while unfinished) records no progress, so sessions it
  replayed after the last agent pass are not scanned (known gap).
- An empty claim (SKIP LOCKED) does not end a pass: the worker records the
  pass end only when a non-locking check finds no pending user.
- `agent_events` is append-only (the `paper_ledger_append_only()` trigger).
  Event links are re-verified against the reader's own paper rows on every
  read; links to records that no longer exist or belong to someone else are
  returned as null.
- The scanner threshold is relative (twice the average of the previous five
  close-to-close moves) because the demo candles rarely move over 1% a day.
  With the demo data the stop-loss and session-limit rules rarely fire; the
  integration tests exercise them with inserted ledger rows.
- `AGENTS_ENABLED=false` returns 503 on every agent endpoint and does not
  start the worker. `AGENT_STALE_AFTER_SECONDS` (default 30) sets health's
  deadline.

## Reports (D) notes

- `app/reports/service.py` derives every figure from the paper ledger in one
  REPEATABLE READ transaction: `paper_trades` (fills), `paper_replays`
  (which strategy version each replay used) and `paper_accounts` (open
  position and reconciliation).
- `paper_replays` (migration `0007`) is written by `assign` and is
  append-only. The migration backfills each account's current replay;
  fills of earlier replays stay unattributed (`strategy: null`).
- Dates are IST session dates; the period filter runs in SQL on
  `filled_at` bounds at IST midnight.
- The open position is marked at the close of the last replayed demo
  session. Reconciliation replays only the current replay's ledger from the
  paper capital (cash and quantity).
- The CSV export loads every fill in the period at once; fine for paper
  ledgers, revisit (stream) before real ledgers.
- There is no live broker, so there are no broker statements or tax fields.
  Live reconciliation belongs to a later, separately approved phase.

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

- On every write endpoint (auth, brokers, strategies, backtests, paper), a
  body that is not valid JSON returns `400 INVALID_REQUEST` before the
  session and CSRF checks run, because FastAPI decodes JSON first. Valid JSON
  of the wrong shape still gets `401`/`403` first. Nothing is read or written
  either way. Fix app-wide in the hardening phase (found on #21).

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
