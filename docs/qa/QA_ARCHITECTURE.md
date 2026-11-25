# QA architecture

```
                 GitHub Actions (read-only token, no secrets)            trusted, no candidate code
 ┌──────────────────────────────────────────────────────────────┐      ┌──────────────────────────┐
 │ qa-suite.yml (one candidate = base sha [+ PR head shas])      │      │ gate / morning-report    │
 │  prepare: merge check ─┬─ backend: ruff + pytest (777)        │JUnit │  supervisor (rules)      │
 │                        ├─ qa: independent suite ──────────────┼─────▶│  + optional AI review    │
 │                        │   + secret scan + pip-audit          │      │  qa-summary.md, json,    │
 │                        └─ frontend: lint, tsc, vitest,        │      │  defects.md, verdict     │
 │                            npm audit, [playwright e2e]        │      └──────────────────────────┘
 └──────────────────────────────────────────────────────────────┘

 qa job internals
   pytest ──▶ ApiClient ──HTTP──▶ uvicorn app.asgi (separate process, APP_ENV=test)
                │  contract check        │            │
                │  cookie jar / CSRF     │ SMTP       │ asyncpg / redis
                ▼                        ▼            ▼
          redacted evidence        SmtpSink      TcpProxy (cut/restore) ─▶ Postgres 16 / Redis 7
                                   (aiosmtpd)                              (disposable service containers)
   operator actions: `python -m app.auth.admin ...` and `alembic upgrade head` as subprocesses
```

## Decisions

| Decision | Why | Trade-off |
|---|---|---|
| Black-box over HTTP, backend as subprocess | Independence; same path a client uses | Slower than in-process tests (auth suite ~3-4 min) |
| Real SMTP provider + local sink, not the `mock` provider | Codes are random as in production; exercises the real delivery path and failure handling | Needs a local port; still no external mail |
| Own TOTP implementation (RFC 6238) | Oracle must not share the product's bugs | Must be kept correct: self-tested on RFC vectors |
| Stdlib TCP proxy instead of Toxiproxy | No extra binary/container; same locally and in CI | Only cut/restore today (no latency/bandwidth toxics) |
| Contract validation inside the client | Every response checked without extra test code | A contract drift fails many tests at once (grouped by the defect analyser) |
| No Allure yet | JUnit + JSON + Markdown cover gating and the morning report; Allure adds a Java toolchain | Less visual history; revisit when trend charts are needed |
| Schemathesis/Locust/ZAP/Testcontainers not added yet | Not needed for tonight's auth baseline; CI service containers replace Testcontainers | Listed as specified work in the traceability matrix |

## Independence controls

- `qa/tests/policy` fails if `qa/` imports `app.*`, embeds real endpoints/credentials, uses non-`.invalid` emails, or if the AI agent gains GitHub write calls.
- Workflows: `pull_request` only (never `pull_request_target`), `permissions: contents: read`, git credentials removed before candidate code runs, actions pinned to commit SHAs, job timeouts.
