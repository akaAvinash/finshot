"""Guardrails on the QA framework: independence from product code and safe defaults."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.suite("policy"), pytest.mark.severity("high")]

QA_DIR = Path(__file__).resolve().parents[2]
PY_FILES = [p for p in QA_DIR.rglob("*.py") if "artifacts" not in p.parts and p.name != Path(__file__).name]


@pytest.mark.req("QA-POL-001")
def test_qa_code_never_imports_product_code():
    """Expected values must not come from the implementation under test."""
    offenders = [
        str(p.relative_to(QA_DIR))
        for p in PY_FILES
        if re.search(r"^\s*(from|import)\s+app(\.|\s|$)", p.read_text(), re.M)
    ]
    assert offenders == []


@pytest.mark.req("QA-POL-002")
def test_no_real_endpoints_or_credentials_in_qa_code():
    pattern = re.compile(
        r"(api\.kite\.trade|api\.anthropic\.com/v1/messages\b.*key=|smtp\.gmail\.com|"
        r"homelab\.|\.ts\.net|sk-ant-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{30})"
    )
    offenders = [str(p.relative_to(QA_DIR)) for p in PY_FILES if pattern.search(p.read_text())]
    assert offenders == []


@pytest.mark.req("QA-POL-003")
def test_synthetic_contact_data_only():
    """Emails in the framework use the reserved .invalid TLD."""
    emails = set()
    for p in PY_FILES:
        emails |= set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", p.read_text()))
    real = {e for e in emails if not e.endswith(".invalid") and "example" not in e}
    assert real == set()


@pytest.mark.req("QA-POL-004")
def test_ai_agent_has_no_merge_or_write_capability():
    """The AI QA agent may read results and write reports. It must not call GitHub write APIs."""
    agent_src = "\n".join(p.read_text() for p in (QA_DIR / "ai_agent").rglob("*.py"))
    for forbidden in ("/merge", "pulls/{", "subprocess", "os.system", "eval(", "exec("):
        assert forbidden not in agent_src, forbidden


@pytest.mark.req("QA-POL-005")
def test_traceability_and_catalog_are_current():
    """docs/qa CSVs are generated from test markers; a stale or inconsistent file fails."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(QA_DIR / "scripts" / "build_catalog.py"), "--check"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
