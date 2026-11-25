# Staging demo handoff (TRAD-6, T03)

Demo, sandbox and paper only. Staging is a private Tailscale host that cloud
sessions cannot reach, so every step marked **on staging** runs through a Remote
Control session on the owner's machine, with the owner's approval.

## Pinned revision

| Item | Value | Status |
|---|---|---|
| Candidate repo revision | `2bc5602e0b3a8e556347cddded1c7c1eb215ab0a` (main after QA PR #48) | Fact, from git |
| Backend code | Unchanged by #48. #48 only added `qa/`, `docs/qa/` and workflows. | Fact, from the PR file list |
| Alembic head | `0012` (recovery codes). The migration chain is `0001` to `0012`. | Fact, from `backend/migrations/versions` |
| Frontend revision on staging | **Not yet recorded** | Fill in from staging |
| Backend release on staging | **Not yet recorded.** The last recorded staging release is `9e5cf9b` at `0002` (HANDOFF.md, 2026-11-25 read-only check). | Fill in from staging |
| Preceding release for rollback | Record the release directory or image that is live before the upgrade. | Fill in from staging |

The pin is complete only when the two "on staging" rows above hold real values
and the verification output below is attached to TRAD-6.

## Health checks

| Check | Expected |
|---|---|
| `GET /health/live` | `200 {"status":"ok"}`. The process is up. No dependency check. |
| `GET /health/ready` | `200` with `{"status":"ok","checks":{"database":"ok","redis":"ok"}}`. `503` means Postgres or Redis failed; details are in the logs, not the response. |
| `./ops verify` (staging tooling, lives on the server, not in this repo) | All checks pass. |
| `python backend/scripts/verify_staging.py` | Every check that ran says PASS. Read-only. Needs `STAGING_BASE_URL`, and `STAGING_SESSION_COOKIE` for the signed-in checks. |

The API does **not** report its migration head, so the earlier runbook step
"check that the API reports the new migration head" cannot be done. Use the
database instead (below).

## Migrations

- Migrations run as a separate one-shot job, never on API startup.
- Check the state on staging: `alembic current`. Expect `0012 (head)`.
- Upgrade: `alembic upgrade head` from `0002` applies `0003` to `0012`.
- Downgrade is not part of the rollback. `0004` makes strategy versions
  immutable and several migrations backfill data. Roll back by restoring the
  dump taken before the upgrade.

## Rollback

1. Before the upgrade: `pg_dump` to a root-only file. Record its path and size.
2. Record the current release (directory or image tag).
3. To roll back: stop api and workers of the new release, restore the dump into
   the database, redeploy the recorded release, run `./ops verify`.
4. Confirm `alembic current` matches the restored release.

Exact commands and the release path come from the staging tooling and must be
copied from the server into TRAD-6, not guessed here.

## Verified authenticated responses

Run `verify_staging.py` with a signed-in session cookie and attach its output.
It checks market data, instruments, auth/me, brokers, strategies, paper
trading, paper reports and alerts, and reports status codes and response shape
only. A signed-in account that has not finished authenticator setup gets `403`
on the account routes; finish setup first.

| Area | Endpoint | Auth | Expected on a fresh demo account |
|---|---|---|---|
| Market data | `GET /api/v1/market/overview` | none | `200`, `source: demo`, one quote per catalog instrument |
| Broker demos | `GET /api/v1/brokers/preview` | session | `200`, `ready`, providers `zerodha` and `fyers`, `account: null` until connected |
| Strategies | `GET /api/v1/strategies/preview` | session | `200`, `ready`, empty `strategies` list, `metrics: null` |
| Paper reports | `GET /api/v1/reports/paper` | session | `200`, `status: empty` until a strategy is assigned, then `ready` |

Evidence status at the time of writing: **not collected.** No staging access
from the cloud, and the owner's own HTTPS check (reachable, zero published
database ports) is a statement in chat, not an attached record.

## Dashboard API note (T09, for Codex)

There is no Dashboard endpoint. The current Dashboard cards map to existing
APIs like this. Every response labels its source; demo data must be labelled in
the UI.

| Dashboard card | Use | Available | Not available |
|---|---|---|---|
| Market indices strip | `GET /market/overview`, quotes where the instrument kind is `index` (kind comes from `GET /market/instruments`) | `price`, `change`, `changePercent`, `trend`, `session.status`, `asOf`, `source` | Any live feed. `volume` is null for indices. |
| Watchlist | `GET /market/overview`, equity quotes | Same fields plus `open`, `high`, `low`, `volume` | A per-user watchlist. No endpoint stores one, so the list is the catalog or a fixed client-side choice. |
| Recent trades | `GET /reports/paper`, `data.journal` (newest first, max 500) | `instrument`, `side`, `quantity`, `fillPaise`, `feesPaise`, `pnlPaise`, `filledAt`, `reason`, `strategy` | A trade status or order id beyond `id`. |
| Win rate | `GET /reports/paper`, `summary.winningTrades` over `summary.closedTrades` | Both counts | Nothing. Guard against `closedTrades = 0`. |
| Month P&L | `GET /reports/paper?from=<first of month>&to=<today>` (IST dates), `summary.netPaise` (or `realisedPaise`) | Amounts in integer paise | A percentage return. The report has no capital base. Use `capitalPaise` from `GET /auto-trading/paper` if a percentage is shown. |
| Day P&L | `GET /reports/paper?from=<today>&to=<today>`, the `daily` entry for today, `realisedPaise` | Realised P&L for the session date | "vs previous close" semantics. Unrealised P&L is for the whole open position, not per day. |
| Portfolio value | `GET /auto-trading/paper`, `account.equityPaise` | Cash plus open position at the last replayed close | A live portfolio. Paper only. |
| Portfolio chart | `GET /reports/paper`, `daily` | Daily realised P&L and fees, so a cumulative realised line | An equity curve with mark-to-market history. The API has none. |

Other notes:

- `status: empty` from `/reports/paper` and `/auto-trading/paper` means the
  caller has never assigned a strategy. Show an empty state, not zeros.
- Amounts are integer paise in paper and report responses. Market prices are
  rupees as numbers.
- Report dates are IST session dates of the demo replay, not wall-clock dates.
  "Today" on the Dashboard may have no fills.
- Gaps worth a contract PR if the Dashboard needs them: a day-return
  percentage, an equity history series, a per-user watchlist.
