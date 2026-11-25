"""Turn `npm audit --json` output into JUnit, keeping npm's own severity per package.

Severity mapping (npm -> QA): critical -> critical, high -> high, moderate -> medium,
low/info -> low. Under the owner's critical-only policy, only a critical advisory
blocks; the rest are warnings. If npm audit could not produce a report (network,
registry or lockfile error), the result is tagged ``incomplete`` and the gate blocks,
because nothing then shows that no critical advisory applies.

Reads the JSON from a file (``--input``) and the npm exit code (``--returncode``),
so it never runs npm itself and works on the output of the workflow step.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

SEVERITY = {"critical": "critical", "high": "high", "moderate": "medium", "low": "low", "info": "low"}


def audit_cases(returncode: int, stdout: str) -> tuple[list[str], int]:
    """JUnit test cases from one npm audit run, and how many of them fail."""
    try:
        data = json.loads(stdout)
        vulns = data.get("vulnerabilities") if isinstance(data, dict) else None
        if not isinstance(vulns, dict) or (isinstance(data, dict) and "error" in data):
            vulns = None
    except ValueError:
        vulns = None
    # npm audit exits non-zero when it finds advisories; a non-zero exit without any is a failed run.
    if vulns is not None and returncode != 0 and not vulns:
        vulns = None
    if vulns is None:
        return [
            '<testcase classname="npm_audit" name="npm-audit-ran">'
            '<properties><property name="tag" value="incomplete"/><property name="requirement" value="SEC-DEP-001"/>'
            f'</properties><error message="npm audit did not complete">{escape(stdout[-2000:])}</error></testcase>'
        ], 1
    cases: list[str] = []
    for name in sorted(vulns):
        v = vulns[name]
        sev = SEVERITY.get(str(v.get("severity", "")).lower(), "high")
        via = [x if isinstance(x, str) else x.get("title") or x.get("url") or "" for x in v.get("via", [])]
        msg = f"{name} {v.get('range', '')} [{v.get('severity')}] {'; '.join(filter(None, via))[:300]}"
        cases.append(
            f'<testcase classname="npm_audit" name={quoteattr(name)}>'
            f'<properties><property name="severity" value="{sev}"/><property name="suite" value="security"/>'
            '<property name="requirement" value="SEC-DEP-001"/></properties>'
            f"<failure message={quoteattr(msg)}/></testcase>"
        )
    if not cases:
        cases.append(
            '<testcase classname="npm_audit" name="no-known-vulnerabilities">'
            '<properties><property name="requirement" value="SEC-DEP-001"/></properties></testcase>'
        )
        return cases, 0
    return cases, len(cases)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="file holding `npm audit --json` output")
    ap.add_argument("--returncode", type=int, required=True)
    ap.add_argument("--junit", required=True)
    args = ap.parse_args()
    raw = Path(args.input).read_text() if Path(args.input).exists() else ""
    cases, failures = audit_cases(args.returncode, raw)
    Path(args.junit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.junit).write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="npm-audit" tests="{len(cases)}" '
        f'failures="{failures}">{"".join(cases)}</testsuite></testsuites>'
    )
    print(f"{failures} npm audit finding(s)")
    return 0  # the verdict comes from the report (severity-aware), not from this step


if __name__ == "__main__":
    raise SystemExit(main())
