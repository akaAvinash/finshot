# Authentication and OTP delivery

Contract: `contracts/openapi.yaml` (tag Auth, tag Step-up). Code: `app/auth/`.

## What proves what

| Situation | Mechanism | Status |
|---|---|---|
| First sign-in on a device | OTP to an invited phone (SMS) or email | SMS adapter **not built** (see MSG91) |
| Regular use | Server-side session cookie, CSRF token, idle and absolute expiry | Built |
| Sensitive operations | Authenticator code (TOTP, RFC 6238) opening a 10-minute step-up window | Built; no operation gated yet |
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

Per UTC day, counted in Redis only for codes that are actually sent:
`OTP_DAILY_DELIVERY_LIMIT` (all numbers, default 100) and
`OTP_DAILY_DELIVERY_LIMIT_PER_PHONE` (default 10). At the cap the API returns
503 and sends nothing. If Redis is down the request fails (500); it does not
skip the cap. Per-request limits and the resend cooldown still apply.

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
- Operations that need a recent step-up should use the `SteppedUpSession`
  dependency (403 `STEP_UP_REQUIRED` when closed). Settings (next PR) will be
  the first user.

## Audit

Events record the action and user id only: `otp_requested`, `otp_verify_failed`,
`login_succeeded`, `logout` plus `totp.enrollment_started`, `totp.enabled`, `totp.step_up`,
`totp.step_up_failed`, `totp.disabled`, `invite.revoked`, `auth.totp_reset`.
OTP requests record channel and whether a delivery happened. No codes, secrets,
phone numbers, emails or raw IPs.

## Onboarding someone

1. `invite add` their number on the server.
2. They request a code in the app and sign in.
3. Optional: they set up an authenticator in Settings once it ships.
