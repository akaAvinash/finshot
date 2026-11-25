# Defect report template

The supervisor drafts these automatically in `defects.md`; humans complete the rest.

```
ID:               QA-XXXXXXXX (signature hash) / DEF-NNN once triaged
Title:            <component>: <observed behaviour>
Severity:         critical | high | medium | low   (impact if real)
Confidence:       high | medium | low              (how sure the cause is product)
Category:         product | qa-framework | environment
Requirement(s):   AUTH-... (REQUIREMENTS_TRACEABILITY.csv)
Repository / commit tested: akaAvinash/tradeo @ <sha>; PR #<n> base <sha> head <sha>
Environment:      runner, Postgres/Redis versions, backend settings that differ from defaults
Steps to reproduce:
  1. ...
  (command: python -m pytest -c qa/pytest.ini '<test path>::<name>')
Expected:         <with contract/doc reference>
Actual:           <status, body, headers; redacted>
Evidence:         artifact name / path; logs redacted
Suspected cause:  <rule-based or human; AI notes labelled as AI>
Workaround:       none / ...
```

Severity guide: critical = money, auth bypass, data leak, unauthorised broker action; high = security control or
financial rule wrong without direct loss; medium = functional bug with workaround; low = cosmetic or diagnostics.
