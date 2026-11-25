# AI QA agent design

The agent is a set of roles implemented as functions in one process
(`python -m qa.ai_agent.supervisor`). Each role has a deterministic core; an LLM
can add notes to that core when the owner authorises API access.

| Role | Deterministic core (always runs) | Optional AI add-on |
|---|---|---|
| QA Supervisor | Suite selection from changed files (`select_suites`), orchestration, consolidated report | none |
| Requirements & test design | Traceability gaps from `REQUIREMENTS_TRACEABILITY.csv` | (planned) missing scenario proposals, filed as suggestions only |
| API & integration | Contract violations surfaced by the client, grouped | covered by defect-analysis notes |
| UI | Playwright JUnit ingestion; traces uploaded as artifacts | (planned) screenshot review |
| Security | Severity from markers; secret/dependency scans | `security` role notes on auth/security defects |
| Financial | Oracle tests; severity from markers | `financial` role notes |
| Reliability & performance | Outage test results | (planned) Locust report review |
| Defect analysis | Group by normalised signature, classify product / framework / environment, draft reports with repro command and redacted evidence | `defect-analysis` role notes |
| Reporting | Markdown + JSON report, merge eligibility from fixed rules (`RELEASE_GATES.md`) | none: the verdict is never AI-generated |

## Provider management (`qa/ai_agent/providers.py`)

- Interface `LLMProvider.complete(system, user, max_tokens, timeout)`; implementations for Anthropic and OpenAI SDKs, imported lazily (optional dependencies).
- Enabled only when **all** are set: `QA_AI_PROVIDER`, `QA_AI_DAILY_BUDGET_USD`, the provider key, and a known or configured price. Default Anthropic model `claude-opus-5-5` ($4 / $20 per MTok, Anthropic pricing table cached 2026-11-03); override with `QA_AI_MODEL` and `QA_AI_INPUT_USD_PER_MTOK` / `QA_AI_OUTPUT_USD_PER_MTOK`.
- Limits: daily spend ledger (refuses a call whose worst case would exceed the cap), 12 calls per run, 4000 output tokens, 90 s timeout, 1 retry, circuit breaker after 2 consecutive failures, cache keyed by the redacted prompt.
- Refusals and errors raise `LLMUnavailable`; the report then states the AI limitation and continues.

Interactive Claude Code / Codex subscriptions are not assumed to give unattended API access. Nothing is purchased; the owner must create and fund a key and set the cap.

## Safety

- Input: test logs, code, PR text and errors are untrusted. They are redacted (`core/redaction.py`), wrapped in explicit delimiters, and the model is told not to follow instructions inside them.
- Output: must be one JSON object matching a strict schema (no extra fields, bounded lengths). Notes are attached only to defect ids the agent sent; anything else is dropped.
- Capability: the agent has no tools. It cannot run commands, call GitHub, merge, approve, change code, read secrets other than its own key, or place orders. A policy test fails if `ai_agent/` gains `subprocess`, `eval`, `exec` or GitHub write paths.
- In CI the key is only exposed to the report job, which never checks out or runs candidate code, and only in the nightly workflow (not on PRs).
- AI-proposed tests are suggestions: they become gating tests only after a human adds them under `qa/tests` with markers and review.
