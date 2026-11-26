# Broker abstraction and contract audit (TRAD-11 / T18), DRAFT

Status: **draft for review**. Formal completion depends on T17, the integrated
demo gate (TRAD-29, planned 2026-12-02). Do not mark TRAD-11 Done from this
document alone.

- Audited revision: `main` at `17a409d` (2026-11-26), contract `0.10.0`.
- Scope: `backend/app/brokers/`, `backend/app/api/routes/brokers.py`, broker
  use in `backend/app/alerts/`, migration `0003`, `contracts/openapi.yaml`
  (Brokers tag and schemas). Frontend files are listed only as places where
  the contract's provider list is copied, not reviewed (Codex owns
  `frontend/`).
- Method: read the code and contract, grep for provider names, and compare
  the adapter boundary with the public auth and account shapes of two
  providers (Zerodha Kite Connect v3 and Fyers API v3). No provider was
  called. No contract file was changed.

Labels used below: **Fact** (seen in code or a cited page), **Inference**
(my reading of a fact), **Recommendation**.

## 1. Summary

1. **Fact.** No Zerodha-specific *field or type* exists in shared code. There
   is no `instrument_token`, `request_token`, `tradingsymbol`, checksum or
   Kite error type anywhere in `backend/app`. The adapter protocol is
   read-only by construction (no order methods) and stores no credentials.
2. **Fact.** The coupling that does exist is the **closed provider list**:
   `zerodha` and `fyers` are hard-coded as a `Literal`, a DB check
   constraint, a contract enum, and a fixed two-item, fixed-order array.
   Adding a third adapter (for example the T23 synthetic one) today needs a
   migration, a breaking contract change and frontend edits.
3. **Inference.** The model assumes **one account per provider per user**
   and uses the **provider name as the connection identity**. That blocks
   T24 (multiple accounts) and leaks into alerts.
4. **Inference.** The adapter seam is too thin for a real provider: a
   single-step `authorize()`, a display mask used as the account key, and
   one error type. Both reference providers use a two-step redirect flow
   with a server-side secret and can invalidate tokens before expiry.
5. **Verdict (opinion):** the boundary is a sound demo seam and a good
   starting point, but it is **not yet provider-neutral** in the sense
   TRAD-11 asks for. Nine gaps below; four block T22/T23/T24.

## 2. Provider shapes compared

Facts from the providers' public docs (fetched 2026-11-26). Items marked
"unverified" were not on the pages read and must be checked in E02 or T26.

| Concern | Zerodha Kite Connect v3 | Fyers API v3 (individual app) | Tradeo today |
|---|---|---|---|
| Login | Redirect to `kite.zerodha.com/connect/login?v=3&api_key=…`; returns `request_token` (valid "a few minutes") to the registered redirect URL | Redirect to login with `client_id`, `redirect_uri`, `response_type=code`, `state`; returns `auth_code` and `state` | `authorize(provider, now)` returns a grant in one call |
| Token exchange | `POST /session/token` with `checksum = SHA-256(api_key + request_token + api_secret)` | `POST /api/v3/validate-authcode` with `appIdHash = SHA-256(app_id:app_secret)` (docs disagree on `+` vs `:`; test) | None |
| Access token expiry | 6 AM next day (regulatory), or earlier on API logout / master logout | Daily at 6:30 AM; expired or invalid tokens give error codes -8, -15, -16, -17 | Demo: connect time + 8 h |
| Refresh | `refresh_token` only for "certain approved platforms" | `refresh_token` returned; lifetime and use not documented on the pages read (unverified) | None |
| Account identity | `user_id`, "unique, permanent", alphanumeric (sample `AB1234`) | Not on the auth pages; profile/account endpoint not reviewed (unverified) | `maskedAccountId` matching `^•••• [0-9]{4}$`, also used as the account key |
| Revoke | `DELETE /session/token` | Not reviewed (unverified) | Disconnect deletes the row; adapter not called |
| Auth header | `Authorization: token api_key:access_token` | `app_id:access_token` | n/a |
| Instrument id | (Not reviewed here; T19) | (Not reviewed here; T19) | Tradeo `Instrument.id`, `exchange: NSE` |

