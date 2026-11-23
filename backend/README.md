# Tradeo backend

FastAPI service foundation for Tradeo. It provides configuration, database and
cache wiring, migrations, health probes, logging and container setup. It has
**no business endpoints yet** and **no order placement of any kind**.

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
  api/router.py      /api/v1 router (empty until contracts are agreed)
migrations/          Alembic
tests/unit           no external services needed
tests/integration    real Postgres + Redis
```

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
`DATABASE_URL` (must be `postgresql+asyncpg://`) and `REDIS_URL`.

In `APP_ENV=staging|production` the service **refuses to start** if:
CORS allows `*` or plain `http://` origins, `ALLOWED_HOSTS` is empty or `*`,
docs are enabled, logs are not JSON, log level is DEBUG, or the database or
Redis URL has no password. Validation errors never echo the input values.

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
TEST_DATABASE_URL=postgresql+asyncpg://user:pw@localhost:5432/tradeo_test \
TEST_REDIS_URL=redis://:pw@localhost:6379/15 \
pytest                       # also runs integration tests (upgrades/downgrades that DB)
ruff check . && ruff format --check . && mypy app
```

## API contract

The shared contract is `contracts/openapi.yaml` (owned outside `backend/`; do
not edit it from here). This service follows it:

- Business routes live under `/api/v1` (`app/api/router.py`). None are
  implemented yet; the contract's Markets endpoints come next.
- Errors use the contract's shape: `{"code": "UPPER_SNAKE", "message": "..."}`,
  plus `requestId` when available (`app/core/errors.py`). Invalid parameters
  return **400 `INVALID_REQUEST`**, not FastAPI's default 422. Unhandled errors
  return 500 `INTERNAL_ERROR`.
- `/health/*` probes are infrastructure endpoints and are not in the contract.
