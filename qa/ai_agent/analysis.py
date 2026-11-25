"""Deterministic analysis: the agent's behaviour when no model is available.

Each function is a QA role's rule-based core. AI output (when authorised) can
add explanation next to these results but never replaces or overrides them.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from qa.core.redaction import redact
from qa.reporting.results import TestResult

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ------------------------------------------------------------ Supervisor --
SUITE_RULES: list[tuple[str, list[str]]] = [
    (
        "backend/app/auth/**",
        ["authentication", "security", "reliability", "contract", "backend-unit", "backend-integration"],
    ),
    ("backend/app/**", ["backend-unit", "backend-integration", "authentication", "security", "reliability"]),
    ("backend/migrations/**", ["backend-integration", "authentication", "reliability"]),
    ("contracts/**", ["contract", "authentication", "backend-unit", "frontend-unit"]),
    ("frontend/**", ["frontend-lint", "frontend-unit", "frontend-e2e"]),
    ("qa/**", ["framework", "policy", "authentication", "security", "reliability", "financial"]),
    (".github/workflows/**", ["framework", "policy"]),
]


def select_suites(changed_files: list[str]) -> dict[str, list[str]]:
    """suite -> the changed files that triggered it. Unknown paths trigger nothing extra."""
    picked: dict[str, list[str]] = defaultdict(list)
    for path in changed_files:
        for pattern, suites in SUITE_RULES:
            if fnmatch.fnmatch(path, pattern):
                for s in suites:
                    picked[s].append(path)
    return dict(picked)


# ------------------------------------------------------ Defect analysis --
_VOLATILE = [
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "<uuid>"),
    (re.compile(r"0x[0-9a-f]+"), "<addr>"),
    (re.compile(r"\d+(\.\d+)?"), "<n>"),
    (re.compile(r"'[^']{20,}'"), "'<str>'"),
]


def failure_signature(r: TestResult) -> str:
    last_detail = r.details.strip().splitlines()[-1] if r.details.strip() else ""
    text = (r.message or last_detail or "no message").split("\n")[0]
    for pattern, repl in _VOLATILE:
        text = pattern.sub(repl, text)
    return text[:200]


@dataclass
class DefectCandidate:
    id: str
    title: str
    severity: str
    confidence: str
    category: str  # product | qa-framework | environment
    tests: list[str]
    requirements: list[str]
    signature: str
    evidence: str
    suspected_cause: str
    ai_notes: list[str] = field(default_factory=list)


_ENV_HINTS = ("connection refused", "timed out", "could not connect", "no space left", "name or service not known")
_FRAMEWORK_HINTS = (
    "fixture",
    "contractviolationerror",
    "importerror",
    "modulenotfounderror",
    "attributeerror: 'apiclient'",
)


def classify(r: TestResult) -> tuple[str, str, str]:
    """(category, confidence, suspected cause) from the failure text alone."""
    text = f"{r.message}\n{r.details}".lower()
    if any(h in text for h in _ENV_HINTS) and "assert" not in r.message.lower():
        return (
            "environment",
            "medium",
            "A dependency or the runner was unavailable; re-run before treating as a product defect.",
        )
    if "contractviolationerror" in text:
        return "product", "high", "The API answered with a status or body the contract does not document."
    if any(h in text for h in _FRAMEWORK_HINTS):
        return (
            "qa-framework",
            "medium",
            "The failure is inside the QA harness, not an assertion about product behaviour.",
        )
    if "assert" in text:
        return (
            "product",
            "high",
            "A product behaviour assertion failed; see the test docstring for the expected behaviour.",
        )
    return "product", "low", "Unclassified failure; needs manual triage."


def group_failures(results: list[TestResult]) -> list[DefectCandidate]:
    groups: dict[tuple[str, str], list[TestResult]] = defaultdict(list)
    for r in results:
        if r.is_failure:
            groups[(r.suite, failure_signature(r))].append(r)
    out: list[DefectCandidate] = []
    for (suite, sig), members in groups.items():
        sev = min((m.severity for m in members), key=lambda s: SEVERITY_ORDER.get(s, 9))
        category, confidence, cause = classify(members[0])
        did = "QA-" + hashlib.sha1(f"{suite}|{sig}".encode()).hexdigest()[:8].upper()
        title = members[0].nodeid.split("::")[-1].replace("test_", "").replace("_", " ")
        out.append(
            DefectCandidate(
                id=did,
                title=f"{suite}: {title}",
                severity=sev,
                confidence=confidence,
                category=category,
                tests=[m.nodeid for m in members],
                requirements=sorted({q for m in members for q in m.requirements}),
                signature=sig,
                evidence=redact((members[0].message + "\n" + members[0].details)[-1500:]),
                suspected_cause=cause,
            )
        )
    out.sort(key=lambda d: (SEVERITY_ORDER.get(d.severity, 9), d.id))
    return out


# ------------------------------------------------------- Coverage gaps --
@dataclass
class Requirement:
    req_id: str
    area: str
    engine: str
    requirement: str
    priority: str
    status: str
    tests: str


def load_traceability(path: Path) -> list[Requirement]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return [
            Requirement(
                row["req_id"],
                row["area"],
                row["engine"],
                row["requirement"],
                row["priority"],
                row["status"],
                row.get("tests", ""),
            )
            for row in csv.DictReader(fh)
        ]


def coverage_gaps(reqs: list[Requirement], results: list[TestResult]) -> dict[str, list[Requirement]]:
    executed = defaultdict(list)
    for r in results:
        for q in r.requirements:
            executed[q].append(r)
    gaps: dict[str, list[Requirement]] = {"not_automated": [], "automated_but_not_run": [], "run_but_failing": []}
    for q in reqs:
        runs = executed.get(q.req_id, [])
        if q.status != "automated":
            gaps["not_automated"].append(q)
        elif not runs or all(x.outcome in ("skipped", "blocked") for x in runs):
            gaps["automated_but_not_run"].append(q)
        elif any(x.is_failure for x in runs):
            gaps["run_but_failing"].append(q)
    return gaps


# ------------------------------------------------------ Merge eligibility --
@dataclass
class Eligibility:
    verdict: str  # ELIGIBLE | NOT_ELIGIBLE
    reasons: list[str]
    warnings: list[str]


def merge_eligibility(
    results: list[TestResult],
    *,
    required_sources: list[str],
    tested_sha: str | None,
    expected_sha: str | None,
    job_outcomes: dict[str, str] | None = None,
) -> Eligibility:
    reasons: list[str] = []
    warnings: list[str] = []
    if not results:
        reasons.append("no test results were produced")
    if expected_sha and tested_sha and expected_sha != tested_sha:
        reasons.append(f"results are for {tested_sha[:12]}, latest commit is {expected_sha[:12]} (stale)")
    present = {r.source for r in results}
    for src in required_sources:
        if src not in present:
            reasons.append(f"mandatory result set '{src}' is missing")
    for job, outcome in (job_outcomes or {}).items():
        if outcome not in ("success", "skipped-not-applicable"):
            reasons.append(f"mandatory job '{job}' ended '{outcome}'")
    for r in results:
        if r.is_failure and r.severity in ("critical", "high"):
            reasons.append(f"{r.severity} failure: {r.nodeid}")
        elif r.is_failure:
            warnings.append(f"{r.severity} failure: {r.nodeid}")
        if "critical_gate" in r.tags and r.outcome in ("skipped", "blocked"):
            reasons.append(f"critical gate not executed: {r.nodeid}")
    return Eligibility("NOT_ELIGIBLE" if reasons else "ELIGIBLE", reasons, warnings)
