"""Publish the nightly verdict as a commit status (context ``qa/nightly``) on each tested PR head.

Owner policy (2026-11-25): QA runs nightly, and only critical findings block a merge.
The status is ``failure`` when the candidate's verdict is NOT_ELIGIBLE (a critical failure,
or results missing, stale or cancelled), ``error`` when no report was produced, and
``success`` otherwise. High, medium and low findings are listed in the report but do not block.

The status is attached to the exact head commit that was tested. A later push to the PR has
no ``qa/nightly`` status until the next nightly run or a manual run with ``target=<PR number>``.

Reads only JSON written by morning_report.py; never runs candidate code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

CONTEXT = "qa/nightly"


def statuses(matrix: list[dict], reports: dict, run_url: str) -> list[dict]:
    out = []
    for m in matrix:
        if not m.get("pr") or not m.get("merge_sha"):
            continue  # main, single-sha and integration candidates have no PR head to mark
        head = m["merge_sha"].split()[-1]
        rep = reports.get(m["label"])
        if not rep:
            state, desc = "error", "Nightly QA produced no report for this commit"
        else:
            gate = rep["merge_eligibility"]
            counts = rep.get("defects_by_severity") or {}
            if gate["verdict"] == "ELIGIBLE":
                state = "success"
                desc = f"No critical findings ({len(gate.get('warnings', []))} non-blocking)"
            else:
                state = "failure"
                first = gate["reasons"][0] if gate["reasons"] else "not eligible"
                desc = f"Blocked: {first}"
            if counts.get("critical"):
                desc = f"{counts['critical']} critical defect(s). " + desc
        out.append(
            {
                "pr": m["pr"],
                "sha": head,
                "state": state,
                "description": desc[:140],
                "context": CONTEXT,
                "target_url": run_url,
            }
        )
    return out


def post(repo: str, token: str, s: dict) -> None:
    body = {k: s[k] for k in ("state", "description", "context") if s.get(k)}
    if s.get("target_url"):
        body["target_url"] = s["target_url"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/statuses/{s['sha']}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
        if resp.status >= 300:
            raise RuntimeError(f"status API returned {resp.status}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--morning", required=True, help="morning.json from morning_report.py")
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--run-url", default="")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    morning = json.loads(Path(args.morning).read_text()) if Path(args.morning).exists() else {}
    items = statuses(json.loads(args.matrix)["include"], morning.get("reports", {}), args.run_url)
    token = os.environ.get("GITHUB_TOKEN", "")
    failed = 0
    for s in items:
        print(f"PR #{s['pr']} {s['sha'][:12]}: {s['state']} - {s['description']}")
        if args.dry_run:
            continue
        try:
            post(args.repo, token, s)
        except Exception as exc:  # noqa: BLE001 - report and keep going for the other PRs
            failed += 1
            print(f"::error::could not set status on PR #{s['pr']}: {type(exc).__name__}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
