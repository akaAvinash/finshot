# QA risk register

| ID | Risk | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| R1 | `qa/nightly` not a required check, so PRs with critical findings can still merge | High | High | Owner adds `qa/nightly` to branch protection after the first nightly run | Open (needs owner) |
| R1b | Only critical findings block (owner policy); high findings (e.g. vulnerable dependency) can merge | Medium | Medium | Morning report lists them first under warnings; owner triages daily | Accepted by owner 2026-11-25 |
| R2 | Nightly schedule inactive until workflow is on main | Certain | Medium | Owner reviews/merges the QA PR | Open (needs owner) |
| R3 | Staging unreachable from GitHub runners | Certain | Medium | Disposable services in CI; staging smoke via Remote Control on the owner's device | Accepted |
| R4 | Financial engines checked only by product tests; no independent cross-check yet | High | Critical | Oracles exist; cross-check tests FIN-X-* next | Open |
| R5 | Frontend e2e runs in preview mode, not against the real backend | High | High | AUTH-UI-001 real-backend Playwright journey | Open |
| R6 | Per-IP rate limits not exercised (single client IP) | Medium | Medium | Separate backend with `TRUSTED_PROXY_HOPS=1` and spoofed X-Forwarded-For | Open |
| R7 | Contract drift fails many tests at once | Medium | Low | Defect analyser groups by signature | Mitigated |
| R8 | Time-based tests flaky near TOTP step boundaries | Low | Medium | Simulated device avoids last 2 s of a step; drift test waits for a safe window | Mitigated |
| R9 | AI provider cost runaway or prompt injection | Low | Medium | Off by default, daily cap, call cap, schema-only output, no tools | Mitigated |
| R10 | Pinned actions/images go stale or vulnerable | Medium | Medium | Dependabot for actions (owner choice); images pinned by tag only today (digest pinning TODO) | Open |
| R11 | Real SMTP never verified end to end | Medium | Medium | Authorised, capped manual test (AUTH-OTP-009) | Open (needs owner) |
