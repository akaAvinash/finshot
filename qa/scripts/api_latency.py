"""Opt-in API timing and coverage for the existing HTTP test scenarios."""

from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from qa.core.contract import load_contract


def latency(samples: list[float]) -> dict[str, float | None]:
    """Nearest-rank percentiles in milliseconds."""
    ordered = sorted(samples)
    return {
        f"p{p}_ms": round(ordered[math.ceil(len(ordered) * p / 100) - 1], 2) if ordered else None for p in (50, 95, 99)
    }


class ApiLatency:
    def __init__(self, destination: Path, require_success: bool) -> None:
        self.destination = destination
        self.require_success = require_success
        self.contract = load_contract()
        self.operations = self.contract.operation_ids()
        self.samples: dict[str, list[tuple[float, int]]] = defaultdict(list)
        self.patch = pytest.MonkeyPatch()
        self._instrument_httpx()

    def _observe(self, request: httpx.Request, started: float, status: int) -> None:
        if request.url.host not in {"testserver", "localhost", "127.0.0.1", "::1"}:
            return
        operation = self.contract.operation(request.method, request.url.path)
        if operation is not None:
            self.samples[operation[1]["operationId"]].append(((time.perf_counter() - started) * 1000, status))

    def _instrument_httpx(self) -> None:
        send: Callable[..., httpx.Response] = httpx.Client.send
        async_send = httpx.AsyncClient.send

        def timed(client: httpx.Client, request: httpx.Request, *args: Any, **kwargs: Any) -> httpx.Response:
            status = 0
            start = time.perf_counter()
            try:
                response = send(client, request, *args, **kwargs)
                status = response.status_code
                return response
            finally:
                self._observe(request, start, status)

        async def timed_async(
            client: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any
        ) -> httpx.Response:
            status = 0
            start = time.perf_counter()
            try:
                response = await async_send(client, request, *args, **kwargs)
                status = response.status_code
                return response
            finally:
                self._observe(request, start, status)

        self.patch.setattr(httpx.Client, "send", timed)
        self.patch.setattr(httpx.AsyncClient, "send", timed_async)

    def pytest_unconfigure(self) -> None:
        self.patch.undo()

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        results = {}
        for operation, (method, path) in self.operations.items():
            samples = self.samples[operation]
            success = [ms for ms, status in samples if 200 <= status < 300]
            results[operation] = {
                "method": method,
                "path": path,
                "samples": len(samples),
                "successful": len(success),
                "status_counts": dict(Counter(str(status) for _, status in samples)),
                **latency(success),
            }
        missing = sorted(operation for operation, result in results.items() if not result["successful"])
        if self.require_success and missing and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        report = {
            "test_exit_code": int(session.exitstatus),
            "operations": results,
            "operations_without_success": missing,
            "sample_scope": "Existing API test scenarios, including in-process ASGI requests",
        }
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line(f"API latency: {len(results) - len(missing)}/{len(results)} operations returned 2xx")
            if missing:
                reporter.write_line("Operations without a 2xx sample: " + ", ".join(missing))


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("api-latency")
    group.addoption("--api-latency-report", type=Path, help="Write redacted per-operation API latency JSON.")
    group.addoption("--api-latency-require-success", action="store_true", help="Require a 2xx for every API operation.")


def pytest_configure(config: pytest.Config) -> None:
    destination = config.getoption("--api-latency-report")
    required = config.getoption("--api-latency-require-success")
    if required and destination is None:
        raise pytest.UsageError("--api-latency-require-success requires --api-latency-report")
    if destination is not None:
        config.pluginmanager.register(ApiLatency(destination, required), "api-latency-recording")
