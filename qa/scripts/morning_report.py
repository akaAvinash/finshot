"""Build one report per nightly candidate, then the consolidated morning report.

Answers: what was tested (exact commits), what failed, critical defects, what
to fix first, which PRs are merge-eligible, what is untested, what is blocked.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from qa.scripts.nightly_candidates import gh

REQUIRED = ["backend", "qa", "frontend-unit", "secret-scan", "dependency-audit", "npm-audit"]
E2E_SOURCE = "frontend-e2e"
UNKNOWN_SHA = "current-commit-unknown"  # never equals a tested sha, so a failed lookup fails closed


def required_sources(run_e2e: bool) -> list[str]:
    """Result sets every candidate must produce; the e2e set only when e2e was requested."""
    return [*REQUIRED, E2E_SOURCE] if run_e2e else list(REQUIRED)


def supervisor_cmd(
    m: dict,
    files: list[str],
    dest: str,
    run_url: str,
    *,
    run_e2e: bool,
    candidate_result: str,
    current_sha: str | None,
) -> list[str]:
    """Command line for one candidate's report. Pure, so the gate inputs can be tested."""
    tested = m["merge_sha"].split()[-1] if m["merge_sha"] else m["checkout_sha"]
    cmd = [
        sys.executable,
        "-m",
        "qa.ai_agent.supervisor",
        "--junit",
        *(files or ["/dev/null"]),
        "--out",
        dest,
        "--required",
        *required_sources(run_e2e),
        "--tested-sha",
        tested,
        "--expected-sha",
        current_sha or UNKNOWN_SHA,
        "--base-sha",
        m["checkout_sha"],
        "--head-sha",
        m["merge_sha"] or m["checkout_sha"],
        "--branch",
        m["label"],
        "--run-url",
        run_url,
        "--title",
        f"Nightly: {m['label']}",
        "--environment",
        "GitHub-hosted ubuntu-latest, Postgres 16 + Redis 7 service containers",
    ]
    # A cancelled run is not a pass even if some JUnit files were written first. Plain
    # failures are deliberately not passed: non-critical failures must stay warnings.
    if candidate_result == "cancelled":
        cmd += ["--jobs", json.dumps({"candidate": "cancelled"})]
    if m.get("pr"):
        cmd += ["--pr", str(m["pr"])]
    if m["label"] != "main":  # one AI pass at most per night: main only
        cmd.append("--no-ai")
    return cmd


def current_sha_for(m: dict, repo: str, token: str, default_branch: str = "main") -> str | None:
    """Tip the candidate should match now: the PR head, or the default branch tip. None if unknown."""
    if not repo or not token:
        return None
    try:
        if m.get("pr"):
            return gh(f"/repos/{repo}/pulls/{m['pr']}", token)["head"]["sha"]  # type: ignore[index]
        if m["label"] == "main":
            return gh(f"/repos/{repo}/commits/{default_branch}", token)["sha"]  # type: ignore[index]
    except Exception:  # noqa: BLE001 - any lookup failure means unknown, which blocks
        return None
    return (
        m["merge_sha"].split()[-1] if m["merge_sha"] else m["checkout_sha"]
    )  # explicit sha / integration: nothing newer exists


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-url", default="")
    ap.add_argument("--run-e2e", choices=["true", "false"], default="false")
    ap.add_argument("--candidate-result", default="success", help="needs.candidate.result")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = ap.parse_args()
    run_e2e = args.run_e2e == "true"
    token = os.environ.get("GITHUB_TOKEN", "")

    results = Path(args.results)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    matrix = json.loads(args.matrix)["include"]
    cands = json.loads(Path(args.candidates).read_text()) if Path(args.candidates).exists() else {"prs": []}

    rows = []
    reports = {}
    for m in matrix:
        label = m["label"]
        files = sorted(str(p) for p in results.glob(f"junit-{label}-*/**/*.xml"))
        dest = out / label
        cmd = supervisor_cmd(
            m,
            files,
            str(dest),
            args.run_url,
            run_e2e=run_e2e,
            candidate_result=args.candidate_result,
            current_sha=current_sha_for(m, args.repo, token),
        )
        subprocess.run(cmd, check=False)
        rep_path = dest / "qa-report.json"
        rep = json.loads(rep_path.read_text()) if rep_path.exists() else None
        reports[label] = rep
        rows.append((m, rep))

    now = datetime.now(UTC)
    lines = [
        "# Tradeo nightly QA: morning report",
        "",
        f"Generated {now.astimezone(ZoneInfo('Asia/Kolkata')):%Y-%m-%d %H:%M} IST. Run: {args.run_url or 'local'}",
        "",
        "## Candidates tested (exact commits)",
        "",
        "| Candidate | Base | Head | Total | Passed | Failed | Blocked | Verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m, rep in rows:
        if rep is None:
            lines.append(
                f"| {m['label']} | {m['checkout_sha'][:12]} | {(m['merge_sha'] or m['checkout_sha'])[:12]} | - | - | - | - | NO RESULT |"
            )
            continue
        t = rep["totals"]
        lines.append(
            f"| {m['label']} | {m['checkout_sha'][:12]} | {(m['merge_sha'] or m['checkout_sha'])[-40:][:12]} | "
            f"{t['total']} | {t['passed']} | {t['failed']} | {t['blocked']} | {rep['merge_eligibility']['verdict']} |"
        )
    not_tested = [p for p in cands.get("prs", []) if p.get("status") != "test"]
    if not_tested:
        lines += ["", "## Open PRs not tested", ""]
        lines += [
            f"- #{p['pr']} {p['title']}: {p['status']}"
            + (f" (stacked on #{p['stacked_on']})" if p.get("stacked_on") else "")
            for p in not_tested
        ]
    if cands.get("integration"):
        lines += ["", f"Integration candidate {cands['integration']['prs']}: {cands['integration']['status']}"]

    fix_first = []
    for m, rep in rows:
        for d in (rep or {}).get("defects", []):
            fix_first.append((d["severity"], m["label"], d))
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    fix_first.sort(key=lambda x: (order.get(x[0], 9), x[1]))
    lines += ["", "## Fix first", ""]
    lines += [
        f"{i}. [{s}] {label}: {d['title']} ({d['id']}, {len(d['tests'])} test(s))"
        for i, (s, label, d) in enumerate(fix_first[:10], 1)
    ] or ["Nothing failed."]

    main_rep = reports.get("main")
    if main_rep:
        gaps = main_rep["coverage_gaps"]
        lines += [
            "",
            "## Untested features (from traceability, main)",
            "",
            f"{len(gaps['not_automated'])} requirements have no automation yet; "
            f"{len(gaps['automated_but_not_run'])} automated requirements did not run.",
        ]
        lines += ["", "## AI analysis", "", f"- {main_rep['ai']['status']}"]
    lines += [
        "",
        "Merge eligibility is a recommendation from fixed rules. Merging stays with the owner.",
    ]
    (out / "MORNING_REPORT.md").write_text("\n".join(lines) + "\n")
    (out / "morning.json").write_text(json.dumps({"candidates": [m for m, _ in rows], "reports": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
