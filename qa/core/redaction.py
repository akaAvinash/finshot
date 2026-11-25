"""Redaction for evidence, logs and anything sent to an AI provider.

Applied before any text leaves the test process (artifacts, reports, LLM
prompts). Conservative: it is better to hide a harmless value than leak one.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(__Host-tradeo_(?:session|csrf)=)[^;\s,]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(x-csrf-token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\"(?:csrfToken|secret|code|recoveryCode|password|token)\"\s*:\s*\")[^\"]*"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret=)[A-Z2-7]+"), r"\1[REDACTED]"),
    # Whole credential for any scheme (Basic, Bearer, ...), quoted JSON or header form.
    (re.compile(r"(?i)([\"']?\bauthorization[\"']?\s*[:=]\s*[\"']?)[^\"'\r\n,}]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(sk-(?:ant-)?[A-Za-z0-9_\-]{10,})"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(redis://[^:/\s]*:)[^@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"\+91[6-9]\d{9}\b"), "+91[PHONE]"),
    (re.compile(r"\b[A-Z2-7]{5}-[A-Z2-7]{5}\b"), "[RECOVERY_CODE]"),
    (re.compile(r"\b[A-Z2-7]{32}\b"), "[TOTP_SECRET]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
