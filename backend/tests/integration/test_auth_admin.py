"""Invite migration backfill and the operator commands (real Postgres)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import admin
from tests.support import OTHER_PHONE, PHONE, Browser, db_rows

BACKEND_DIR = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 25, tzinfo=UTC)


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


def test_migration_invites_every_existing_user(db_url: str) -> None:
    cfg = _cfg(db_url)
    command.downgrade(cfg, "0009")
    db_rows(
        db_url,
        "INSERT INTO users (id, phone_e164, status, created_at, updated_at)"
        " VALUES (gen_random_uuid(), :p, 'active', now(), now())",
        p=PHONE,
    )
    command.upgrade(cfg, "head")
    rows = db_rows(db_url, "SELECT phone_e164, revoked_at FROM invites")
    assert rows == [{"phone_e164": PHONE, "revoked_at": None}]


def _run(db_url: str, fn):  # type: ignore[no-untyped-def]
    async def go():  # type: ignore[no-untyped-def]
        engine = create_async_engine(db_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await fn(db)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_invite_add_is_idempotent_and_reinstates(db_url: str) -> None:
    _run(db_url, lambda db: admin.add_invite(db, PHONE, None, NOW))
    _run(db_url, lambda db: admin.revoke_invite(db, PHONE, NOW))
    assert db_rows(db_url, "SELECT revoked_at FROM invites")[0]["revoked_at"] is not None
    _run(db_url, lambda db: admin.add_invite(db, PHONE, "a@example.com", NOW))
    row = db_rows(db_url, "SELECT revoked_at, email FROM invites")[0]
    assert row == {"revoked_at": None, "email": "a@example.com"}


def test_invalid_input_is_refused(db_url: str) -> None:
    with pytest.raises(admin.AdminError):
        _run(db_url, lambda db: admin.add_invite(db, "123", None, NOW))
    with pytest.raises(admin.AdminError):
        _run(db_url, lambda db: admin.add_invite(db, PHONE, "not-an-email", NOW))


def test_listing_masks_numbers_and_emails(db_url: str) -> None:
    _run(db_url, lambda db: admin.add_invite(db, PHONE, "alice@example.com", NOW))
    (row,) = _run(db_url, admin.list_invites)
    assert row == ("+91******3210", "a***@example.com", False)


def test_revoking_ends_live_sessions_and_blocks_new_sign_in(browser: Browser, db_url: str) -> None:
    browser.login()
    assert browser.get("/api/v1/auth/me").status_code == 200
    assert _run(db_url, lambda db: admin.revoke_invite(db, PHONE, datetime.now(UTC)))
    assert browser.get("/api/v1/auth/me").status_code == 401
    browser.get_csrf()
    challenge = browser.request_otp(PHONE, invite=False)
    assert browser.verify(challenge.json()["challengeId"], "123456").status_code == 401


def test_totp_reset_removes_the_authenticator(browser: Browser, db_url: str) -> None:
    browser.login()
    browser.post("/api/v1/auth/totp/enroll")
    assert db_rows(db_url, "SELECT 1 FROM totp_credentials")
    assert _run(db_url, lambda db: admin.reset_totp(db, PHONE, NOW))
    assert not db_rows(db_url, "SELECT 1 FROM totp_credentials")
    assert db_rows(db_url, "SELECT 1 FROM audit_events WHERE action = 'auth.totp_reset'")
    assert not _run(db_url, lambda db: admin.reset_totp(db, OTHER_PHONE, NOW))


def test_user_id_names_the_account(browser: Browser, db_url: str) -> None:
    browser.login()
    (row,) = db_rows(db_url, "SELECT id FROM users WHERE phone_e164 = :p", p=PHONE)
    assert _run(db_url, lambda db: admin.user_id(db, PHONE)) == str(row["id"])
    assert _run(db_url, lambda db: admin.user_id(db, OTHER_PHONE)) is None
    with pytest.raises(admin.AdminError):
        _run(db_url, lambda db: admin.user_id(db, "123"))
