# Authentication test plan

Specification: `contracts/openapi.yaml` 0.10.0 (Auth, Step-up, Settings tags) and `backend/docs/AUTH.md`.
Implementation under test: whatever is on the tested commit; the plan does not assume behaviour beyond those documents.

## Environment

Backend process with `APP_ENV=test`, `OTP_EMAIL_PROVIDER=smtp` pointed at the local SMTP sink (STARTTLS off, test env only),
SMS provider disabled, workers disabled, default rate limits, resend cooldown 0 in the shared backend (cooldown has its
own backend). Short-TTL backends for expiry tests (30 s OTP, 60 s idle, 60 s step-up). Invites via the operator CLI.

## Coverage (requirement ids in `REQUIREMENTS_TRACEABILITY.csv`)

| Brief item | Requirement ids | Status |
|---|---|---|
| Invite-only registration | AUTH-REG-001..005 | automated |
| Email OTP delivery / expiry / incorrect / replay / resend / attempt limits | AUTH-OTP-001..008 | automated |
| Rate limiting | AUTH-RATE-001, -003, AUTH-TOTP-010, AUTH-CAP-001 | automated; per-IP limits (AUTH-RATE-002) specified |
| Email delivery failure | AUTH-OTP-008, REL-AUTH-003 | automated |
| Authenticator enrolment, QR, manual setup | AUTH-TOTP-001..004 | automated |
| Phone + TOTP sign-in, drift, replay, invalid codes | AUTH-TOTP-005..010 | automated |
| Recovery codes, single use, replay, lost authenticator | AUTH-REC-001..006 | automated |
| Session expiry, logout, logout all, revocation, concurrency | AUTH-SESS-001..011 | automated; absolute expiry (12 h) specified |
| CSRF, cookies | AUTH-CSRF-001..003, AUTH-COOKIE-001..002 | automated |
| Unauthorized access, account isolation | AUTH-SESS-001, AUTH-ISO-001..002, AUTH-SETUP-001 | automated; full route inventory (SEC-AUTHZ-001) specified |
| Account enumeration | AUTH-ENUM-001..004 | automated; timing analysis (AUTH-ENUM-005) specified |
| Credential leakage | SEC-LEAK-001..004 | automated |
| Database and Redis outages | REL-AUTH-001..002 | automated |
| Browser refresh / navigation / interrupted registration | AUTH-SESS-007..008, AUTH-REG-005 | automated at API level; browser journey AUTH-UI-001 specified |
| Frontend/backend integration | AUTH-UI-001 | specified (frontend e2e today runs in preview mode, not against the backend) |
| Real SMTP | AUTH-OTP-009 | specified; needs owner authorisation, an owned mailbox and a send cap |
| SMS (MSG91), passkeys | AUTH-OTP-010, AUTH-PASSKEY-001 | not implemented in product |

## Real SMTP verification (not automated)

Only with explicit owner approval: one invited synthetic number with an owner-controlled mailbox, at most 3 sends per run,
manual trigger only, never in nightly. Never send to real users.
