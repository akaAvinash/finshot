"""Operator commands for invite-only access. There is no admin role in the API;
these run on the server, against the configured database.

    python -m app.auth.admin invite add +919876543210 [--email you@example.com]
    python -m app.auth.admin invite revoke +919876543210
    python -m app.auth.admin invite list
    python -m app.auth.admin totp-reset +919876543210
    python -m app.auth.admin user-id +919876543210   (for MARKET_STREAM_OWNER_USER_ID)
    python -m app.auth.admin staging-otp +919876543210
    python -m app.auth.admin tester issue +919000000001   (prints the code once)
    python -m app.auth.admin tester revoke +919000000001
    python -m app.auth.admin tester purge +919000000001
    python -m app.auth.admin tester list

Phone numbers are masked in output. Nothing here prints a secret."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import (
    AuditEvent,
    Invite,
    RecoveryCode,
    TesterIdentity,
    TotpCredential,
    User,
)
from app.auth.models import Session as SessionRow
from app.auth.otp import mask_destination, read_staging_codes
from app.core.config import Settings

_PHONE = re.compile(r"^\+91[6-9][0-9]{9}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AdminError(Exception):
    """A usage error to show to the operator."""


def validate_phone(phone: str) -> str:
    if not _PHONE.fullmatch(phone):
        raise AdminError("phone must be an Indian mobile number in E.164 form (+91...)")
    return phone


async def add_invite(db: AsyncSession, phone: str, email: str | None, now: datetime) -> None:
    validate_phone(phone)
    if await db.scalar(
        select(TesterIdentity.user_id)
        .join(User, User.id == TesterIdentity.user_id)
        .where(User.phone_e164 == phone)
    ):
        raise AdminError("that number is a tester identity and cannot be a regular account")
    if email is not None and not _EMAIL.fullmatch(email):
        raise AdminError("email is not a valid address")
    stmt = insert(Invite).values(phone_e164=phone, email=email, created_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Invite.phone_e164],
        set_={"revoked_at": None, "email": email if email is not None else Invite.email},
    )
    await db.execute(stmt)
    await db.commit()


async def revoke_invite(db: AsyncSession, phone: str, now: datetime) -> bool:
    """Revoke the invite and end every live session of that number's user."""
    validate_phone(phone)
    result = await db.execute(
        update(Invite)
        .where(Invite.phone_e164 == phone, Invite.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    user_id = await db.scalar(select(User.id).where(User.phone_e164 == phone))
    if user_id is not None:
        await db.execute(
            update(SessionRow)
            .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.add(
            AuditEvent(
                user_id=user_id,
                actor="operator",
                action="invite.revoked",
                resource=None,
                metadata_redacted={},
                created_at=now,
            )
        )
    await db.commit()
    return bool(getattr(result, "rowcount", 0))


async def list_invites(db: AsyncSession) -> list[tuple[str, str, bool]]:
    rows = await db.execute(select(Invite).order_by(Invite.created_at))
    return [
        (
            mask_destination(r.phone_e164),
            (r.email and mask_destination(r.email)) or "-",
            bool(r.revoked_at),
        )
        for r in rows.scalars()
    ]


async def reset_totp(db: AsyncSession, phone: str, now: datetime) -> bool:
    """Lost authenticator: remove the credential and close every step-up window."""
    validate_phone(phone)
    user_id = await db.scalar(select(User.id).where(User.phone_e164 == phone))
    if user_id is None:
        return False
    deleted = await db.execute(delete(TotpCredential).where(TotpCredential.user_id == user_id))
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    await db.execute(
        update(SessionRow).where(SessionRow.user_id == user_id).values(step_up_until=None)
    )
    db.add(
        AuditEvent(
            user_id=user_id,
            actor="operator",
            action="auth.totp_reset",
            resource=None,
            metadata_redacted={},
            created_at=now,
        )
    )
    await db.commit()
    return bool(getattr(deleted, "rowcount", 0))


async def user_id(db: AsyncSession, phone: str) -> str | None:
    """The account id for a number (not a secret; used to name the market
    stream owner in MARKET_STREAM_OWNER_USER_ID)."""
    found = await db.scalar(select(User.id).where(User.phone_e164 == validate_phone(phone)))
    return str(found) if found is not None else None


def staging_code(path: str, phone: str) -> str | None:
    """The current unexpired staging code for a number, or None."""
    entry = read_staging_codes(Path(path), now=time.time()).get(validate_phone(phone))
    return str(entry["code"]) if entry else None


async def _run(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.db.session import create_engine, create_session_factory

    settings = get_settings()
    if args.command == "staging-otp":
        if not settings.otp_staging_file:
            print("OTP_STAGING_FILE is not set", file=sys.stderr)
            return 1
        code = staging_code(settings.otp_staging_file, args.phone)
        print(
            code if code else "no unexpired code for that number",
            file=sys.stderr if not code else sys.stdout,
        )
        return 0 if code else 1

    engine = create_engine(settings)
    now = datetime.now(UTC)
    try:
        async with create_session_factory(engine)() as db:
            if args.command == "invite" and args.action == "add":
                await add_invite(db, args.phone, args.email, now)
                print(f"invited {mask_destination(args.phone)}")
            elif args.command == "invite" and args.action == "revoke":
                done = await revoke_invite(db, args.phone, now)
                print("revoked" if done else "no active invite for that number")
            elif args.command == "invite":
                for phone, email, revoked in await list_invites(db):
                    print(phone, email, "revoked" if revoked else "active")
            elif args.command == "tester":
                await _run_tester(args, db, settings, now)
            elif args.command == "user-id":
                found = await user_id(db, args.phone)
                print(found or "no account with that number")
            elif args.command == "totp-reset":
                done = await reset_totp(db, args.phone, now)
                print("authenticator removed" if done else "nothing to reset")
    finally:
        await engine.dispose()
    return 0


async def _run_tester(
    args: argparse.Namespace, db: AsyncSession, settings: Settings, now: datetime
) -> None:
    from app.auth import tester
    from app.auth.crypto import Keys

    try:
        if args.action == "issue":
            ttl = timedelta(seconds=settings.tester_invite_ttl_seconds)
            code = await tester.issue_invite(
                db,
                Keys.from_secret(settings.auth_secret_key.get_secret_value()),
                args.phone,
                ttl,
                now,
            )
            minutes = int(ttl.total_seconds() // 60)
            print(f"tester {mask_destination(args.phone)}: code (shown once, {minutes} min):")
            print(code)
        elif args.action == "revoke":
            done = await tester.revoke_access(db, args.phone, now)
            print("access revoked" if done else "no tester with that number")
        elif args.action == "purge":
            done = await tester.purge_credentials(db, args.phone, now)
            print("credentials purged" if done else "no tester with that number")
        else:
            for phone, purged, live in await tester.list_testers(db):
                print(phone, "purged" if purged else "active", f"live-invites={live}")
    except tester.TesterError as exc:
        raise AdminError(str(exc)) from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.auth.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite")
    actions = invite.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("phone")
    add.add_argument("--email")
    actions.add_parser("revoke").add_argument("phone")
    actions.add_parser("list")
    tester_cmd = sub.add_parser("tester")
    tester_actions = tester_cmd.add_subparsers(dest="action", required=True)
    for name in ("issue", "revoke", "purge"):
        tester_actions.add_parser(name).add_argument("phone")
    tester_actions.add_parser("list")
    sub.add_parser("totp-reset").add_argument("phone")
    sub.add_parser("staging-otp").add_argument("phone")
    sub.add_parser("user-id").add_argument("phone")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
