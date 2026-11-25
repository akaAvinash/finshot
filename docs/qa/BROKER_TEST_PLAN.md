# Universal broker test plan

Status on main: demo adapters only (`backend/app/brokers`, `contracts/brokers.openapi.yaml`). No real broker connectivity is authorised.
Zerodha is not assumed to be the only broker: every check below is written against the broker-independent interface.

## Adapter conformance suite (BRK-001, specified)

One parametrised suite run against every registered adapter (demo today; each new adapter must pass it before merge):

| Capability | Checks |
|---|---|
| Connect / token lifecycle | connect, expiry surfaced as typed state, refresh or reconnect path, no token in logs |
| Funds and margins | normalised Decimal amounts in INR, currency explicit |
| Holdings / positions | instrument mapping to Tradeo ids, quantity sign convention, average price |
| Unsupported capability | typed error, never a silent no-op (BRK-004) |
| Rate limits | 429/backoff behaviour from a mock transport (BRK-005) |
| Multiple accounts | account isolation per user, no cross-account reads (BRK-002) |
| Reconciliation | positions vs paper ledger, mismatch raises an alert |

Transport is always a mock (RESPX-style) for real adapters; recorded fixtures must be synthetic.
Order placement through any real adapter is out of scope.
