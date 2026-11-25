"""Discover nightly regression candidates: open PRs pinned to exact commits, plus main.

Reads open pull requests through the GitHub REST API (read-only token), pins
each PR's head commit and the current tip of its intended base branch, checks
with `git merge-tree` whether the two merge cleanly, and writes:

- a GitHub Actions matrix (`matrix=` output) of candidates to test,
- `candidates.json` describing every PR, including the ones not tested and why.

Rules:
- Draft PRs are listed but not tested.
- A PR whose base is another PR's branch (stacked) is tested against that
  branch's current tip, which is its intended base, and flagged as stacked.
- A PR that does not merge cleanly into its base is reported as a conflict and
  not tested; nothing is tested as a combination unless an integration
  candidate is defined explicitly (--integration "12,14").
- At most --max PRs are tested (oldest update first is dropped).
Run from a full clone (fetch-depth 0).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path


def gh(path: str, token: str) -> list | dict:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tradeo-qa-nightly",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read())


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def base_tip(ref: str) -> str | None:
    if git("fetch", "--no-tags", "origin", ref, check=False).returncode != 0:
        return None
    return git("rev-parse", "FETCH_HEAD").stdout.strip()


_IDENT = {
    "GIT_AUTHOR_NAME": "qa-bot",
    "GIT_AUTHOR_EMAIL": "qa-bot@qa.tradeo.invalid",
    "GIT_COMMITTER_NAME": "qa-bot",
    "GIT_COMMITTER_EMAIL": "qa-bot@qa.tradeo.invalid",
}


def merges_cleanly(base: str, heads: list[str], *, fetch: bool = True) -> tuple[bool, str]:
    """Merge heads onto base in order without touching the work tree.

    `merge-tree --write-tree` returns a tree; each step wraps it in a throwaway
    commit (parents: previous result and the head) so the next step merges
    commits, not trees.
    """
    current = base
    for h in heads:
        if fetch and git("fetch", "--no-tags", "origin", h, check=False).returncode != 0:
            return False, f"cannot fetch {h[:12]}"
        r = git("merge-tree", "--write-tree", current, h, check=False)
        if r.returncode != 0:
            return False, f"conflict merging {h[:12]} onto {current[:12]}"
        tree = r.stdout.split()[0]
        c = subprocess.run(
            ["git", "commit-tree", tree, "-p", current, "-p", h, "-m", "qa: candidate merge"],
            capture_output=True,
            text=True,
            env={**os.environ, **_IDENT},
            check=False,
        )
        if c.returncode != 0:
            return False, f"cannot record merge of {h[:12]}"
        current = c.stdout.strip()
    return True, ""


def open_prs(repo: str, token: str) -> list[dict]:
    """All open PRs, most recently updated first (follows pagination)."""
    out: list[dict] = []
    page = 1
    while True:
        batch = gh(f"/repos/{repo}/pulls?state=open&per_page=100&sort=updated&direction=desc&page={page}", token)
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def apply_nightly_limit(report: list[dict], limit: int) -> list[dict]:
    """Pick at most `limit` testable PRs for the scheduled run.

    A PR left out only because of the limit keeps `testable: True`, so an explicit
    manual request for it can still run.
    """
    testable = [e for e in report if e.get("testable")]
    chosen = testable[:limit]
    for e in testable[limit:]:
        e["status"] = f"not scheduled: over the nightly limit of {limit}"
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "akaAvinash/tradeo"))
    ap.add_argument("--default-branch", default="main")
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--integration", default="", help="comma-separated PR numbers, merged in this order")
    ap.add_argument("--out", default="candidates.json")
    args = ap.parse_args()
    token = os.environ["GITHUB_TOKEN"]

    main_sha = base_tip(args.default_branch)
    if not main_sha:
        raise SystemExit(f"cannot resolve {args.default_branch}")
    prs = open_prs(args.repo, token)
    open_branches = {p["head"]["ref"]: p["number"] for p in prs}

    report: list[dict] = []
    matrix: list[dict] = [{"label": "main", "checkout_sha": main_sha, "merge_sha": "", "pr": 0}]
    for p in prs:
        entry = {
            "pr": p["number"],
            "title": p["title"],
            "author": p["user"]["login"],
            "draft": p["draft"],
            "head_ref": p["head"]["ref"],
            "head_sha": p["head"]["sha"],
            "base_ref": p["base"]["ref"],
            "same_repo": p["head"]["repo"] is not None and p["head"]["repo"]["full_name"] == args.repo,
            "stacked_on": open_branches.get(p["base"]["ref"]),
        }
        if p["draft"]:
            entry["status"] = "skipped: draft"
        elif not entry["same_repo"]:
            entry["status"] = "skipped: fork PR (head not fetchable by sha in this workflow)"
        else:
            tip = base_tip(p["base"]["ref"])
            entry["base_sha"] = tip
            if tip is None:
                entry["status"] = "skipped: base branch not found"
            else:
                ok, why = merges_cleanly(tip, [p["head"]["sha"]])
                entry["status"] = "test" if ok else f"not tested: {why}"
                entry["testable"] = ok
        report.append(entry)

    for e in apply_nightly_limit(report, args.max):
        matrix.append(
            {"label": f"pr-{e['pr']}", "checkout_sha": e["base_sha"], "merge_sha": e["head_sha"], "pr": e["pr"]}
        )

    integration: dict | None = None
    if args.integration.strip():
        nums = [int(x) for x in args.integration.split(",") if x.strip()]
        by_num = {e["pr"]: e for e in report}
        missing = [n for n in nums if n not in by_num]
        bases = {by_num[n]["base_ref"] for n in nums if n in by_num}
        heads = [by_num[n]["head_sha"] for n in nums if n in by_num]
        integration = {"prs": nums, "base_sha": main_sha}
        if missing:
            integration["status"] = f"not tested: PRs not open {missing}"
        elif bases - {args.default_branch} - {by_num[n]["head_ref"] for n in nums}:
            integration["status"] = "not tested: PRs target different bases (incompatible candidate)"
        else:
            ok, why = merges_cleanly(main_sha, heads)
            integration["status"] = "test" if ok else f"not tested: {why}"
            if ok:
                matrix.append(
                    {
                        "label": "integration-" + "-".join(map(str, nums)),
                        "checkout_sha": main_sha,
                        "merge_sha": " ".join(heads),
                        "pr": 0,
                    }
                )

    Path(args.out).write_text(json.dumps({"main_sha": main_sha, "prs": report, "integration": integration}, indent=2))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"matrix={json.dumps({'include': matrix})}\n")
    print(json.dumps({"main_sha": main_sha, "tested": [m["label"] for m in matrix]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
