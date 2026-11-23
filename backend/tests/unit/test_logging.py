from __future__ import annotations

import json

import pytest
import structlog

from app.core.logging import configure_logging
from tests.conftest import SettingsFactory


def test_sensitive_keys_are_redacted(
    make_settings: SettingsFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings())
    structlog.get_logger("t").info("evt", password="hunter2", token="abc", symbol="NIFTY")
    entry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert entry["password"] == "[REDACTED]"
    assert entry["token"] == "[REDACTED]"
    assert entry["symbol"] == "NIFTY"


def test_stdlib_loggers_are_json(
    make_settings: SettingsFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    import logging

    configure_logging(make_settings())
    logging.getLogger("uvicorn.error").warning("from uvicorn")
    entry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert entry["event"] == "from uvicorn"
    assert entry["logger"] == "uvicorn.error"
