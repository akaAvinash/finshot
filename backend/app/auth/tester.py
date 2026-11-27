"""Invite-only tester sign-in: invite codes, operator actions and the operation
allowlist (`x-tester-allowed-operations` in contracts/openapi.yaml).

A tester is a dedicated user on a synthetic phone number with no `invites`
row and no authenticator, so the regular OTP, authenticator and recovery
sign-in cannot reach it. The operator issues one short-lived, single-use code
(`python -m app.auth.admin tester issue +91...`); the tester redeems it at
`POST /api/v1/auth/login/tester` and gets a session bound to that invite,
limited to demo and paper trading. Codes are stored only as a keyed digest and
shown once. Audit events never carry codes, full phone numbers or tokens."""

from __future__ import annotations

import base64
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import Keys, hmac_hex
from app.auth.models import AuditEvent, Invite, TesterIdentity, TesterInvite, User
from app.auth.models import Session as SessionRow

# The only operations a tester session may call. Anything else, including any
# operation added later, is refused with 403 TESTER_ACCESS_DENIED. Mirrors
# `x-tester-allowed-operations` in the contract (a test compares them).
TESTER_ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "getCsrfToken",
        "getCurrentUser",
        "logout",
        "getMarketInstruments",
        "getMarketOverview",
        "getMarketCandles",
        "getBrokerConnections",
        "getBrokerPortfolio",
        "getStrategies",
        "sendStrategyCommand",
        "getBacktestWorkspace",
        "startBacktest",
        "getBacktestRun",
        "getPaperTrading",
        "sendPaperCommand",
        "getTradeControls",
        "getTradeControlsHistory",
        "getPaperReport",
        "exportPaperTrades",
        "listAgents",
        "getAgentHealth",
        "listAgentEvents",
        "listAlerts",
        "acknowledgeAlert",
        "getAlertPreferences",
        "updateAlertPreferences",
    }
)

CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22}$")
MAX_INVITE_TTL = timedelta(minutes=15)
_PHONE = re.compile(r"^\+91[6-9][0-9]{9}$")


class TesterError(Exception):
    """A usage error to show to the operator."""


def operation_allowed(operation_id: str | None) -> bool:
    return operation_id is not None and operation_id in TESTER_ALLOWED_OPERATIONS


