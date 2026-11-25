"""Audit the backend's installed Python dependencies with pip-audit; write JUnit.

One test case per vulnerable package. Severity is 'high' by default because
pip-audit (PyPI advisory data) does not always carry a CVSS score.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

# Installer tooling in the CI virtualenv, not shipped with the product. Reported separately, never gating.
TOOLING = {"pip", "setuptools", "wheel"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", required=True)
    args = ap.parse_args()
    proc = subprocess.run(
        ["pip-audit", "--format", "json", "--progress-spinner", "off", "--skip-editable"],
        capture_output=True,
        text=True,
    )
    cases: list[str] = []
    failures = 0
    try:
        data = json.loads(proc.stdout or "{}")
        deps = data.get("dependencies", data if isinstance(data, list) else [])
    except ValueError:
        deps = None
    if deps is None:
        failures = 1
        cases.append(
            '<testcase classname="dependency_audit" name="pip-audit-ran"><error message="pip-audit output unreadable">'
            f"{escape(proc.stderr[-2000:])}</error></testcase>"
        )
    else:
        seen: set[tuple[str, str]] = set()
        for dep in deps:
            if dep["name"].lower() in TOOLING:
                for v in dep.get("vulns", []):
                    print(f"tooling (not gating): {dep['name']} {dep.get('version')} {v.get('id')}")
                continue
            for v in dep.get("vulns", []):
                key = (dep["name"].lower(), v.get("id", "?"))
                if key in seen:
                    continue
                seen.add(key)
                failures += 1
                msg = f"{dep['name']} {dep.get('version')} {v.get('id')} fix: {', '.join(v.get('fix_versions', [])) or 'none'}"
                cases.append(
                    f'<testcase classname="dependency_audit" name={quoteattr(dep["name"] + ":" + v.get("id", "?"))}>'
                    '<properties><property name="severity" value="high"/><property name="suite" value="security"/>'
                    '<property name="requirement" value="SEC-DEP-001"/></properties>'
                    f"<failure message={quoteattr(msg)}/></testcase>"
                )
        if not failures:
            cases.append(
                '<testcase classname="dependency_audit" name="no-known-vulnerabilities">'
                '<properties><property name="requirement" value="SEC-DEP-001"/></properties></testcase>'
            )
    Path(args.junit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.junit).write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="dependency-audit" tests="{len(cases)}" '
        f'failures="{failures}">{"".join(cases)}</testsuite></testsuites>'
    )
    print(f"{failures} vulnerable dependency finding(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
