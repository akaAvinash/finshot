"""Schema checks: migrations match the models, roll back cleanly, and purge works."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.maintenance import purge_expired
from app.db.base import Base
from tests.support import Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
AUTH_TABLES = {"users", "otp_challenges", "sessions", "audit_events"}


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


def _tables(url: str) -> set[str]:
    rows = db_rows(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {r["tablename"] for r in rows}


def test_migrations_match_the_models(db_url: str) -> None:
    """Autogenerate finds nothing to change: the models and migration 0002 agree."""

    async def diff() -> list[object]:
        import app.auth.models  # noqa: F401

        engine = create_async_engine(db_url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync: compare_metadata(
                        MigrationContext.configure(sync, opts={"compare_type": True}),
                        Base.metadata,
                    )
                )
        finally:
            await engine.dispose()

    assert asyncio.run(diff()) == []


def test_auth_migration_rolls_back_and_forward(db_url: str) -> None:
    cfg = _config(db_url)
    command.upgrade(cfg, "head")
    assert AUTH_TABLES <= _tables(db_url)
    command.downgrade(cfg, "0001")
    assert not (AUTH_TABLES & _tables(db_url))
    command.upgrade(cfg, "head")
    assert AUTH_TABLES <= _tables(db_url)


def test_database_constraints_reject_bad_rows(db_url: str, browser: Browser) -> None:
    browser.login()
    from sqlalchemy.exc import DBAPIError

    for sql in (
        "INSERT INTO users (phone_e164, created_at, updated_at) VALUES ('+14155550100', now(), now())",
        "INSERT INTO users (phone_e164, status, created_at, updated_at) VALUES ('+919000000001', 'weird', now(), now())",
        "INSERT INTO users (phone_e164, created_at, updated_at) VALUES ('+919876543210', now(), now())",
        "UPDATE otp_challenges SET attempts = -1",
    ):
        with pytest.raises(DBAPIError):
            db_rows(db_url, sql)


def test_deleting_a_user_cascades_sessions_but_keeps_audit_history(
    db_url: str, browser: Browser
) -> None:
    browser.login()
    db_rows(db_url, "DELETE FROM users")
    assert db_rows(db_url, "SELECT 1 FROM sessions") == []
    audit = db_rows(db_url, "SELECT user_id FROM audit_events WHERE action = 'login_succeeded'")
    assert audit and audit[0]["user_id"] is None


def test_purge_removes_expired_otp_digests_and_dead_sessions(
    db_url: str, browser: Browser, clock: FakeClock
) -> None:
    browser.login()
    browser.get_csrf()
    browser.request_otp("+919123456780")  # a second, unused challenge
    browser.post("/api/v1/auth/logout")
    clock.advance(2 * 3600)

    async def run() -> dict[str, int]:
        engine = create_async_engine(db_url)
        try:
            async with engine.connect() as conn:
                from sqlalchemy.ext.asyncio import AsyncSession

                async with AsyncSession(bind=conn) as db:
                    return await purge_expired(db, now=clock.now)
        finally:
            await engine.dispose()

    result = asyncio.run(run())
    assert result == {"otp_challenges": 2, "sessions": 1}
    assert db_rows(db_url, "SELECT 1 FROM otp_challenges") == []
    # Audit history is retained.
    assert db_rows(db_url, "SELECT count(*) AS n FROM audit_events")[0]["n"] >= 3


def test_purge_removes_idle_expired_sessions_that_were_never_revoked(
    db_url: str, browser: Browser, clock: FakeClock
) -> None:
    browser.login()
    clock.advance(3 * 3600)  # idle for 3 hours (30 min idle TTL), still inside the 12 h cap

    async def run() -> dict[str, int]:
        engine = create_async_engine(db_url)
        try:
            from sqlalchemy.ext.asyncio import AsyncSession

            async with AsyncSession(bind=engine) as db:
                return await purge_expired(db, now=clock.now, idle_ttl=timedelta(minutes=30))
        finally:
            await engine.dispose()

    assert asyncio.run(run())["sessions"] == 1
    assert db_rows(db_url, "SELECT 1 FROM sessions") == []


def test_requesting_a_code_purges_that_phones_old_challenges(
    db_url: str, browser: Browser, clock: FakeClock
) -> None:
    browser.get_csrf()
    browser.request_otp()
    clock.advance(timedelta(hours=2).total_seconds())
    browser.get_csrf()  # pre-login token expired (30 min); fetch a fresh one
    browser.request_otp()
    assert len(db_rows(db_url, "SELECT 1 FROM otp_challenges")) == 1


def test_timestamps_are_utc(db_url: str, browser: Browser) -> None:
    browser.login()
    rows = db_rows(db_url, "SELECT created_at FROM users")
    assert rows[0]["created_at"].utcoffset() == timedelta(0)
