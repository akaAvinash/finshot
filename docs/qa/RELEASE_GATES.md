# Release and merge gates

Implemented in `qa/ai_agent/analysis.py::merge_eligibility` and enforced by the `qa gate` job (`.github/workflows/qa-pr.yml`).

A candidate is **NOT_ELIGIBLE** when any of these holds:

| Rule | Source of truth |
|---|---|
| No results at all | JUnit files |
| A mandatory result set is missing: `backend`, `qa`, `frontend-unit`, `secret-scan`, `dependency-audit` | artifact names |
| A mandatory job ended anything other than success (failure, cancelled, skipped) | `needs.suite.result` |
| Any critical or high severity test failed or errored | test `severity` marker / JUnit property |
| A `critical_gate` test was skipped or blocked | markers |
| Results are for a different commit than the latest head (stale) | tested vs expected sha |

Medium and low failures are listed as warnings; they do not block by themselves.

Also required, outside this tool:
- CodeRabbit check per repository rules.
- No unresolved critical/high defects from earlier runs (owner judgement until a tracker exists).
- No unauthorised broker operations or credential leakage (covered by security suite and secret scan).

Retries never turn a failure into a pass. `continue-on-error` is not used in any workflow.

The verdict is a recommendation. Merging stays with the owner or the repository's explicit policy.
The `qa gate` check becomes enforced only if the owner adds it as a required status check (a repository setting QA has not changed).
