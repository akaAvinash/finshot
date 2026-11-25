# Staging demo handoff (TRAD-6, T03)

Demo, sandbox and paper only. Staging is a private Tailscale host that cloud
sessions cannot reach, so every step marked **on staging** runs through a Remote
Control session on the owner's machine, with the owner's approval.

## Pinned revision

Recorded 2026-11-25 by a read-only check on the staging host. Nothing was changed.

| Item | Value | Status |
|---|---|---|
| Backend live on staging | `c700c7e37084d5d33760913edeb1c8da4466fdfc` (#45), release dir `~/tradeo-staging/repo`, image `tradeo-staging-api:local` (10570d619226, built 2026-11-25 14:45 UTC) | Fact, from the host |
| Backend vs main | `c700c7e` is on main. Against main `2bc5602`, `backend/` differs only by `docs/HANDOFF.md`. Staging runs main's backend code. | Fact, from `git diff` |
| Frontend live on staging | image label `9675ec05eb0975de4b1cb77080e69016bed74986` (image 0a9e423d4671), from branch `codex/account-settings` | Fact, from the host |
| Frontend vs main | `9675ec0` is not an ancestor of main (#47 landed as the squash `1cabcc0`), but `git diff 9675ec0 origin/main -- frontend` is empty. The frontend tree equals main's. | Fact, from `git diff` |
| Alembic head, live DB | `0012`, from `SELECT version_num FROM alembic_version` in a read-only transaction. Equals the head in this repo (`0012_recovery_codes`). | Fact, from the host |
| Preceding backend release | `~/tradeo-staging/repo-8c8e08a` (`8c8e08a1d88460a8481918a955bf9e03d119439a`), then `~/tradeo-staging/repo-9e5cf9b` (migration 0002). Tarballs kept. | Fact, from the host |
| Rollback frontend image | `tradeo-staging-frontend:rollback-9675ec05...`, which is the build of `36145d11a8b75d467ec782452f89b234a6f41a77` (on main, #44) | Fact, from the host |
| Rollback API image | None. The API image has only the `:local` tag. | Fact, from the host |

The Settings and recovery frontend and the c700c7e backend are what the demo
handoff runs on. Nothing needs deploying for T03 unless the owner wants the
doc-only commits on main.

## Health checks

Evidence from the staging host. Inside the api container (`http://127.0.0.1:8000`):

| Check | Result |
|---|---|
| `GET /health/live` | `200 {"status":"ok"}` |
| `GET /health/ready` | `200`, status ok, database ok, redis ok |
| `GET /api/v1/market/overview` | `200`, `source: demo`, asOf `2026-11-23T10:00:00Z`, 12 quotes |
| `GET /api/v1/market/instruments` | `200`, 12 instruments |
| Frontend `/login` inside the container, and through the ingress at `127.0.0.1:18446` | `200` and `200` |

Through the tailnet origin `https://homelab.tail14603a.ts.net:8446`, `/health/live`,
`/health/ready`, `/api/v1/market/overview` and `/api/v1/market/instruments`
all return **404**. The ingress sends everything to the frontend, and at
`9675ec0` the frontend proxies only `/api/v1/auth/*`, `/api/v1/alerts*`,
`/api/v1/settings/profile` and `/api/v1/reports/paper/trades.csv`.
Port `127.0.0.1:8000` on the host belongs to an unrelated container, not to Tradeo.

**Consequence for T09, T10 and T11:** Dashboard, Brokers and Strategies cannot
reach `market/*`, `brokers/preview`, `strategies/preview`, `auto-trading/paper`
or `reports/paper` (JSON) through the staging origin until the frontend proxy
(or the ingress) routes them to the API. That is frontend work (Codex) or an
infra change (owner approval), not a backend change. Also, `/health/*` is not
reachable from outside; probe it inside the host.

The API publishes no host port, so run the smoke script inside the API
container. Unauthenticated run, 2026-11-25 (script fed on stdin, GET only):

```
PASS  /health/live  http=200  keys=['status'] status=ok
PASS  /health/ready  http=200  keys=['checks', 'status'] status=ok
PASS  /api/v1/market/overview  http=200  keys=['asOf', 'quotes', 'session', 'source'] source=demo quotes[]=12
PASS  /api/v1/market/instruments  http=200  keys=['instruments'] instruments[]=12
SKIP  (six signed-in checks, no session cookie)
0 failed
```

Every signed-in route exists on the live API: without a cookie, `auth/me`,
`brokers/preview`, `strategies/preview`, `auto-trading/paper`, `reports/paper`
and `alerts` each return `401 UNAUTHENTICATED` (not 404).

Full `./ops verify`, run by the owner on 2026-11-25 (it inserts synthetic
rows and updates `users.updated_at`, so it writes to the staging database):

```
API readiness and CSRF endpoint passed
PostgreSQL app reads/writes, DDL denial and credential denial passed
Redis app commands, restricted ACL and credential denial passed
Alembic 0012, SCRAM verifiers, HBA, backup access and test DB separation passed
Frontend and ingress passed
```

`SELECT version_num FROM alembic_version` afterwards: `0012`.

## Ports

Postgres (5432), Redis (6379), the API (8000) and the frontend publish no host
ports. The ingress publishes `8080/tcp` on `127.0.0.1:18446` only, and
`tailscale serve` exposes it as `https://homelab.tail14603a.ts.net:8446`,
tailnet only.

## Migrations

- Migrations run as a separate one-shot job, never on API startup.
- The API does not report its migration head. Read it from the database:
  `SELECT version_num FROM alembic_version` (read-only), or `alembic current`
  in the migrate container. Expect `0012`.
- Upgrade: `alembic upgrade head` applies `0003` to `0012` from `0002`.
- Do not use `alembic downgrade` for rollback. `0004` makes strategy versions
  immutable and several migrations backfill data. Restore the dump instead.

**Revision id collision.** `~/tradeo-staging/repo-8c8e08a` contains a different
migration that is also numbered `0012` (`0012_email_sign_in`). The live schema
has the main version: the `recovery_codes` table exists, `users.email` does not,
and `invites.phone_e164` is still present. If that older release directory is
put back without restoring the database, Alembic sees `0012` as already applied
and skips its migration, so code and schema would not match. Main has exactly
one `0012` (`0012_recovery_codes`).

## Rollback

1. Backup in `~/.local/state/tradeo-staging/backups` (mode 0600, each with a
   `.sha256`). Latest: `tradeo-staging-20261125T143541Z-T6Cc26rN-v1.dump.gpg`,
   69,586 bytes, 2026-11-25 14:35:41 UTC, taken just before the c700c7e release
   directory (14:44). Older: `20261125T094543Z` (10,293 bytes),
   `20261124T011242Z` (10,277 bytes).
2. Take a fresh `pg_dump` before any new upgrade. The 14:35 dump predates any
   data created since.
3. To roll back: stop api and workers, restore the dump, redeploy the recorded
   release directory, run the read-only `./ops` checks.
4. The API image has no rollback tag. Before the next upgrade, tag the running
   image (for example `tradeo-staging-api:rollback-c700c7e`) so a rollback has
   something to point at.
5. The staging README's rollback note still names `9e5cf9b` as the previous
   release. That is out of date.

Exact `./ops` commands live on the server; copy them from there, do not guess.

## Verified authenticated responses

Run `verify_staging.py` with a signed-in session cookie, against a base URL
that reaches the API, and attach its output.
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

Signed-in run by the owner, 2026-11-25, inside the API container with a real
session (the cookie never left the host's shell):

```
PASS  /health/live  http=200  keys=['status'] status=ok
PASS  /health/ready  http=200  keys=['checks', 'status'] status=ok
PASS  /api/v1/market/overview  http=200  keys=['asOf', 'quotes', 'session', 'source'] source=demo quotes[]=12
PASS  /api/v1/market/instruments  http=200  keys=['instruments'] instruments[]=12
PASS  /api/v1/auth/me  http=200  keys=['session', 'user']
PASS  /api/v1/brokers/preview  http=200  keys=['data', 'status'] status=ready connections[]=2 events[]=0
PASS  /api/v1/strategies/preview  http=200  keys=['data', 'status'] status=ready strategies[]=0
PASS  /api/v1/auto-trading/paper  http=200  keys=['status'] status=empty
PASS  /api/v1/reports/paper  http=200  keys=['status'] status=empty
PASS  /api/v1/alerts  http=200  keys=['asOf', 'items', 'nextCursor', 'unread'] items[]=3
0 failed
```

This account has no strategy assigned, so paper trading and the paper report
are `status: empty`. Their populated shapes (the Dashboard fields above) are not
exercised on staging yet; assign a demo strategy and re-run to cover them.

To repeat the run:

1. Sign in at `https://homelab.tail14603a.ts.net:8446` (email code, then
   authenticator) and copy the value of the `__Host-tradeo_session` cookie
   from the browser's developer tools.
2. From a PowerShell prompt at the root of a checkout that has the script (main
   once this is merged), copy it to the host:

   ```powershell
   Get-Content backend/scripts/verify_staging.py -Raw | ssh avinaks@100.108.199.120 'umask 077; cat > /tmp/verify_staging.py'
   ```

3. Open an SSH session and run it in the API container. `read -rs` keeps the
   cookie off the screen, out of shell history and off the process list;
   `-e STAGING_SESSION_COOKIE` with no value passes it from the environment.

   ```sh
   ssh -t avinaks@100.108.199.120
   cd ~/tradeo-staging/repo/backend/staging
   read -rsp 'Session cookie: ' STAGING_SESSION_COOKIE; echo; export STAGING_SESSION_COOKIE
   docker compose --project-name tradeo-staging -f compose.yaml exec -T \
       -e STAGING_BASE_URL=http://127.0.0.1:8000 -e STAGING_SESSION_COOKIE \
       api python - < /tmp/verify_staging.py
   unset STAGING_SESSION_COOKIE; rm /tmp/verify_staging.py; exit
   ```

4. Paste the PASS/FAIL lines (they contain no values or cookie) into TRAD-6.

Port evidence is recorded above (no host ports for Postgres, Redis, API,
frontend).

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

Paths above are inside the response envelope: `/reports/paper` returns
`{status, data}`, so the fields are `data.summary`, `data.daily`,
`data.journal`; `/auto-trading/paper` puts the account at `data.account`.

### Field by field, against `DashboardSnapshot` (`frontend/src/lib/api/dashboard-fixture.ts`)

| Fixture field | Source | Status |
|---|---|---|
| `asOf` | `overview.asOf` for market cards; `report.data.asOf` for paper cards | Available. They can differ; show each card's own. |
| `indices[].symbol`, `name` | `instruments[]` where `kind = index`: `symbol`, `name` | Available. Live catalog: NIFTY 50, BANKNIFTY, FINNIFTY, INDIA VIX. |
| `indices[].price`, `changePercent` | `overview.quotes[]` by `instrumentId` | Available. `volume` is null for indices. |
| `watchlist[]` | `instruments[]` where `kind = equity` joined to `overview.quotes[]` | Available for the 8 catalog equities (RELIANCE, HDFCBANK, SBIN, TCS, INFY, ICICIBANK, BHARTIARTL, ITC). No per-user list. |
| `portfolioValue` | `paper.data.account.equityPaise / 100` | Available once a strategy is assigned. |
| `dayPnl` | `report?from=D&to=D` → `data.daily[0].realisedPaise / 100` | Realised only. No entry when D had no fill. |
| `dayReturn` | none | **Unavailable.** No prior-day equity. Hide it, or label it as day P&L over `capitalPaise`. |
| `monthPnl` | `report?from=<month start>&to=D` → `data.summary.netPaise / 100` | Available. `netPaise` includes the current open position's unrealised P&L. |
| `monthReturn` | none | **Unavailable** as a true return. `netPaise / capitalPaise` is P&L over starting capital, not a time-weighted return; label it if used. |
| `winningTrades` | `data.summary.winningTrades` | Available. |
| `totalTrades` | `data.summary.closedTrades` | Available. Not `fills`: a buy and its sell are two fills, one closed trade. |
| `portfolio[]` (`date`, `value`) | `data.daily[]`: `capitalPaise` plus cumulative `realisedPaise` | **Partial.** Realised only, only on fill dates, no mark-to-market history. |
| `recentTrades[].id`, `side`, `quantity` | `data.journal[]` | Available. `side` is `Buy` or `Sell`, as in the fixture. |
| `recentTrades[].symbol` | `journal[].instrument` (instrument id) joined to `instruments[].symbol` | Available. Catalog instruments only; there are no option contracts such as the fixture's `NIFTY 50 24500 CE`. |
| `recentTrades[].price` | `journal[].fillPaise / 100` | Available. |
| `recentTrades[].pnl` | `journal[].pnlPaise / 100` | Available with a caveat: `0` on every buy. |
| `recentTrades[].timeIst` | `journal[].filledAt` formatted in Asia/Kolkata | Available. |

Other notes:

- `status: empty` from `/reports/paper` and `/auto-trading/paper` means the
  caller has never assigned a strategy. Show an empty state, not zeros.
- Amounts are integer paise in paper and report responses. Market prices are
  rupees as numbers.
- Report dates are IST session dates of the demo replay, not wall-clock dates.
  "Today" on the Dashboard may have no fills.
- Gaps worth a contract PR if the Dashboard needs them: a day-return
  percentage, an equity history series, a per-user watchlist.
