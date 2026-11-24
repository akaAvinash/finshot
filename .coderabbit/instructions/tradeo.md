---
id: tradeo-review
paths:
  - "**/*"
---

# Tradeo review policy

## All changes

- Prioritize security, correctness, data integrity, and user-facing regressions.
- Keep findings within the PR's scope. Cite the affected lines and explain the
  failure case and user impact.
- Flag missing regression tests for changed critical behavior. Distinguish
  verified test results from checks that still need to run.

## Backend (`backend/**`)

- Check input validation, authentication, authorization, and ownership scoping
  on reads and writes. Check that migrations preserve existing data.
- For OTP and sessions, verify expiry, rate limits, atomic single use, session
  rotation and revocation, and cookie and CSRF handling.
- Flag exposed secrets, broker credentials, session tokens, or full phone
  numbers. Any development OTP logging must be restricted to local development.

## Frontend (`frontend/**`)

- Check protected navigation, strict TypeScript, and alignment with the API
  contract. Verify loading, empty, error, and stale-data states where applicable.
- Check keyboard access, focus handling, and mobile layout for changed flows.
- Keep simulated data and actions visibly labeled. Flag browser-exposed
  credentials or demo flows that can call live broker or order endpoints.

## API contracts (`contracts/**`)

- Check endpoint, schema, status-code, and header changes against existing
  consumers. Flag breaking changes and missing error responses.
- For auth changes, verify that cookie and CSRF behavior matches the contract
  and that multiple Set-Cookie values remain separate.
