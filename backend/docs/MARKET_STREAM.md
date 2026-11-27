# Owner market stream

Updated 2026-11-27 (UTC). Implements `contracts/live-market-stream.asyncapi.yaml`
(0.1.0-draft, PR #83). Read-only: nothing here places, changes or reads orders.

## What it does

`GET /api/v1/market/stream?instrumentId=NSE:RELIANCE&timeframe=5m` upgrades to a
WebSocket for one instrument and timeframe. Only the account named by
`MARKET_STREAM_OWNER_USER_ID` can connect. The server sends:

1. `snapshot`: the latest quote and recent candles (`history.source` is `market`).
2. `status`: the upstream feed state (`live`, `closed`, `stale`, `unavailable`),
   right after the snapshot, on every change, and every
   `MARKET_STREAM_HEARTBEAT_SECONDS` (15) while no update was sent.
3. `update`: the latest quote and the current candle. A candle with the same
   `time` replaces the last bar; a later `time` appends one. When ticks cross into
   a new bar, the finished bar is sent first.

The browser sends nothing. To switch instrument or timeframe, close and reconnect.

One upstream connection serves all owner connections. The REST market routes
(`/instruments`, `/overview`, `/candles`) stay on demo data.

## Before the upgrade (HTTP status, error body `{code, message}`)

| Order | Condition | Status | `code` |
|---|---|---|---|
| 1 | `MARKET_STREAM_ENABLED` is false | 404 | `NOT_FOUND` |
| 2 | `Origin` is not exactly `PUBLIC_ORIGIN` | 403 | `ORIGIN_NOT_ALLOWED` |
| 3 | No session cookie, or it is expired or revoked | 401 | `UNAUTHENTICATED` |
| 4 | Not the owner, a tester session, or authenticator setup pending | 403 | `MARKET_STREAM_FORBIDDEN` |
| 5 | Missing, unknown, repeated or extra query parameters; instrument not in the catalog | 400 | `INVALID_REQUEST` |
| 6 | More than `MARKET_STREAM_MAX_CONNECTIONS` (5) streams, no first tick within `MARKET_STREAM_SNAPSHOT_TIMEOUT_SECONDS` (5), feed down, or history failed | 503 | `MARKET_STREAM_UNAVAILABLE` (with `Retry-After: 5`) |

## After the upgrade (close codes)

| Code | When | Client action |
|---|---|---|
| 4401 | Session ended (checked every `MARKET_STREAM_SESSION_RECHECK_SECONDS`, 30) | Stop. Sign in again. |
| 4403 | Account no longer eligible (for example, its authenticator was removed) | Stop. |
| 1008 | The client sent a message | Stop. |
| 1013 | The client fell behind (`MARKET_STREAM_QUEUE_SIZE`, 256 ticks) | Reconnect with backoff. |
| 1012 | Server restart (sent by the server process) | Reconnect with backoff. |

Each periodic session check renews the session (owner decision, 2026-11-27): an
open chart keeps the session alive, so it is not signed out by the idle timeout.
The absolute expiry (`SESSION_ABSOLUTE_TTL_SECONDS`, 12 hours) still ends it with
4401, as do sign-out and revocation.

## Configuration (server environment only)

| Variable | Default | Notes |
|---|---|---|
| `MARKET_STREAM_ENABLED` | `false` | Needs `MARKET_STREAM_OWNER_USER_ID`. |
| `MARKET_STREAM_OWNER_USER_ID` | none | `python -m app.auth.admin user-id +91XXXXXXXXXX` prints it. |
| `MARKET_STREAM_PROVIDER` | `mock` | `mock` or `kite`. `mock` is refused in production. |
| `KITE_API_KEY` | none | Needed for `kite`. |
| `KITE_ACCESS_TOKEN_FILE` | none | Needed for `kite`. A file the API process can read, mode 0600. |
| `KITE_API_SECRET` | none | Only for the token exchange command below. |

Tuning: `MARKET_STREAM_MAX_CONNECTIONS`, `MARKET_STREAM_QUEUE_SIZE`,
`MARKET_STREAM_HEARTBEAT_SECONDS`, `MARKET_STREAM_SESSION_RECHECK_SECONDS`,
`MARKET_STREAM_STALE_AFTER_SECONDS` (30, no upstream message while open means
`stale`), `MARKET_STREAM_SNAPSHOT_TIMEOUT_SECONDS`, `MARKET_STREAM_MOCK_TICK_SECONDS` (1).

### Mock feed

A random walk from the demo catalog's last closes, ticking every second for every
subscribed instrument, around the clock (its status is never `closed`). **Not real
prices**, even though frames say `source: market` as the contract requires. Use it
on staging to build the chart.

### Kite feed

- Quotes: the Kite ticker WebSocket in `full` mode, so each quote carries the
  exchange timestamp. Order messages on that connection are dropped.
- History: Kite historical candles, paced to about 3 requests a second and cached
  for 10 seconds. Daily bars are dated at the 09:15 IST open. Candles stay in
  memory only (Kite terms 4(b); `docs/DATA_RIGHTS.md`).
- Instrument tokens are looked up from Kite's NSE instrument list once a day. The
  catalog is the same 12 instruments as the demo data.
- Daily token: Kite access tokens expire every morning (about 06:00 IST). On the
  server:

  ```
  python -m app.market.stream.kite_session login-url   # open it, sign in to Kite
  python -m app.market.stream.kite_session exchange    # paste request_token (hidden)
  ```

  The token is written to `KITE_ACCESS_TOKEN_FILE` (0600, atomic). The stream uses
  it on its next connection attempt (backoff up to 60 seconds); no restart needed.
- Nothing logs the API key, token or WebSocket URL. Errors are logged by type or
  HTTP status.
- The binary tick parser follows Kite's published layout and is tested against
  constructed packets, not a live feed. The first live connection is the owner's
  check.

### Not covered

- NSE holidays are not known: on a holiday the Kite feed shows `stale` during
  market hours.
- A connection opened mid-bar starts that bar from the history's last bar; after
  that, bar volume is the growth of the day's cumulative volume.
- A broker-wide outage or an expired token affects this feed and any future order
  path alike (the contract notes this).

## Staging test steps (for wiring the chart)

Needs the owner's go-ahead to deploy, and an ingress change: the Next.js proxy does
not carry WebSocket upgrades, so `/api/v1/market/stream` must be routed by the
ingress straight to the API, keeping the `Origin` header and cookies.

1. Owner, on the staging host: get the owner id with
   `python -m app.auth.admin user-id <owner phone>` (inside the API container).
2. Set in the API environment: `MARKET_STREAM_ENABLED=true`,
   `MARKET_STREAM_OWNER_USER_ID=<id>`, `MARKET_STREAM_PROVIDER=mock`. Restart the API.
3. Route `wss://<staging origin>/api/v1/market/stream` to the API (ingress).
4. Sign in as the owner in the browser, then in the console:

   ```js
   const ws = new WebSocket(`wss://${location.host}/api/v1/market/stream?instrumentId=NSE:NIFTY50&timeframe=1m`);
   ws.onmessage = (e) => console.log(JSON.parse(e.data));
   ws.onclose = (e) => console.log('closed', e.code);
   ```

   Expect one `snapshot`, one `status` with `state: "live"`, then an `update`
   about every second.
5. Negative checks: a signed-out window or a tester session gets a failed upgrade
   (browsers show 1006; the server answered 401 or 403). Signing out in another tab
   closes the stream with 4401 within 30 seconds.
6. Kite (later, owner only): set `MARKET_STREAM_PROVIDER=kite`, `KITE_API_KEY`,
   `KITE_ACCESS_TOKEN_FILE`, run the daily token exchange, restart once. During
   market hours the status should be `live`; outside them, `closed`.

Server log lines: `market_stream_opened`, `market_stream_closed` (with close code),
`market_stream_upstream_failed` (error type), `kite_http_error` (status).
