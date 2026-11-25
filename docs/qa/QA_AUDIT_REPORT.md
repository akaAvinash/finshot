# QA audit (Phase 0), 25 November 2026

Audited commit: `main` at `1cabcc0` ("Connect Tradeo account Settings to the backend (#47)").

## Findings

| Area | Fact (checked) | Consequence for QA |
|---|---|---|
| Existing QA framework | None. No `qa/`, no `docs/qa/`, no QA branches (`git branch -a`, 34 remote branches, none QA-named). | Built new, no duplication. |
| CI | No `.github/` directory on main. The only Actions workflow is GitHub's dynamic Dependabot graph job. | No automated checks run on PRs today; only the CodeRabbit check is required by branch protection. |
| Open PRs | None at audit time (GitHub API). #44 (`codex/email-only-sign-in`, titled "Add Tradeo phone-identity recovery and replacement setup") is **merged** (15:25Z), not a draft as the coordinator brief assumed. | Nightly discovery has no PR candidates tonight; it will test main. |
| Backend tests | pytest, 777 tests (unit + integration on real Postgres/Redis). Ran at `1cabcc0`: **777 passed, 0 failed, 242 s**. | Reused as a CI job; not duplicated. |
| Frontend tests | Vitest (19 files, 72 tests), Playwright e2e (preview mode, 9 specs), staging Playwright config. Ran `npm ci --ignore-scripts`, lint, typecheck, vitest: **all passed, 72/72**. E2E not run locally (needs a production build + browser). | Reused as CI jobs; e2e on main pushes and nightly. |
| Contract | `contracts/openapi.yaml` v0.10.0 (OpenAPI 3.1), plus preview contracts. | QA client validates every response against it. |
| Auth implementation | Invite-only; registration by emailed code (SMTP provider) or mock; phone + TOTP sign-in; recovery codes; step-up; setup-required restriction; operator CLI. SMS (MSG91) and passkeys not built. | Authentication qualified black-box over HTTP. |
| Staging | `homelab.tail14603a.ts.net:8446` is a private Tailscale host; unreachable from cloud runners. | All CI uses disposable local Postgres/Redis; staging checks need Remote Control on the owner's device. |
| Branch protection | (From project memory, not re-read: settings API needs admin) 0 approvals, CodeRabbit required. | The new `qa gate` check is **not** required until the owner adds it. |

## Feature status used by the QA plan

| Engine / service | Status on main |
|---|---|
| Authentication, sessions, step-up, settings profile | Implemented |
| Market data | Demo provider (read-only) |
| Universal broker | Demo adapters only (no real broker connectivity) |
| Strategy research | Implemented (versions, rules) |
| Backtesting | Implemented (in-process worker) |
| Paper trading + risk tiers | Implemented (paper only) |
| Reports (paper) | Implemented incl. CSV export |
| Agents | Deterministic advisory agents (read-only) |
| Alerts | Implemented (in-app only) |
| Trade execution (live) | Not implemented and out of scope |
| Market intelligence, MCP gateway, orchestration engine | Not implemented |
