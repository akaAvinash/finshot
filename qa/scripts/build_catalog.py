"""Regenerate docs/qa/TEST_CASE_CATALOG.csv and the automated part of REQUIREMENTS_TRACEABILITY.csv.

Test metadata comes from the pytest markers in qa/tests (req, severity, suite,
critical_gate, slow) and the first docstring line. Requirement text comes from
qa/policies/requirements.csv, the single hand-maintained list of requirements
(including specified-only and not-implemented ones). Run from the repo root:

    python qa/scripts/build_catalog.py           # write
    python qa/scripts/build_catalog.py --check   # fail if the files are stale
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "qa" / "tests"
REQS = ROOT / "qa" / "policies" / "requirements.csv"
TRACE = ROOT / "docs" / "qa" / "REQUIREMENTS_TRACEABILITY.csv"
CATALOG = ROOT / "docs" / "qa" / "TEST_CASE_CATALOG.csv"


def _marks(decorators: list[ast.expr]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in decorators:
        call = d if isinstance(d, ast.Call) else None
        target = call.func if call else d
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute):
            if target.value.attr == "mark":
                args = [a.value for a in (call.args if call else []) if isinstance(a, ast.Constant)]
                out.setdefault(target.attr, []).extend(str(a) for a in args)
    return out


def collect() -> list[dict[str, str]]:
    rows = []
    for path in sorted(TESTS.rglob("test_*.py")):
        tree = ast.parse(path.read_text())
        module_marks: dict[str, list[str]] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in node.targets):
                if isinstance(node.value, ast.List):
                    module_marks = _marks(list(node.value.elts))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                m = _marks(node.decorator_list)
                merged = {k: module_marks.get(k, []) + m.get(k, []) for k in set(module_marks) | set(m)}
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                rel = path.relative_to(ROOT).as_posix()
                rows.append(
                    {
                        "test_id": f"{rel}::{node.name}",
                        "suite": (merged.get("suite") or ["?"])[-1],
                        "requirements": " ".join(merged.get("req", [])),
                        "severity": (merged.get("severity") or ["medium"])[-1],
                        "critical_gate": "yes" if "critical_gate" in merged else "no",
                        "needs_services": "yes" if "needs_services" in merged else "no",
                        "schedule": "nightly" if "slow" in merged else "pr+nightly",
                        "purpose": doc[0] if doc else node.name[5:].replace("_", " "),
                    }
                )
    return rows


def render(rows: list[dict[str, str]], fields: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def build() -> tuple[str, str, list[str]]:
    tests = collect()
    reqs = list(csv.DictReader(REQS.open(newline="")))
    by_req: dict[str, list[str]] = {}
    for t in tests:
        for r in t["requirements"].split():
            by_req.setdefault(r, []).append(t["test_id"].split("::")[1])
    known = {r["req_id"] for r in reqs}
    problems = [f"test references unknown requirement {r}" for r in by_req if r not in known]
    trace = []
    for r in reqs:
        ts = by_req.get(r["req_id"], [])
        status = r["status"]
        if ts and status in ("specified", "not_implemented"):
            problems.append(f"{r['req_id']} has tests but status {status}")
        if status == "automated" and not ts:
            problems.append(f"{r['req_id']} marked automated but no test references it")
        trace.append({**r, "tests": " ".join(sorted(set(ts)))})
    fields = ["req_id", "area", "engine", "requirement", "source", "priority", "status", "tests"]
    return render(trace, fields), render(tests, list(tests[0].keys())), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    trace, catalog, problems = build()
    for p in problems:
        print(p, file=sys.stderr)
    if args.check:
        stale = [p.name for p, text in ((TRACE, trace), (CATALOG, catalog)) if not p.exists() or p.read_text() != text]
        for s in stale:
            print(f"{s} is stale; run python qa/scripts/build_catalog.py", file=sys.stderr)
        return 1 if (stale or problems) else 0
    TRACE.write_text(trace)
    CATALOG.write_text(catalog)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
