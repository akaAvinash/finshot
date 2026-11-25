# Threat model (QA view)

Scope: authentication surface, QA/CI pipeline, AI agent. STRIDE per asset; "Test" names the automated check or the plan entry.

## Authentication

| Threat | Example | Control (product) | Test |
|---|---|---|---|
| Spoofing | Guess a 6-digit OTP or TOTP | 5 attempts per challenge, per-phone/IP throttles | AUTH-OTP-005, AUTH-TOTP-010, AUTH-RATE-001 |
| Spoofing | Replay a captured code / recovery code / cookie | Single-use codes, monotonic TOTP steps, server-side sessions | AUTH-OTP-004, AUTH-TOTP-006, AUTH-REC-002, AUTH-SESS-002 |
| Spoofing | Session fixation | New session id on login | AUTH-COOKIE-002 |
| Tampering | Cross-site request | CSRF token bound to context + cookie | AUTH-CSRF-001..003 |
| Repudiation | Deny revoking sessions | Audit events without values | (specified) audit assertions via DB |
| Information disclosure | Who is invited / has an account | Uniform responses, throttles, caps | AUTH-ENUM-001..004; timing AUTH-ENUM-005 specified |
| Information disclosure | Codes, secrets, phones in logs | Log policy | SEC-LEAK-001..004 |
| Denial of service | Burn someone's daily OTP allowance | Documented trade-off in AUTH.md | AUTH-CAP-001 (behaviour), owner decision |
| Elevation | Stolen idle session enrols attacker TOTP | 15-min recency for enrol | (specified) needs time travel or 15 min wait |
| Elevation | Session without authenticator reaches data | Setup-required restriction | AUTH-SETUP-001 |

## CI / QA pipeline

| Threat | Control |
|---|---|
| PR code steals secrets | `pull_request` only, no secrets in suite jobs, read-only token, git credentials removed before code runs |
| Malicious PR alters the gate | Gate job checks out the **base** commit's QA tooling, not the PR's |
| Supply chain | Actions pinned to commit SHAs; `npm ci --ignore-scripts`; pip-audit and npm audit |
| Artifact leakage | Evidence redacted; synthetic data only; 14-30 day retention |

## AI agent

| Threat | Control |
|---|---|
| Prompt injection via logs/PR text | Delimited untrusted block, schema-only output, notes bound to known ids, no tools |
| Over-trust | AI never changes outcome, severity or verdict; labelled as opinion |
| Cost abuse | Off by default; daily cap; per-run call cap |
| Secret exfiltration | Redaction before sending; key only in the nightly report job |
