"""Run against real PostgreSQL and Redis.

    TEST_DATABASE_URL=postgresql+asyncpg://... TEST_REDIS_URL=redis://... pytest -m integration

Skipped when those variables are unset. Point TEST_DATABASE_URL at a throwaway
database: the migration test upgrades and downgrades it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import create_app
from tests.conftest import SettingsFactory

DB_URL = os.environ.get("TEST_DATABASE_URL")
REDIS_URL = os.environ.get("TEST_REDIS_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (DB_URL and REDIS_URL), reason="TEST_DATABASE_URL/TEST_REDIS_URL unset"),
]

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_ready_with_real_dependencies(make_settings: SettingsFactory) -> None:
    with TestClient(create_app(make_settings(database_url=DB_URL, redis_url=REDIS_URL))) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = DB_URL
    return cfg


async def _current_revision() -> str | None:
    assert DB_URL is not None
    engine = create_async_engine(DB_URL)
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(text("SELECT to_regclass('alembic_version') IS NOT NULL"))
            if not exists:
                return None
            return await conn.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()


def test_migrations_upgrade_and_downgrade() -> None:
    cfg = _alembic_config()
    head = ScriptDirectory.from_config(cfg).get_current_head()

    command.upgrade(cfg, "head")
    assert asyncio.run(_current_revision()) == head

    command.downgrade(cfg, "base")
    assert asyncio.run(_current_revision()) is None

    command.upgrade(cfg, "head")
    assert asyncio.run(_current_revision()) == head


def test_migrations_have_a_single_head() -> None:
    assert len(ScriptDirectory.from_config(_alembic_config()).get_heads()) == 1
