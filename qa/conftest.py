"""Root fixtures for the independent QA suite.

Lifecycle: one disposable database (schema dropped and migrated once per run),
one SMTP sink, one backend process with default production-like limits. Redis
is flushed before each test so rate-limit counters from one test cannot leak
into another. Tests that need other settings start their own backend with
`backend_factory`.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from qa.config.settings import QaSettings, load
from qa.core.actors import Person
from qa.core.client import ApiClient
from qa.core.mail import SmtpSink
from qa.core.redaction import redact
from qa.core.sut import Backend, flush_redis, reset_database

# ---------------------------------------------------------------- metadata --
SEVERITIES = ("critical", "high", "medium", "low")


def pytest_configure(config: pytest.Config) -> None:
    config._qa_started = time.time()  # type: ignore[attr-defined]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Copy traceability markers into JUnit properties so reports can use them."""
    for item in items:
        for mark in item.iter_markers("req"):
            for req in mark.args:
                item.user_properties.append(("requirement", req))
        sev = item.get_closest_marker("severity")
        item.user_properties.append(("severity", sev.args[0] if sev else "medium"))
        for name in ("needs_services", "slow", "critical_gate"):
            if item.get_closest_marker(name):
                item.user_properties.append(("tag", name))
        for mark in item.iter_markers("suite"):
            item.user_properties.append(("suite", mark.args[0]))


# ---------------------------------------------------------------- services --
@pytest.fixture(scope="session")
def qa_settings() -> QaSettings:
    return load()


@pytest.fixture(scope="session")
def artifacts_dir(qa_settings: QaSettings) -> Path:
    path = qa_settings.artifacts_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def services(qa_settings: QaSettings) -> QaSettings:
    if not qa_settings.services_configured:
        if os.environ.get("QA_REQUIRE_SERVICES") == "1":
            pytest.fail("QA_DATABASE_URL/QA_REDIS_URL unset but QA_REQUIRE_SERVICES=1")
        pytest.skip("QA_DATABASE_URL/QA_REDIS_URL unset (blocked: no disposable services)")
    reset_database(qa_settings)
    return qa_settings


@pytest.fixture(scope="session")
def smtp_sink() -> Iterator[SmtpSink]:
    sink = SmtpSink()
    sink.start()
    yield sink
    sink.stop()


@pytest.fixture(scope="session")
def backend_factory(services: QaSettings, smtp_sink: SmtpSink, artifacts_dir: Path) -> Iterator[Callable[..., Backend]]:
    started: list[Backend] = []
    migrated = False

    def make(name: str = "backend", **env: str) -> Backend:
        nonlocal migrated
        b = Backend(
            settings=services,
            env_overrides={k.upper(): str(v) for k, v in env.items()},
            smtp_port=smtp_sink.port,
            smtp_username=smtp_sink.username,
            smtp_password=smtp_sink.password,
            log_path=artifacts_dir / "logs" / f"{name}-{len(started)}.log",
        )
        if not migrated:
            b.migrate()
            migrated = True
        b.start()
        started.append(b)
        return b

    yield make
    for b in started:
        b.stop()


@pytest.fixture(scope="session")
def backend(backend_factory: Callable[..., Backend]) -> Backend:
    # Resend cooldown 0 keeps the default suite fast; the cooldown has its own test.
    return backend_factory("default", OTP_RESEND_COOLDOWN_SECONDS="0")


@pytest.fixture(autouse=True)
def _clean_redis(request: pytest.FixtureRequest, qa_settings: QaSettings) -> None:
    if request.node.get_closest_marker("needs_services") and qa_settings.services_configured:
        flush_redis(qa_settings)


@pytest.fixture
def sink(smtp_sink: SmtpSink) -> Iterator[SmtpSink]:
    smtp_sink.clear()
    yield smtp_sink
    smtp_sink.clear()


@pytest.fixture
def people(backend: Backend, sink: SmtpSink, request: pytest.FixtureRequest) -> Iterator[Callable[[], Person]]:
    made: list[Person] = []

    def make() -> Person:
        p = Person(backend, sink)
        made.append(p)
        return p

    request.node._qa_people = made  # type: ignore[attr-defined]
    yield make
    for p in made:
        for c in p.clients:
            c.close()


@pytest.fixture
def anon(backend: Backend, request: pytest.FixtureRequest) -> Iterator[ApiClient]:
    c = ApiClient(backend.base_url, name="anonymous")
    request.node._qa_anon = c  # type: ignore[attr-defined]
    yield c
    c.close()


# ---------------------------------------------------------------- evidence --
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    parts: list[str] = []
    for p in getattr(item, "_qa_people", []):
        for c in p.clients:
            parts.append(c.evidence())
    anon = getattr(item, "_qa_anon", None)
    if anon is not None:
        parts.append(anon.evidence())
    if parts:
        text = redact("\n\n".join(parts))
        report.sections.append(("qa evidence (redacted)", text))
        art = load().artifacts_dir / "evidence"
        art.mkdir(parents=True, exist_ok=True)
        safe = item.nodeid.replace("/", "_").replace("::", "__")[:180]
        (art / f"{safe}.txt").write_text(text)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    started = getattr(session.config, "_qa_started", time.time())
    out = load().artifacts_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "session.json").write_text(
        json.dumps({"started": started, "finished": time.time(), "exitstatus": int(exitstatus)})
    )
