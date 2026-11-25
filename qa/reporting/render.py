"""Markdown rendering for the QA report (GitHub step summary, nightly morning report)."""

from __future__ import annotations

from typing import Any


def _short(sha: str | None) -> str:
    return sha[:12] if sha else "n/a"


def render_markdown(r: dict[str, Any], title: str) -> str:
    t = r["totals"]
    gate = r["merge_eligibility"]
    lines = [
        f"# {title}",
        "",
        f"**Merge eligibility: {gate['verdict']}**",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Repository | {r['repository']} |",
        f"| Branch | {r.get('branch') or 'n/a'} |",
        f"| PR | {('#' + str(r['pr_number'])) if r.get('pr_number') else 'n/a'} |",
        f"| Base commit | {_short(r.get('base_sha'))} |",
        f"| Head commit | {_short(r.get('head_sha'))} |",
        f"| Tested commit | {_short(r.get('tested_sha'))} |",
        f"| Environment | {r.get('environment')} |",
        f"| Started / finished (UTC) | {r.get('started_at') or 'n/a'} / {r['finished_at']} |",
        f"| Run | {r.get('run_url') or 'local'} |",
        "",
        "| Total | Passed | Failed | Skipped | Blocked | Flaky candidates |",
        "|---|---|---|---|---|---|",
        f"| {t['total']} | {t['passed']} | {t['failed']} | {t['skipped']} | {t['blocked']} | {len(r['flaky_candidates'])} |",
        "",
        "## Results by suite",
        "",
        "| Suite | Passed | Failed | Error | Skipped | Blocked |",
        "|---|---|---|---|---|---|",
    ]
    for s, c in r["by_source"].items():
        lines.append(f"| {s} | {c['passed']} | {c['failed']} | {c['error']} | {c['skipped']} | {c['blocked']} |")
    lines += ["", "## Gate reasons", ""]
    lines += [f"- {x}" for x in gate["reasons"]] or ["- none"]
    if gate["warnings"]:
        lines += ["", "Warnings (do not block on their own):", *[f"- {x}" for x in gate["warnings"]]]
    sev = r["defects_by_severity"]
    lines += [
        "",
        "## Defect candidates",
        "",
        f"Critical {sev['critical']} · High {sev['high']} · Medium {sev['medium']} · Low {sev['low']}",
        "",
    ]
    if r["defects"]:
        lines += ["| ID | Severity | Category | Confidence | Title | Tests |", "|---|---|---|---|---|---|"]
        for d in r["defects"]:
            lines.append(
                f"| {d['id']} | {d['severity']} | {d['category']} | {d['confidence']} | {d['title']} | {len(d['tests'])} |"
            )
    else:
        lines.append("None.")
    if r["flaky_candidates"]:
        lines += [
            "",
            "## Flaky candidates (original failure still counts)",
            "",
            *[f"- {x}" for x in r["flaky_candidates"]],
        ]
    gaps = r["coverage_gaps"]
    lines += [
        "",
        "## Coverage gaps",
        "",
        f"- Requirements not automated yet: {len(gaps['not_automated'])}",
        f"- Automated but not executed in this run: {len(gaps['automated_but_not_run'])}",
        f"- Executed and failing: {len(gaps['run_but_failing'])}",
    ]
    by_engine: dict[str, int] = {}
    for q in gaps["not_automated"]:
        by_engine[q["engine"]] = by_engine.get(q["engine"], 0) + 1
    if by_engine:
        lines += ["", "| Engine / area | Requirements without automation |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(by_engine.items())]
    lines += ["", "## AI analysis", "", f"- {r['ai']['status']}", *[f"- {x}" for x in r["ai"]["limitations"]]]
    return "\n".join(lines) + "\n"


def _repro(nodeid: str) -> str:
    """JUnit 'qa.tests.x.test_mod::test_name' -> a pytest command line."""
    cls, _, name = nodeid.partition("::")
    if cls.startswith("qa."):
        return f"python -m pytest -c qa/pytest.ini '{cls.replace('.', '/')}.py::{name}'"
    return f"(re-run the suite that produced: {nodeid})"


def render_defects(r: dict[str, Any]) -> str:
    if not r["defects"]:
        return "# Defect candidates\n\nNone in this run.\n"
    out = ["# Defect candidates", ""]
    for d in r["defects"]:
        out += [
            f"## {d['id']}: {d['title']}",
            "",
            f"- Severity: {d['severity']} (from the test's declared impact)",
            f"- Category: {d['category']} · Confidence: {d['confidence']}",
            f"- Tested commit: {(r.get('tested_sha') or 'n/a')[:12]}",
            f"- Requirements: {', '.join(d['requirements']) or 'n/a'}",
            f"- Suspected cause (rule-based): {d['suspected_cause']}",
            "- Tests:",
            *[f"  - `{t}`" for t in d["tests"]],
            "",
            "Reproduce:",
            "",
            "```",
            _repro(d["tests"][0]),
            "```",
            "",
            "Evidence (redacted):",
            "",
            "```",
            d["evidence"],
            "```",
            "",
        ]
        for note in d["ai_notes"]:
            out += [f"> {note}", ""]
    return "\n".join(out)
