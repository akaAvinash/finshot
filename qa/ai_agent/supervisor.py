"""QA Supervisor: turns test results into the consolidated QA report.

    python -m qa.ai_agent.supervisor --junit out/*.xml --out out/report \\
        --required qa-pr --tested-sha $SHA --expected-sha $SHA

Steps (each role is a function; AI is an optional add-on to each):
  1. Ingest JUnit results (authoritative outcomes).
  2. Defect analysis: group failures, classify, draft defect reports.
  3. Coverage: traceability gaps.
  4. Release gate: merge eligibility from fixed rules.
  5. Optional AI review (security, financial, defect triage) within budget.
  6. Write JSON, Markdown summary and defect drafts.

The AI layer receives redacted, delimited data and may only return JSON that
matches a schema. Its output is labelled as AI opinion and never changes an
outcome, a defect severity or the merge verdict.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from qa.ai_agent import analysis
from qa.ai_agent.providers import LLMUnavailable, load_provider
from qa.config.settings import REPO_ROOT
from qa.reporting.render import render_defects, render_markdown
from qa.reporting.results import TestResult, load_many

TRACE = REPO_ROOT / "docs" / "qa" / "REQUIREMENTS_TRACEABILITY.csv"

_AI_SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "additionalProperties": False,
    "properties": {
        "findings": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "required": ["defect_id", "explanation", "suggested_next_step"],
                "additionalProperties": False,
                "properties": {
                    "defect_id": {"type": "string", "maxLength": 20},
                    "explanation": {"type": "string", "maxLength": 1200},
                    "suggested_next_step": {"type": "string", "maxLength": 600},
                    "missing_test_idea": {"type": "string", "maxLength": 600},
                },
            },
        }
    },
}

_ROLE_PROMPTS = {
    "defect-analysis": "You are a QA defect analyst for a trading platform. For each defect, explain the most likely root cause from the evidence and the next diagnostic step. Do not claim a fix is verified.",
    "security": "You are a security QA reviewer. For each security-relevant defect, explain the risk and a missing negative test. Do not suggest disabling checks.",
    "financial": "You are a financial QA reviewer. Explain the monetary impact of each defect and which independent check would confirm it.",
}


def _flaky(original: list[TestResult], rerun: list[TestResult]) -> list[str]:
    passed_on_rerun = {r.nodeid for r in rerun if r.outcome == "passed"}
    return sorted(r.nodeid for r in original if r.is_failure and r.nodeid in passed_on_rerun)


def _ai_review(defects: list[analysis.DefectCandidate], state_dir: Path) -> tuple[str, list[str]]:
    llm, status = load_provider(state_dir)
    if llm is None or not defects:
        return (status if llm is None else f"{status}; nothing to review"), []
    errors: list[str] = []
    by_role = {
        "security": [d for d in defects if d.title.startswith(("security", "authentication"))],
        "financial": [d for d in defects if d.title.startswith("financial")],
        "defect-analysis": defects,
    }
    for role, items in by_role.items():
        if not items:
            continue
        payload = json.dumps(
            [{"defect_id": d.id, "title": d.title, "severity": d.severity, "evidence": d.evidence} for d in items[:10]]
        )
        try:
            data = llm.ask_json(role, _ROLE_PROMPTS[role], payload, _AI_SCHEMA)
        except LLMUnavailable as exc:
            errors.append(f"{role}: {exc}")
            continue
        known = {d.id: d for d in items}
        for f in data["findings"]:
            d = known.get(f["defect_id"])
            if d is not None:  # ignore findings about ids we did not send
                note = f"[AI {role}] {f['explanation']} Next: {f['suggested_next_step']}"
                if f.get("missing_test_idea"):
                    note += f" Test idea: {f['missing_test_idea']}"
                d.ai_notes.append(note)
    spent = f"; spent ~${llm.spent_usd:.4f} this run"
    return status + spent + (f"; errors: {', '.join(errors)}" if errors else ""), errors


def build_report(args: argparse.Namespace) -> dict:
    results = load_many([Path(p) for p in args.junit])
    rerun = load_many([Path(p) for p in args.rerun_junit]) if args.rerun_junit else []
    defects = analysis.group_failures(results)
    reqs = analysis.load_traceability(TRACE)
    gaps = analysis.coverage_gaps(reqs, results)
    jobs = json.loads(args.jobs) if args.jobs else None
    gate = analysis.merge_eligibility(
        results,
        required_sources=args.required or [],
        tested_sha=args.tested_sha,
        expected_sha=args.expected_sha,
        job_outcomes=jobs,
    )
    changed = Path(args.changed_files).read_text().split() if args.changed_files else []
    ai_status, _ = (
        _ai_review(defects, Path(args.out) / ".ai-state") if not args.no_ai else ("AI analysis disabled (--no-ai)", [])
    )

    def count(o: str) -> int:
        return sum(1 for r in results if r.outcome == o)

    report = {
        "schema": "tradeo-qa-report/1",
        "repository": os.environ.get("GITHUB_REPOSITORY", "akaAvinash/tradeo"),
        "branch": args.branch,
        "pr_number": args.pr,
        "base_sha": args.base_sha,
        "head_sha": args.head_sha,
        "tested_sha": args.tested_sha,
        "environment": args.environment,
        "run_url": args.run_url,
        "started_at": args.started_at,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "totals": {
            "total": len(results),
            "passed": count("passed"),
            "failed": count("failed") + count("error"),
            "skipped": count("skipped"),
            "blocked": count("blocked"),
        },
        "by_source": {
            s: {
                o: sum(1 for r in results if r.source == s and r.outcome == o)
                for o in ("passed", "failed", "error", "skipped", "blocked")
            }
            for s in sorted({r.source for r in results})
        },
        "flaky_candidates": _flaky(results, rerun),
        "defects": [asdict(d) for d in defects],
        "defects_by_severity": {s: sum(1 for d in defects if d.severity == s) for s in analysis.SEVERITY_ORDER},
        "coverage_gaps": {k: [asdict(q) for q in v] for k, v in gaps.items()},
        "suite_selection": analysis.select_suites(changed) if changed else {},
        "merge_eligibility": asdict(gate),
        "ai": {
            "status": ai_status,
            "limitations": [
                "AI notes are opinions on redacted evidence; they never change outcomes, severities or the merge verdict.",
                "Without authorised API access the report is produced by deterministic rules only.",
                "Defect grouping is by normalised failure message and can merge or split distinct root causes.",
            ],
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m qa.ai_agent.supervisor")
    ap.add_argument("--junit", nargs="+", required=True)
    ap.add_argument("--rerun-junit", nargs="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--required", nargs="*", help="junit file stems that must be present")
    ap.add_argument("--jobs", help='JSON {"job": "success|failure|cancelled|skipped"} for mandatory jobs')
    ap.add_argument("--changed-files")
    ap.add_argument("--branch")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--base-sha")
    ap.add_argument("--head-sha")
    ap.add_argument("--tested-sha")
    ap.add_argument("--expected-sha")
    ap.add_argument("--environment", default="local disposable Postgres 16 + Redis 7")
    ap.add_argument("--run-url")
    ap.add_argument("--started-at")
    ap.add_argument("--title", default="Tradeo QA report")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--fail-on-ineligible", action="store_true")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = build_report(args)
    (out / "qa-report.json").write_text(json.dumps(report, indent=2))
    (out / "qa-summary.md").write_text(render_markdown(report, args.title))
    (out / "defects.md").write_text(render_defects(report))
    print(f"{report['merge_eligibility']['verdict']}: {report['totals']}")
    if args.fail_on_ineligible and report["merge_eligibility"]["verdict"] != "ELIGIBLE":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
