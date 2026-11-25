"""Read JUnit XML (pytest, vitest, playwright) into one result model.

JUnit is the source of truth for outcomes. Nothing downstream may change an
outcome; analysis only adds interpretation.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class

    source: str  # which junit file / suite group
    nodeid: str
    outcome: str  # passed | failed | error | skipped | blocked
    duration: float
    message: str = ""
    details: str = ""
    severity: str = "medium"
    requirements: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    suite: str = ""

    @property
    def is_failure(self) -> bool:
        return self.outcome in ("failed", "error")


_BLOCKED_MARKERS = ("blocked", "unset", "not implemented", "not_implemented")


def parse_junit(path: Path, source: str | None = None) -> list[TestResult]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    out: list[TestResult] = []
    for suite in suites:
        for case in suite.findall("testcase"):  # direct children: nested suites are visited on their own
            cls = case.get("classname", "")
            name = case.get("name", "")
            nodeid = f"{cls}::{name}" if cls else name
            outcome, message, details = "passed", "", ""
            for tag in ("failure", "error", "skipped"):
                el = case.find(tag)
                if el is not None:
                    message = (el.get("message") or "").strip()
                    details = (el.text or "").strip()
                    outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                    break
            if outcome == "skipped" and any(m in message.lower() for m in _BLOCKED_MARKERS):
                outcome = "blocked"
            r = TestResult(
                source=source or path.stem,
                nodeid=nodeid,
                outcome=outcome,
                duration=float(case.get("time") or 0),
                message=message[:500],
                details=details[-4000:],
            )
            props = case.find("properties")
            if props is not None:
                for p in props.iter("property"):
                    n, v = p.get("name"), p.get("value") or ""
                    if n == "requirement":
                        r.requirements.append(v)
                    elif n == "severity":
                        r.severity = v
                    elif n == "tag":
                        r.tags.append(v)
                    elif n == "suite":
                        r.suite = v
            if not r.suite:
                r.suite = source or path.stem
            out.append(r)
    return out


def load_many(paths: list[Path]) -> list[TestResult]:
    results: list[TestResult] = []
    for p in paths:
        if p.exists() and p.stat().st_size > 0:
            results.extend(parse_junit(p, p.stem))
    return results
