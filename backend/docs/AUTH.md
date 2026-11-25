# Authentication and OTP delivery

Contract: `contracts/openapi.yaml` (tag Auth, tag Step-up). Code: `app/auth/`.

## What proves what

| Situation | Mechanism | Status |
|---|---|---|
| Registration (first sign-in) | One-time code to the invite's email (or SMS) | Email via SMTP built; SMS adapter **not built** (see MSG91) |
| Every later sign-in | Phone number plus authenticator code (`POST /auth/login/totp`); no code is sent | Built |
| Regular use | Server-side session cookie, CSRF token, idle and absolute expiry | Built |
| Sensitive operations | Authenticator code (TOTP, RFC 6238) opening a 10-minute step-up window | Built; ending another session is gated |
| Passkeys | `PasskeyAuthenticator` interface, `UnavailablePasskeys` placeholder | Interface only |
| External site | Cloudflare Access in front of the origin | Infrastructure, not in this repo |
| QA | `mock` provider (fixed code `123456`) | Development and test only |

## Invite-only access

There is no sign-up. A phone number can sign in only if it has a non-revoked
row in `invites`. `POST /auth/otp/request` returns the same 202 for every
number, so it does not reveal who is invited. For an uninvited number nothing is
delivered and no spend is counted; the random code it returns a challenge for
can never be verified. Verification re-checks the invite, so revoking one
blocks codes already issued. Operator commands (run on the server; there is no
admin API):

    python -m app.auth.admin invite add +91XXXXXXXXXX [--email you@example.com]
    python -m app.auth.admin invite revoke +91XXXXXXXXXX   # also ends live sessions
    python -m app.auth.admin invite list                   # masked output
    python -m app.auth.admin totp-reset +91XXXXXXXXXX      # lost authenticator
    python -m app.auth.admin staging-otp +91XXXXXXXXXX     # staging provider only

Migration `0010` invites every phone that already has a user, so existing
accounts keep working.

## Registration, then authenticator sign-in

1. An invited number asks for a code (`channel: email` goes to the invite's
   address) and verifies it. That creates the account and a session.
2. The user sets up an authenticator (`/auth/totp/enroll`, `/auth/totp/confirm`).
3. From then on `POST /auth/login/totp` (phone number + current code) is the
   way in. A successful login opens the step-up window, so a gated action does
   not need a second code. Once an authenticator is active a one-time code can
   no longer start a session: `otp/request` still answers 202 but sends
   nothing, and `otp/verify` refuses (401 `INVALID_OTP`, the code stays unused).
4. Recovery codes: a stepped-up session can create ten single-use codes
   (`POST /auth/totp/recovery-codes`, shown once; only keyed digests are
   stored in `recovery_codes`). `POST /auth/login/recovery` (phone number +
   code) signs in once, spends the code and removes the authenticator and
   every other code, so the person sets up a new authenticator and creates new
   codes. A code lives only as long as the authenticator it was issued for:
   `disableTotp`, the operator `totp-reset`, recovery sign-in and confirming a
   new authenticator all delete the account's codes. Recovery sign-in shares
   the authenticator sign-in allowance and answers the same uniform `401`.
5. Lost authenticator and no codes: `totp-reset` on the server, then register
   again by emailed code.

Failure handling: every failure is `401 INVALID_CREDENTIALS` (wrong or reused
code, uninvited number, unknown number, no authenticator, revoked invite). The
IP is throttled on every attempt. The phone allowance (default 5 per 15
minutes) is reserved before the code is checked, so concurrent requests cannot
exceed it, and given back after a successful login. It is the same for every
well-formed number (429 `RATE_LIMITED`). Trade-off:
anyone who knows a number can lock that number out for the window by failing
five times; throttling the phone is what bounds guessing a six-digit code.
Failed attempts are audited as `login_failed` with an IP hash and no code. An
unknown number runs the same HMAC work, but response timing is not otherwise
equalised.

## Providers

`OTP_PROVIDER` (SMS) and `OTP_EMAIL_PROVIDER` (email). Anything unset or
unsupported becomes `disabled`: every request returns 503
`OTP_DELIVERY_UNAVAILABLE`. Nothing falls back to a test provider.

| Value | Where allowed | Behaviour |
|---|---|---|
| `disabled` | everywhere (default) | Delivers nothing |
| `console` | development | Prints to an interactive terminal only, never to logs |
| `mock` | development, test | Fixed code; not a second factor |
| `staging` | staging | Allowlisted synthetic numbers; code in a 0600 file on the server |
| `smtp` (email) | any; STARTTLS required when deployed | Sends via `SMTP_*` |

Settings validation refuses `mock`/`staging` in production and refuses `smtp`
without host, from, username and password.

### Spend limits

Two per-UTC-day counters, both in Redis:

- `OTP_DAILY_DELIVERY_LIMIT` (all numbers, default 100) counts each code handed
  to a provider, including sends that then fail with a provider error (the
  counter is not refunded, so an outage can use the cap up). A request that
  makes no delivery attempt (uninvited number, no email on file) only checks
  it, without counting.
- `OTP_DAILY_DELIVERY_LIMIT_PER_PHONE` (default 10) counts every OTP request
  for that number that gets past the availability check, invited or not, and
  whether or not a code is sent. This keeps the cap from revealing who is
  invited (see the tradeoff below).

