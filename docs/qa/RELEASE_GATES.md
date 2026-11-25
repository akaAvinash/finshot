# Release and merge gates

Owner policy (2026-11-25): QA runs **nightly only** (no per-PR QA run), and **only critical findings block a merge**.

Implemented in `qa/ai_agent/analysis.py::merge_eligibility` (`--block-on`, default `critical`). The nightly workflow
publishes each PR's verdict as the commit status **`qa/nightly`** on the exact head commit it tested
(`qa/scripts/publish_pr_status.py`).

A candidate is **NOT_ELIGIBLE** when any of these holds:

| Rule | Source of truth |
|---|---|
| No results at all | JUnit files |
| A mandatory result set is missing: `backend`, `qa`, `frontend-unit`, `secret-scan`, `dependency-audit` | artifact names |
| A mandatory job ended anything other than success (failure, cancelled, skipped) | `needs.suite.result` |
| Any **critical** severity test failed or errored (e.g. auth bypass, cross-user access, secret in logs or repo) | test `severity` marker / JUnit property |
| A `critical_gate` test was skipped or blocked | markers |
| Results are for a different commit than the latest head (stale) | tested vs expected sha |

High, medium and low failures are listed as warnings in the report and morning report; they do not block.
Missing, stale, cancelled or unexecuted-critical results still block, because they cannot show that nothing critical failed.

Status states: `success` (no critical findings), `failure` (critical finding or incomplete results), `error` (no report).
A push after the nightly run leaves the new head without `qa/nightly` until the next night, or a manual run with
`target=<PR number>`. If `qa/nightly` is made a required check, that new head waits for one of those runs.

Also required, outside this tool:
- CodeRabbit check per repository rules.
- No unresolved critical/high defects from earlier runs (owner judgement until a tracker exists).
- No unauthorised broker operations or credential leakage (covered by security suite and secret scan).

Retries never turn a failure into a pass. `continue-on-error` is not used in any workflow.

The verdict is a recommendation. Merging stays with the owner or the repository's explicit policy.
`qa/nightly` blocks merges only if the owner adds it as a required status check (a repository setting QA has not changed).