Sources: [Kite Connect v3 user/login](https://kite.trade/docs/connect/v3/user),
[Fyers v3 auth flow](https://fyers.in/api-docs/v3/api/authentication/individual-app/authentication-flow/),
[Fyers v3 validate auth code](https://fyers.in/api-docs/v3/api/authentication/individual-app/validate-auth-code/).

**Inference.** The two providers share a shape (redirect, short-lived code,
secret-derived hash, daily token, early invalidation) but differ in every
detail. That shape belongs in a neutral two-step protocol, with the details
inside each adapter.

## 3. Where provider details enter shared code

`grep -rniE "zerodha|fyers"` over `backend/app backend/migrations contracts
frontend/src` (reproduce with the command in section 7):

| File | Hits | What it hard-codes |
|---|---|---|
| `backend/app/brokers/adapter.py` | 4 | `BrokerId = Literal["zerodha", "fyers"]`, `PROVIDERS`, demo masks, docstring |
| `backend/app/brokers/models.py` | 1 | `CHECK provider IN ('zerodha', 'fyers')` on both tables |
| `backend/migrations/versions/20261124_0003_broker_tables.py` | 1 | same check constraint |
| `contracts/openapi.yaml` | 6 | `BrokerId` enum; `BrokerSnapshot.connections` with `minItems: 2`, `maxItems: 2`, `prefixItems` fixing order zerodha then fyers |
| `contracts/brokers.openapi.yaml` | 1 | legacy copy of the same enum |
| `frontend/src/...` (5 files) | 13 | type union, proxy allow-list in `app/api/v1/[...endpoint]/route.ts`, display names, card styling, mock |

`BrokerId` is then used as a core type by `service.py`, `schemas.py`, the
route path parameter, the alert link (`("broker", provider)`) and the alert
link resolver in `alerts/service.py`.

## 4. Findings

Severity: **High** blocks a planned roadmap task; **Medium** must be fixed
before a real provider (T27); **Low** is cleanup.

| # | Sev | Finding | Evidence | Blocks | Recommendation |
|---|---|---|---|---|---|
| F1 | High | Closed provider list in core types, DB and contract | Section 3 | T22, T23 | Provider registry keyed by an opaque `providerId` string. Validate against the registry in code; replace the DB `CHECK` with a `broker_providers` table or no check. Contract: open `BrokerId` to a pattern plus a discoverable list. |
| F2 | High | Provider name is the connection identity; one account per provider per user | `UNIQUE (user_id, provider)`; route `/{provider}/actions`; advisory lock key `broker:{user}:{provider}` | T24 | Add a server-issued `connectionId` (UUID). Key actions, locks, events and alert links by it. Keep `provider` as an attribute. |
| F3 | High | Contract fixes the array to exactly two providers in a set order | `minItems/maxItems: 2`, `prefixItems` const zerodha/fyers | T22, T23, T24 | Contract PR: `connections` becomes a list of connections, each with `connectionId`, `provider`, `capabilities`, `status`. A separate `providers` list says what can be connected. Breaking change: version bump and a Codex handoff. |
| F4 | High | No capability model | Scopes are three fixed Tradeo labels granted in full by every adapter (`READ_SCOPES`) | T19, T22, T24 | Per-provider capability flags (profile, holdings, positions, orders, funds) declared by the adapter, plus a refusal error (`BROKER_CAPABILITY_UNSUPPORTED`). |
| F5 | Medium | The account key is a display mask | `fetch_account(provider, masked_account_id)`; masks can collide (same last four digits); Kite ids are alphanumeric (`AB1234`), so `^•••• [0-9]{4}$` cannot hold a real mask | T20, T27 | Store an opaque, encrypted-at-rest `accountRef` (provider user id) and derive the mask from it. Relax the mask pattern in the contract. |
| F6 | Medium | Single-step authorization | `authorize(provider, now)`; no callback route, no `state` | T27 | Split into `begin_authorization(state) -> redirect URL` and `complete_authorization(callback params, state) -> grant + credential handle`, with server-held secrets (T20). Contract needs a start endpoint and a callback endpoint. |
| F7 | Medium | Only one error type; status derives from expiry alone | `BrokerUnavailableError` maps to 503 for everything; `status_of` uses `expires_at` only | T22, T29 | Neutral error set: `AUTH_EXPIRED`/`REVOKED` (moves the connection to `expired`), `RATE_LIMITED` (429 with `Retry-After`), `UNAVAILABLE`, `MALFORMED_RESPONSE`, `CAPABILITY_UNSUPPORTED`. Both providers invalidate tokens early (Kite master logout; Fyers -8/-15/-16/-17). |
| F8 | Medium | Disconnect never tells the provider | `_perform` deletes the row; adapter not called | T27 | Add `revoke(credential)` to the protocol (Kite has `DELETE /session/token`). Best-effort, logged, never blocks the local disconnect. |
| F9 | Medium | Network call inside a DB transaction under an advisory lock | `apply()` awaits the adapter inside `db.begin()` for up to `BROKER_TIMEOUT_SECONDS` (default 5 s, max 30 s) | T27 | Harmless for the demo adapter. For real adapters, call the provider outside the transaction, then lock, re-check state and write. |
| F10 | Medium | `AccountData` carries counts only | `holdings_count`, `open_orders_count` | T19 | Canonical holding/position/order models with `Decimal` amounts and an instrument mapping done inside the adapter (provider symbol to Tradeo `Instrument.id`). |
| F11 | Low | Global on/off switch, not per provider | `BROKER_PROVIDER: Literal["demo", "disabled"]` | T22 | `BROKER_PROVIDERS_ENABLED` list read by the registry. |
| F12 | Low | Alert text uses the raw id ("The demo zerodha connection…") and the display name exists only in the frontend | `service.py` alert message; `frontend/src/lib/brokers.ts` | — | Display names come from the provider registry. |
| F13 | Low | Legacy `contracts/brokers.openapi.yaml` still lists the enum | Section 3 | — | Mark it superseded, or delete it in the contract PR. |

What is already neutral and should be kept (Fact):

- Read-only protocol: no place, modify or cancel methods (`adapter.py`).
- No credentials or tokens stored (`BrokerConnection` docstring and columns).
- Per-user isolation: every query filters on `user_id`; actions run under a
  per-(user, provider) advisory lock.
- The adapter returns `expires_at`, so each provider's expiry rule (6 AM,
  6:30 AM) stays in the adapter.
- Timeouts and adapter errors map to a structured 503, and a sync that
  answers for a different account is refused.
- `environment = 'DEMO'` check and `source: demo` const: an intentional
  gate, not leakage. Lifting it is a separately approved step.
- `app/market/provider.py` is a good template: a protocol, a disabled
  implementation, and validation and error mapping in the API layer.

## 5. Contract gaps (for a separate contract PR, not changed here)

1. `BrokerId` closed enum and the fixed two-item `connections` array (F1, F3).
2. No `connectionId`; path `/brokers/preview/{provider}/actions` (F2).
3. No capability flags on providers or connections (F4).
4. `maskedAccountId` pattern is digits-only (F5).
5. No authorization start or callback operations (F6).
6. `BrokerError.code` lacks `BROKER_AUTH_EXPIRED`, `BROKER_RATE_LIMITED`
   (with `retryAfterSeconds`), `BROKER_CAPABILITY_UNSUPPORTED`,
   `BROKER_MALFORMED_RESPONSE` (F7).
7. No canonical holding, position, order or funds schemas with decimal
   amounts and instrument identity (F10; this is T19's deliverable).
8. `AlertLink` with `kind: broker` uses the `BrokerId` as its id (F2).

## 6. Proposed provider-neutral boundary (for T19, T20, T22 review)

```
ProviderRegistry: providerId -> (BrokerAdapter, ProviderInfo{displayName, capabilities})

BrokerAdapter (read-only)
  begin_authorization(state, redirect_uri) -> AuthRedirect
  complete_authorization(callback_params, state) -> Grant{accountRef, maskedAccountId, expiresAt, credential}
  fetch_profile(credential) -> CanonicalProfile
  fetch_holdings(credential) -> list[CanonicalHolding]     # only if capability
  fetch_positions / fetch_orders / fetch_funds             # only if capability
  revoke(credential) -> None                               # best effort
  raises BrokerError(kind = auth_expired | revoked | rate_limited | unavailable | malformed | unsupported)

Core (provider-agnostic): connections keyed by connectionId, ownership by user_id,
credential handles encrypted at rest (T20), capability refusal before dispatch,
error-to-HTTP mapping, audit and alerts.
```

**Acceptance check "a second adapter can be added without Zerodha-specific
core types":** today a second adapter needs edits to `adapter.py`,
`models.py`, a migration, the contract and five frontend files (section 3).
After F1 to F4, adding a provider should touch only a new adapter module and
its registry entry. T23 is the test of that; T21's conformance suite should
check it.

## 7. Reproduce

```bash
git checkout 17a409d
grep -rniE "zerodha|fyers" --include=*.py --include=*.yaml --include=*.ts --include=*.tsx \
  backend/app backend/migrations contracts frontend/src | cut -d: -f1 | sort | uniq -c
sed -n 1,70p backend/app/brokers/adapter.py
grep -n "provider" backend/app/brokers/models.py backend/app/brokers/service.py
sed -n '/BrokerSnapshot:/,/BrokerConnection:/p' contracts/openapi.yaml
```

## 8. Open questions for the owner

1. Is one account per provider acceptable for the owner-only pilot, or is
   multi-account (T24) required before the first real broker?
2. Which provider is the reference broker for T26? This decides which
   unverified rows in section 2 must be checked first.
3. Breaking the Brokers contract (F3) needs a coordinated Codex change. Is a
   new versioned path (for example `/api/v1/broker-connections`) preferred
   over changing `/brokers/preview`?
