# MCP gateway test plan

Status on main: no MCP gateway exists (MCP-001..003 are `not_implemented`). This plan is the acceptance bar for when it lands.

| Area | Tests |
|---|---|
| Protocol | Version negotiation, unknown versions refused, malformed JSON-RPC rejected |
| Discovery and schemas | Tool list matches allowlist; input/output validated against declared schema; unknown tools refused |
| AuthN/AuthZ | Per-user tokens; tools scoped to the caller's accounts; no order tools exposed (unauthorised order operations must be impossible, not just denied) |
| Untrusted content | Malicious tool descriptions, prompt injection in tool results, oversized responses, control characters |
| Network | SSRF to private ranges/metadata IPs, DNS rebinding (resolve-then-connect pinning), redirect to internal hosts |
| Secrets | Credentials never in tool results, logs or errors |
| Resilience | Timeouts, slow streams, server crash mid-call, retries bounded |

Harness: a local hostile MCP server fixture (`qa/mocks/`, to be added) serving crafted descriptions and responses.
