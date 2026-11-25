# Performance test plan (PERF-001, specified)

Not automated yet. Targets below are proposals for the owner to confirm, not measured facts.

| Scenario | Load | Proposed target |
|---|---|---|
| `GET /auth/csrf`, `GET /auth/me` | 50 virtual users, 5 min | p95 < 150 ms, 0 errors |
| TOTP sign-in | 10 logins/s, distinct synthetic users | p95 < 400 ms; throttles behave per user |
| Market overview / candles (demo) | 100 VU | p95 < 250 ms |
| Paper report + CSV export | 20 VU | p95 < 800 ms |

Tooling: Locust against a disposable stack on a GitHub-hosted runner (numbers there are noisy; use for regressions
relative to the previous nightly, not absolute SLOs). Rate limits must be raised in the test backend or users
distributed across synthetic IPs via `TRUSTED_PROXY_HOPS`, otherwise the test measures the limiter.
