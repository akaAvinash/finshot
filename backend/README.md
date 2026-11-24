# Tradeo backend

FastAPI service for Tradeo. It provides configuration, database and cache
wiring, migrations, health probes, logging, container setup, (Phase A)
phone-OTP authentication with server-side sessions and (Phase B1) read-only
market data backed by demo fixtures. It has **no broker or trading endpoints
yet**, **no live market feed** and **no order placement of any kind**.

## Stack

| Concern | Choice |
|---|---|
| API | FastAPI + Uvicorn, Python 3.12 |
| Database | PostgreSQL 16 via SQLAlchemy 2 async + asyncpg |
| Migrations | Alembic (async env, baseline revision `0001`) |
| Cache | Redis 7 via `redis.asyncio` |
| Config | `pydantic-settings`, validated at startup |
| Logging | `structlog`, JSON to stdout, request IDs |
| Tests | pytest (unit + opt-in integration) |

## Layout

```
app/
  main.py            app factory, middleware, error handler
  asgi.py            uvicorn entrypoint (app.asgi:app)
  core/config.py     settings + production safety rules
  core/logging.py    structlog setup, secret redaction
  core/middleware.py request IDs, access log, security headers, host allowlist
  db/                engine, session dependency, declarative Base
  cache/redis.py     Redis client
  api/routes/health.py
  api/routes/auth.py /api/v1/auth/* (see contracts/openapi.yaml)
  api/routes/market.py /api/v1/market/* (read-only)
  api/routes/brokers.py /api/v1/brokers/preview* (demo connections)
  api/router.py      /api/v1 router
  auth/              models, service, signed CSRF tokens, OTP providers, rate limits
  market/            provider interface, demo provider, search, response models
  brokers/           read-only adapter protocol, demo adapter, models, service
migrations/          Alembic
tests/unit           no external services needed
tests/integration    real Postgres + Redis
```

## Authentication (Phase A)

Implements the `/api/v1/auth/*` endpoints in `contracts/openapi.yaml`:
`csrf`, `otp/request`, `otp/verify`, `me`, `logout`, `logout-all`, `sessions`.

- **OTP:** six random digits (OS CSPRNG), stored only as an HMAC digest bound to
  the challenge, 5 minute life, single use, at most 5 verify attempts, resend
  cooldown, and Redis rate limits per phone, IP and browser context (`429`
  with `Retry-After`). Verification marks the challenge used with one atomic
  `UPDATE`, so concurrent requests cannot both succeed.
- **Sessions:** random 256-bit token in a cookie; only its HMAC digest is stored.
  Idle (default 30 min) and absolute (default 12 h) expiry, revocation on
  logout, `logout-all`, and rotation on login.
- **Cookies:** `__Host-tradeo_session` and `__Host-tradeo_csrf`, host-only,
  `HttpOnly; Secure; SameSite=Lax; Path=/`, each in its own `Set-Cookie` field.
- **CSRF:** signed token (HMAC) bound to the valid server-side session, or to a
  pre-login context for the OTP flow. A code requested in one browser context
  cannot be verified from another. A stale session cookie counts as pre-login,
  and `GET /auth/csrf` clears it.
- **OTP delivery:** `OTP_PROVIDER=disabled` (default) sends nothing and returns
  503. `OTP_PROVIDER=console` is opt-in, development only (refused in every other
  `APP_ENV`), and prints the code only to an interactive terminal, bypassing the
  logging system. Run it from a terminal, not Docker. Tests inject their own
  provider; no fixed-code path exists in application code. Real SMS is not
  implemented.
- **Data:** `users`, `otp_challenges`, `sessions`, `audit_events` (migration
  `0002`). Audit rows never hold phone numbers, codes or tokens. Purge expired
  digests and dead sessions with `python -m app.auth.maintenance` on a schedule.
- **Behind the Next.js proxy:** set `TRUSTED_PROXY_HOPS=1` so rate limits use the
  real client IP. The proxy wiring itself is separate work and must forward each
  `Set-Cookie` field separately (the contract spells this out).

Not done yet: real SMS provider, passkeys/TOTP step-up, per-user row-level
security in Postgres (queries filter on `user_id`; isolation is covered by tests),
least-privilege database roles.

### Local manual test with the console provider

```bash
export APP_ENV=development OTP_PROVIDER=console AUTH_SECRET_KEY=$(openssl rand -hex 32)
export ALLOWED_HOSTS=localhost PUBLIC_ORIGIN=http://localhost:3000
# plus DATABASE_URL and REDIS_URL, then:
alembic upgrade head && uvicorn app.asgi:app
```

The code appears in that terminal as `OTP for +91******3210: 123456`, not in any log.

## Market data (Phase B1, read-only)

Implements the three Markets operations in `contracts/openapi.yaml`:
`GET /api/v1/market/instruments?query=`, `GET /api/v1/market/overview` and
`GET /api/v1/market/instruments/{instrumentId}/candles?timeframe=`
(`1m`, `5m`, `15m`, `30m`, `1h`, `1D`). No authentication, as in the contract.

- **Provider interface:** routes depend on `MarketDataProvider`
  (`app/market/provider.py`); `create_app(market_provider=...)` injects one.
  `MARKET_DATA_PROVIDER=demo` (default) or `disabled` (every call is 503).
- **Demo data:** `app/market/demo.py` is a deterministic port of
  `frontend/src/lib/api/market-fixture.ts`: same 12 NSE instruments, IDs,
  aliases and numbers, snapshot dated 2026-11-23 (session closed). Every quote
  and candle response says `"source": "demo"`. Not real prices. The calendar
  skips weekends but not NSE holidays.