At either cap the API returns 503 and sends nothing. A request rejected by
either cap does not spend the global counter. If Redis is down the request
fails (500); it does not skip the cap. Per-request limits and the resend
cooldown still apply.

### Uniform failures

Availability is decided before the invite check: a disabled provider or a
reached daily cap answers every number with the same 503, so the failure does
not reveal who is invited. Known residual: a provider that fails at runtime
(for example SMTP down) fails only for invited numbers, because only they reach
it. It takes a real outage and leaks one bit per outage.

Policy tradeoff: the per-phone daily delivery cap counts every request for a
number, invited or not, so the cap cannot reveal who is invited. A third party
who keeps asking for codes for someone else's number can therefore use up that
number's daily allowance (default 10) and block its owner until the UTC day
ends, even after the hourly request limit has reset. Raise
`OTP_DAILY_DELIVERY_LIMIT_PER_PHONE` to make this harder, or accept a
detectable cap for invited numbers. Owner decision; the default favours
not leaking invitations.

### MSG91 (SMS): not implemented, blocked

I could not fetch MSG91's official API reference from this environment, so the
request format, auth header, template variable names and the server-side
verification call are **unverified** and I have not guessed them. To build the
adapter I need:

1. The exact official pages for Send OTP and Verify OTP (or the API docs from
   your MSG91 dashboard).
2. An MSG91 account with an auth key, and a DLT-registered sender ID and OTP
   template (an Indian regulatory requirement for SMS; registration is outside
   this repo).
3. Your approval to spend on SMS. No paid message is sent until you say so.

Design when unblocked: a `Msg91OtpProvider` implementing `OtpProvider`, key in
`MSG91_AUTH_KEY` (a `SecretStr`, never logged), injected HTTP transport for
tests, `deliver` failures mapped to a fixed `OtpDeliveryError` message. Our own
digest verification stays authoritative; MSG91's verify call is optional.

### SMTP setup

Set `OTP_EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM`. Put the password in the server's `.env`, never in
Git. Email codes need the user's email on the invite (`--email`) and
`"channel": "email"` in the request. Failures return 503; server error text is
never returned or logged.

### Staging without SMS

    OTP_PROVIDER=staging
    OTP_STAGING_FILE=/run/tradeo/otp.json
    OTP_STAGING_ALLOWLIST=+91XXXXXXXXXX,+91YYYYYYYYYY   # synthetic numbers only

Read the current code over SSH on the server:
`python -m app.auth.admin staging-otp +91XXXXXXXXXX`. Numbers off the allowlist
are refused, so staging can never message a real person. The code is the
operator's to read; it never appears in logs or API responses.

## Setup required (contract 0.10.0)

A session whose account has no active authenticator (`user.totpEnabled` is
false) may only call `getCsrfToken`, `getCurrentUser`, `logout`, `logoutAll`,
`enrollTotp` and `confirmTotp`. Every other session operation answers
`403 TOTP_SETUP_REQUIRED` after the 401 check and before CSRF, and changes
nothing. In code: `SetupSession` (any valid session) for the six, and
`RequiredSession` (adds the authenticator check) for everything else, so a new
route is restricted by default. Confirming an authenticator lifts the limit on
every session of the account, because `totpEnabled` is read from the database
on each request. Tests: `tests/integration/test_auth_setup_required.py` reads
the restricted list from the contract. Domain tests use
`Browser.login_ready()`, which gives the test account an authenticator row.

## Step-up (TOTP)

- `POST /auth/totp/enroll`: needs a sign-in within 15 minutes (else 403
  `STEP_UP_REQUIRED`); returns the secret once. 409 if one is already active.
- `POST /auth/totp/confirm`: first valid code activates it and opens a window.
- `POST /auth/step-up`: a valid code opens a 10-minute window
  (`sessions.step_up_until`, never past the session's expiry).
- `POST /auth/totp/disable`: needs a valid code; closes all windows.
- Secrets are sealed with AES-GCM under a key derived from `AUTH_SECRET_KEY`,
  bound to the user id. Each time step is accepted once (replay protection);
  ±1 step of drift is allowed. Wrong codes return 422 `INVALID_TOTP`,
  throttled per user and per IP (429).
- Operations that need a recent step-up call `ensure_stepped_up` after the
  CSRF check (order: 401, CSRF, step-up; 403 `STEP_UP_REQUIRED` when closed).
  `DELETE /auth/sessions/{sessionId}` (ending another session) is the first.
  It answers 409 `CURRENT_SESSION` for the caller's own session and 404
  `SESSION_NOT_FOUND` for an unknown, foreign or already-ended one, so another
  user's session ids cannot be probed.
- Profile (`GET`/`PUT /settings/profile`): display name and timezone; no
  step-up. The display name is trimmed (1 to 48 characters, no control
  characters). Phone number changes are not supported.

## Audit

Events record the action and user id only: `otp_requested`, `otp_verify_failed`,
`login_succeeded`, `logout` plus `totp.enrollment_started`, `totp.enabled`, `totp.step_up`,
`totp.step_up_failed`, `totp.disabled`, `invite.revoked`, `auth.totp_reset`,
`settings.profile_updated`, `session.revoked` (no values, no device details).
OTP requests record channel and whether a delivery happened. No codes, secrets,
phone numbers, emails or raw IPs.

## Onboarding someone

1. `invite add` their number on the server.
2. They request a code in the app and sign in.
3. Optional: they set up an authenticator in Settings once it ships.
