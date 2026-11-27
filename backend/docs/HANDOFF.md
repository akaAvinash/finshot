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
| E2: alerts | #30 contract, #31 (migration `0009`) |
| Auth: invite-only sign-in, OTP providers, spend caps, TOTP step-up | #33 contract, #34 (migration `0010`) |
| Settings: profile (display name, timezone) and ending another session | #35 contract, #36 (migration `0011`) |
| Registration by emailed code, then authenticator sign-in | #37 contract, #38 (no migration) |
| Recovery codes for a lost authenticator | #40 contract, #41 (migration `0012`) |
| Setup required until an authenticator is active | #43 contract, this PR (no migration) |
| Owner market stream (mock and Kite feeds, read-only) | #83 contract draft, this PR (no migration); see `docs/MARKET_STREAM.md` |

## Open

None. (Authenticator sign-in is listed as done because it merges with this file.)

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

1. MSG91 provider, blocked on: official Send OTP and Verify OTP API pages, a
   DLT-registered sender ID and template, an MSG91 account, and approval to
   spend. Not built until then (see `docs/AUTH.md`). SMTP credentials are
   also needed before email delivery can be used outside tests.
2. Frontend screens for recovery codes (Codex): create after setup, sign in
   with a code.
3. Further Settings contracts (each its own PR, using step-up): phone change,
   data retention, risk limits. They stay preview-only in the frontend until
   then, and the demo confirmation code is never accepted by the API.
4. Staging upgrade: done 2026-11-25. Staging runs main `e2c7b0e`'s code at
   migration `0012` (TRAD-6, `backend/docs/STAGING_HANDOFF.md`). Rollback:
   stop the API and workers, take a fresh `pg_dump` of the current database,
   restore the pre-upgrade dump, then redeploy the previous release directory
   `~/tradeo-staging/repo-8c8e08a`. Never put `repo-8c8e08a` back without the
   dump: its different `0012` migration would be skipped. The running API image
   is also tagged `tradeo-staging-api:rollback-c700c7e`, so the next upgrade
   can roll back to it.
5. Hardening (kit order).

## Staging (2026-11-25, after the TRAD-6 upgrade)

Pinned-revision handoff, health checks, migrations, rollback and the Dashboard API note: `backend/docs/STAGING_HANDOFF.md` (TRAD-6).

- Staging OTP: after the upgrade, set `OTP_PROVIDER=staging`,
  `OTP_STAGING_FILE`, `OTP_STAGING_ALLOWLIST` (synthetic numbers), then
  `invite add` each number and read codes with `staging-otp` over SSH.
- Reached only from the owner's machine (Tailscale); the cloud sessions have
  no route. The staging tooling (`~/tradeo-staging/repo/backend/staging/ops`)
  lives on the server, not in this repository.
- Runs main `e2c7b0e`'s code at migration `0012`: backend build `c700c7e`,
  frontend build `de9612b`, Postgres, Redis and a Caddy ingress on
  `https://homelab.tail14603a.ts.net:8446` (tailnet only). `./ops verify`
  passes all five checks. The previous release is
  `~/tradeo-staging/repo-8c8e08a`; `~/tradeo-staging/repo-9e5cf9b` (migration
  `0002`) is the one before it. Details: `backend/docs/STAGING_HANDOFF.md`.
- The server-side staging README (`~/tradeo-staging/repo/backend/staging/README.md`,
  not in this repository) still names `9e5cf9b` as the previous release.
  Correct it on the next staging release; it was left untouched in TRAD-6.

## Alert delivery notes (contract 0.13.0)

- Provider-neutral interface `app/alerts/delivery.py` (`NotificationProvider`:
  `configured`, `simulated`, `send(Notification)`). Only `disabled` and `log`
  (simulated: masked log line, sends nothing) exist; settings refuse `log` in
  production. Env: `NOTIFY_EMAIL_PROVIDER`, `NOTIFY_SMS_PROVIDER`,
  `NOTIFY_PUSH_PROVIDER` (`disabled` default), `NOTIFY_WORKER_ENABLED`,
  `NOTIFY_WORKER_POLL_SECONDS` (10), `NOTIFY_LOOKBACK_SECONDS` (3600),
  `NOTIFY_DAILY_LIMIT_PER_CHANNEL` (20), `NOTIFY_TEST_PER_HOUR` (3).