- **Search:** case-insensitive over symbol, ID, name and aliases, ignoring
  spaces and punctuation, ranked exact > prefix > name prefix > substring
  (same rules as `frontend/src/lib/market/search.ts`).
- **Guarantees:** the response models reject negative prices or volumes,
  high/low that do not bound open and close, non-UTC times, and candles that
  are out of order or share a timestamp. A provider that returns such data, raises
  `MarketDataUnavailableError` or exceeds `MARKET_DATA_TIMEOUT_SECONDS`
  produces `503 MARKET_DATA_UNAVAILABLE`, never bad data.
- **Errors:** `400 INVALID_REQUEST` (bad ID format, unknown timeframe, query
  over 100 characters), `404 UNKNOWN_INSTRUMENT` (well-formed ID not in the
  catalog), `503 MARKET_DATA_UNAVAILABLE`; all with `requestId`.

## Brokers (Phase B2, demo only)

Implements `GET /api/v1/brokers/preview` and
`POST /api/v1/brokers/preview/{provider}/actions` from `contracts/openapi.yaml`.
Providers `zerodha` and `fyers`; actions `connect`, `reconnect`, `sync`,
`disconnect`.

- **No real broker access.** No OAuth, provider requests, tokens or
  credentials. The adapter protocol (`app/brokers/adapter.py`) is read-only:
  `authorize` and `fetch_account` only, no order methods (a unit test enforces
  this). `BROKER_PROVIDER=demo` (default) or `disabled` (every call is 503).
- **Per user, server-side.** Tables `broker_connections` (one row per user and
  provider, deleted on disconnect, `environment = 'DEMO'` enforced by the
  database) and `broker_events` (append-only). Migration `0003`. A new user
  starts disconnected with no events. The snapshot returns the 50 most recent
  events, oldest first.
- **Rules.** Connected: `sync`, `disconnect`. Expired (at or after
  `expiresAt`): `reconnect`, `disconnect`. Disconnected: `connect`. Anything
  else is `409 BROKER_ACTION_CONFLICT`. A demo connection lasts 8 hours.
- **Safety.** Both endpoints need a valid session (401 first); the POST needs a
  `session` CSRF token (403). Each action runs in one transaction under a
  per-user, per-provider advisory lock and writes a broker event and an audit
  event. An adapter error, timeout (`BROKER_TIMEOUT_SECONDS`) or a sync for a
  different account returns `503 BROKER_UNAVAILABLE` and writes nothing.

## Run locally

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env            # set passwords
docker compose up -d postgres redis
alembic upgrade head
uvicorn app.asgi:app --reload
```

Or the whole stack: `docker compose up --build` (API on http://127.0.0.1:8000).

## Endpoints

| Path | Purpose |
|---|---|
| `GET /health/live` | Process is up. No dependency checks. |
| `GET /health/ready` | 200 if Postgres and Redis answer within `HEALTH_CHECK_TIMEOUT_SECONDS`, else 503. Body: `{"status","checks":{"database","redis"}}`. |
| `/docs`, `/openapi.json` | Only outside staging/production. |

## Configuration

All settings are environment variables (see `.env.example`). Required:
`DATABASE_URL` (must be `postgresql+asyncpg://`), `REDIS_URL`, `AUTH_SECRET_KEY`
(32+ characters, placeholders rejected) and `PUBLIC_ORIGIN`.

In `APP_ENV=staging|production` the service **refuses to start** if:
CORS allows `*` or plain `http://` origins, `ALLOWED_HOSTS` is empty or `*`,
docs are enabled, logs are not JSON, log level is DEBUG, or the database or
Redis URL has no password, or `PUBLIC_ORIGIN` is not https. Validation errors never echo the input values.

## Secure defaults

- CORS off unless `CORS_ALLOWED_ORIGINS` is set; explicit origin list only.
- Host header allowlist (`ALLOWED_HOSTS`). `/health/*` is exempt so container
  and orchestrator probes can call the raw IP.
- Headers: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`, strict CSP on API responses, HSTS in production.
- Unhandled errors return a generic 500 (`INTERNAL_ERROR`) with the request ID; tracebacks only
  go to the logs. Log keys like `password`, `token`, `authorization` are redacted.
- Docker image: multi-stage, runs as UID 10001, no server header, app files
  owned by root (read-only to the app). Compose runs the API with a read-only
  root FS, `cap_drop: ALL`, `no-new-privileges`, and binds ports to 127.0.0.1.
- Migrations run as a separate one-shot job, not on API startup.

## Tests

```bash
pytest                       # unit tests; integration tests skip
# Integration tests TRUNCATE the auth tables and FLUSHDB Redis: use throwaway instances.
TEST_DATABASE_URL=postgresql+asyncpg://user:pw@localhost:5432/tradeo_test \
TEST_REDIS_URL=redis://:pw@localhost:6379/15 \
pytest                       # also runs integration tests (upgrades/downgrades that DB)
ruff check . && ruff format --check . && mypy app
```

## API contract

The shared contract is `contracts/openapi.yaml` (owned outside `backend/`; do
not edit it from here). This service follows it:

- Routes live under `/api/v1`. The auth and Markets endpoints are implemented.
- Errors use the contract's shape: `{"code": "UPPER_SNAKE", "message": "..."}`,
  plus `requestId` when available (`app/core/errors.py`). Invalid parameters
  return **400 `INVALID_REQUEST`**, not FastAPI's default 422. Unhandled errors
  return 500 `INTERNAL_ERROR`.
- `/health/*` probes are infrastructure endpoints and are not in the contract.