def new_code() -> str:
    """16 random bytes as an unpadded base64url string (22 characters)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")


def code_digest(keys: Keys, phone: str, code: str) -> str:
    """Keyed digest bound to the phone, so a code only matches its own tester."""
    return hmac_hex(keys.tester, "invite", phone, code)


def _validate_phone(phone: str) -> str:
    if not _PHONE.fullmatch(phone):
        raise TesterError("phone must be an Indian mobile number in E.164 form (+91...)")
    return phone


def _audit(
    db: AsyncSession, user_id: uuid.UUID, action: str, now: datetime, metadata: dict[str, str]
) -> None:
    db.add(
        AuditEvent(
            user_id=user_id,
            actor="operator",
            action=action,
            resource=None,
            metadata_redacted=metadata,
            created_at=now,
        )
    )


async def _identity(db: AsyncSession, phone: str) -> uuid.UUID | None:
    return await db.scalar(
        select(TesterIdentity.user_id)
        .join(User, User.id == TesterIdentity.user_id)
        .where(User.phone_e164 == phone)
    )


async def issue_invite(
    db: AsyncSession, keys: Keys, phone: str, ttl: timedelta, now: datetime
) -> str:
    """Create the tester identity if needed and one new invite; return its code.

    Refuses a number that belongs to a regular account. An earlier unused
    invite for the same tester is revoked, so at most one code is live."""
    _validate_phone(phone)
    if ttl > MAX_INVITE_TTL or ttl <= timedelta(0):
        raise TesterError("an invite lasts at most 15 minutes")
    # One issuance per tester at a time, released at the commit below.
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"tester:{phone}", 0)))
    )
    user_id = await _identity(db, phone)
    if user_id is None:
        taken = await db.scalar(select(User.id).where(User.phone_e164 == phone)) or await db.scalar(
            select(Invite.phone_e164).where(Invite.phone_e164 == phone)
        )
        if taken is not None:
            raise TesterError("that number belongs to a regular account")
        user_id = uuid.uuid4()
        db.add(
            User(
                id=user_id,
                phone_e164=phone,
                display_name="Tester",
                created_at=now,
                updated_at=now,
            )
        )
        await db.flush()
        db.add(TesterIdentity(user_id=user_id, created_at=now))
        await db.flush()
    # A purged tester that is issued a new code is active again.
    await db.execute(
        update(TesterIdentity).where(TesterIdentity.user_id == user_id).values(purged_at=None)
    )
    await db.execute(
        update(TesterInvite)
        .where(
            TesterInvite.user_id == user_id,
            TesterInvite.used_at.is_(None),
            TesterInvite.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    code = new_code()
    invite_id = uuid.uuid4()
    db.add(
        TesterInvite(
            id=invite_id,
            user_id=user_id,
            code_digest=code_digest(keys, phone, code),
            created_at=now,
            expires_at=now + ttl,
        )
    )
    _audit(db, user_id, "tester.invite_issued", now, {"invite_id": str(invite_id)})
    await db.commit()
    return code


async def revoke_access(db: AsyncSession, phone: str, now: datetime) -> bool:
    """Invalidate every unused code and end every session of the tester at once.

    The invites are updated first, including used ones, so a redemption that
    is racing with this either sees the revocation (and fails) or has already
    committed a session that the second statement then ends."""
    _validate_phone(phone)
    user_id = await _identity(db, phone)
    if user_id is None:
        return False
    await db.execute(
        update(TesterInvite)
        .where(TesterInvite.user_id == user_id, TesterInvite.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    ended = await db.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    _audit(
        db,
        user_id,
        "tester.access_revoked",
        now,
        {"sessions_ended": str(getattr(ended, "rowcount", 0))},
    )
    await db.commit()
    return True


async def purge_credentials(db: AsyncSession, phone: str, now: datetime) -> bool:
    """Delete every invite (and with them the sessions) of the tester. The
    identity row stays, marked purged, and so do the audit events."""
    _validate_phone(phone)
    # Same lock as issue_invite, so the two take their row locks one at a time.
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"tester:{phone}", 0)))
    )
    user_id = await _identity(db, phone)
    if user_id is None:
        return False
    await db.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.execute(
        TesterInvite.__table__.delete().where(TesterInvite.user_id == user_id)  # type: ignore[attr-defined]
    )
    await db.execute(
        update(TesterIdentity).where(TesterIdentity.user_id == user_id).values(purged_at=now)
    )
    _audit(db, user_id, "tester.credentials_purged", now, {})
    await db.commit()
    return True


async def list_testers(db: AsyncSession) -> list[tuple[str, bool, int]]:
    """(masked phone, purged, live invites) per tester identity."""
    from app.auth.otp import mask_destination

    rows = await db.execute(
        select(User.phone_e164, TesterIdentity.purged_at, TesterIdentity.user_id)
        .join(User, User.id == TesterIdentity.user_id)
        .order_by(TesterIdentity.created_at)
    )
    out: list[tuple[str, bool, int]] = []
    now = datetime.now().astimezone()
    for phone, purged_at, user_id in rows.all():
        live = (
            await db.scalars(
                select(TesterInvite.id).where(
                    TesterInvite.user_id == user_id,
                    TesterInvite.used_at.is_(None),
                    TesterInvite.revoked_at.is_(None),
                    TesterInvite.expires_at > now,
                )
            )
        ).all()
        out.append((mask_destination(phone), purged_at is not None, len(live)))
    return out


async def revoke_all_tester_sessions(db: AsyncSession, now: datetime) -> int:
    """Used at startup when the feature is off: every tester session ends."""
    result = await db.execute(
        update(SessionRow)
        .where(SessionRow.tester_invite_id.is_not(None), SessionRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "CODE_PATTERN",
    "TESTER_ALLOWED_OPERATIONS",
    "TesterError",
    "code_digest",
    "issue_invite",
    "list_testers",
    "new_code",
    "operation_allowed",
    "purge_credentials",
    "revoke_access",
    "revoke_all_tester_sessions",
]