- Destinations resolved at send time: email = active invite's email, SMS = user's
  phone, push = none yet (needs device registration, not in the contract).
- Worker (`app/alerts/delivery_service.py`): enqueue recent alerts per enabled
  channel (partial unique index on alert_id+channel), claim with SKIP LOCKED and
  a lease/backoff (1, 5, 15 min), send outside the transaction, 3 attempts, then
  `failed`. At least once. Tables: `alert_channel_settings`, `alert_deliveries`
  (migration 0018); a purged alert leaves its delivery with `alert_id` null.
- Daily cap rule: every send attempt, first or retry, needs room under
  `NOTIFY_DAILY_LIMIT_PER_CHANNEL` per user and channel, counted as deliveries last
  attempted since 00:00 UTC. A retry over the cap is skipped (`DAILY_LIMIT`).
- A real provider is an owner decision (provider, credentials, spend, and for
  SMS in India a DLT-registered sender and template). Add a class implementing
  the protocol, a new `NOTIFY_*_PROVIDER` value and a branch for it in
  `build_providers` (otherwise the value falls back to disabled); shapes do not change.

### Real email through your own mailbox (SMTP)

- `NOTIFY_EMAIL_PROVIDER=smtp` sends alert email through `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` (server env only, never logged or
  committed). STARTTLS is required: settings refuse `smtp` without all five values
  or with `SMTP_STARTTLS=false`. SMS and push stay disabled or simulated.
- Hard caps, counted per send attempt (retries included) by each attempt's own
  timestamp in `email_send_attempts`, under a mailbox-wide advisory lock: `NOTIFY_EMAIL_DAILY_CAP`
  (50 per UTC day across all users) and `NOTIFY_EMAIL_PER_USER_PER_HOUR` (5). A
  delivery over either is `skipped` with `DAILY_LIMIT` and nothing is sent.
- Before each send the worker atomically re-takes its lease, so a batch that outlives
  its lease cannot send a row another worker has since claimed.
- A send failure shows as `PROVIDER_ERROR` (retries 1, 5, 15 min), then `failed`.
  Logs carry only the exception class, never the server reply, credentials or address.
- Default stays `disabled`. Owner actions: create the mailbox, set the `SMTP_*`
  values and `NOTIFY_EMAIL_PROVIDER=smtp` in the server env yourself, restart the API
  (migration 0019 adds the `email_send_attempts` table).

## Data retention notes (contract 0.13.0)

- `GET`/`PUT /api/v1/settings/data-retention` (`app/retention/`, migration 0017).
  Saving needs step-up. Bounds and default: `DATA_RETENTION_MIN_DAYS` (30),
  `DATA_RETENTION_MAX_DAYS` (730), `DATA_RETENTION_DEFAULT_DAYS` (365); settings
  refuse a default outside the bounds.
- Purge: in-process worker every `RETENTION_PURGE_INTERVAL_SECONDS` (3600; turn off
  with `RETENTION_WORKER_ENABLED=false`) or by hand: `python -m app.retention.service`.
  Deletes alerts, alert deliveries and agent events created
  before `now - period`, per user under an advisory lock. Audit `retention.purged`
  (counts only) when anything was deleted.
- Watermark: `data_retention.purged_through` only moves forward. The alert worker
  (broker expiry, reconciliation mismatch) and the agent worker (cancelled orders,
  finished replays) ignore sources older than it, so a purged alert or event is
  never recorded again. Any new "not yet reported" producer must do the same
  (`app.retention.service.purged_floor`).
- Kept regardless: audit log, paper ledger and reports, strategies/versions/backtests,
  Trade Controls history.

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

- A restricted Redis account (staging uses one) must allow both key prefixes
  `tradeo:rl:*` (counters) and `tradeo:rv:*` (rate-limit reservations, #38),
  and the commands the Lua scripts call: `EVAL`, `GET`, `SET`, `INCR`, `DECR`,
  `PEXPIRE`, `PTTL`, `HGET`, `HSET`, `HINCRBY`, `TIME`. Missing either prefix
  makes `POST /auth/login/totp` and `/auth/login/recovery` return 500 (found
  on staging 2026-11-25; fixed there by widening the ACL). Add a staging
  check that exercises a reservation before the next deploy.
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
