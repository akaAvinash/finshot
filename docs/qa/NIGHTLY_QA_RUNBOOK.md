# Nightly QA runbook

Workflow: `.github/workflows/qa-nightly.yml`. Schedule `30 18 * * *` UTC = 00:00 IST.
**GitHub only runs schedules from the default branch**, so nothing runs nightly until the workflow PR is merged into `main`.
GitHub may delay scheduled runs at busy times; the 06:00 IST report target depends on runner availability.

## What happens

1. `discover` (read-only token): lists open PRs; pins each PR's head sha and the current tip of its base branch; checks the merge with `git merge-tree`; skips drafts, fork PRs and conflicts (reported, not tested); flags stacked PRs and tests them against their own base branch; caps at 6 PRs. Writes `candidates.json`.
2. `candidate` matrix (max 3 parallel): main plus each testable PR through `qa-suite.yml` with everything (slow tests and Playwright e2e included).
3. `morning-report`: one report per candidate and `MORNING_REPORT.md` (exact commits, failures, fix-first list, merge-eligible PRs, untested PRs, untested features, AI status). Published as the run summary and the `morning-report` artifact (30 days).
4. `pr-status` (`statuses: write`, no AI key): sets the commit status `qa/nightly` on each tested PR head. `failure` only for a critical finding or incomplete results; high/medium/low findings are warnings. This is the only QA signal on PRs (no per-PR QA run, owner policy 2026-11-25).

Integration candidates are tested only when given explicitly: Actions → qa-nightly → Run workflow → `integration: 12,14`.
PRs targeting different bases are refused as an incompatible candidate.

## Manual runs (mode D)

After pushing a fix to a PR, re-check it without waiting for the night: Run workflow with `target=<PR number>`; it sets `qa/nightly` on the new head.


Actions → qa-nightly → Run workflow. `target`: `nightly`, `main`, a PR number, or a 40-char sha (validated).
`qa_markers`: a pytest `-m` expression over the registered markers, e.g. `not slow`, `critical_gate`, `needs_services and not outage`. Empty runs everything.

## When it fails

| Symptom | Action |
|---|---|
| `discover` failed | Check token permission errors; the run produced no report |
| Candidate `prepare` failed with merge conflict | PR needs a rebase; not a test failure |
| Many tests fail with connection errors | Environment category in `defects.md`; re-run the job before filing a product defect |
| One product failure | Use the repro command in `defects.md`; evidence is redacted |
| AI section says disabled | Expected unless `QA_AI_PROVIDER`, `QA_AI_DAILY_BUDGET_USD` (repo variables) and `QA_ANTHROPIC_API_KEY` / `QA_OPENAI_API_KEY` (secrets) are set |

## Home-server runners (future)

Do not run PR code on the production home server. A self-hosted runner must be an ephemeral VM/container per job,
no access to the homelab network or Tailscale, no stored credentials, wiped after each job.
