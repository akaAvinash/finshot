"""Scan tracked files for credentials and write a JUnit result (one case per rule).

High-signal patterns only; a match fails the check and prints the file and
line, never the matched value. Run from the repository root.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "anthropic-key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai-key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"),
    "slack-token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "kite-access-token": re.compile(r"(?i)kite[_-]?access[_-]?token\s*[:=]\s*['\"][A-Za-z0-9]{20,}"),
    "password-assignment": re.compile(
        r"(?i)\b(?:smtp|db|database|redis|postgres)_?password\s*[:=]\s*['\"](?!\$|<|ci-only|change-?me|example|test|s3cret|\{)[^'\"\s]{8,}['\"]"
    ),
    "url-with-password": re.compile(
        r"\b(?:postgres(?:ql)?(?:\+\w+)?|redis|amqp)://[^:/\s]+:(?!ci-only|change-?me@|pw@|password@|<|\$|\{)[^@\s]{8,}@"
    ),
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".zip", ".lock"}
SKIP_FILES = {"package-lock.json"}
# Files that hold detection patterns themselves (reviewed; they contain regexes, not credentials).
PATTERN_FILES = {"qa/core/redaction.py", "qa/scripts/secret_scan.py"}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    return [Path(p) for p in out.decode().split("\0") if p]


def scan() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {name: [] for name in RULES}
    for path in tracked_files():
        if (
            path.suffix in SKIP_SUFFIXES
            or path.name in SKIP_FILES
            or path.as_posix() in PATTERN_FILES
            or not path.is_file()
        ):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rule in RULES.items():
                if rule.search(line):
                    hits[name].append(f"{path}:{lineno}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", required=True)
    args = ap.parse_args()
    hits = scan()
    cases = []
    for name, where in hits.items():
        body = ""
        if where:
            body = f'<failure message="possible {name}">{escape(chr(10).join(where[:50]))}</failure>'
        cases.append(
            f'<testcase classname="secret_scan" name="{name}" time="0">'
            f'<properties><property name="severity" value="critical"/>'
            f'<property name="requirement" value="SEC-SECRET-001"/>'
            f'<property name="suite" value="security"/></properties>{body}</testcase>'
        )
    failures = sum(1 for w in hits.values() if w)
    Path(args.junit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.junit).write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="secret-scan" tests="{len(cases)}" '
        f'failures="{failures}">{"".join(cases)}</testsuite></testsuites>'
    )
    for name, where in hits.items():
        for w in where:
            print(f"possible {name}: {w}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
