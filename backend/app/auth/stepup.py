"""Authenticator-app (TOTP) enrolment and the step-up window.

A step-up proves a current TOTP code on one session for a short window
(`sessions.step_up_until`). Codes are accepted once: the accepted 30-second
time step is stored with a compare-and-set UPDATE, so concurrent or replayed
submissions of one code cannot both pass. Wrong codes are rate limited per user
and per IP before the code is looked at, and every outcome is audited without
the code or the secret."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import totp
from app.auth.crypto import Keys, hmac_hex
from app.auth.models import AuditEvent, RecoveryCode, TotpCredential
from app.auth.models import Session as SessionRow
from app.auth.ratelimit import RateLimiter
from app.core.config import Settings
from app.core.errors import ApiError

logger = structlog.get_logger(__name__)

Outcome = Literal["ok", "invalid", "missing"]

RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def _new_recovery_code() -> str:
    pick = secrets.choice
    return "-".join("".join(pick(_RECOVERY_ALPHABET) for _ in range(5)) for _ in range(2))


def step_up_required() -> ApiError:
    return ApiError(
        403, "STEP_UP_REQUIRED", "Confirm with your authenticator, or sign in again, to continue."
    )


def _invalid() -> ApiError:
    return ApiError(422, "INVALID_TOTP", "The code is invalid or has expired.")


class StepUpService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        limiter: RateLimiter,
        keys: Keys,
        clock: Callable[[], datetime],
    ) -> None:
        self._s = settings
        self._factory = session_factory
        self._limiter = limiter
        self._keys = keys
        self._clock = clock

    # ------------------------------------------------------------- enrolment

    async def enroll(
        self, *, user_id: uuid.UUID, session_created_at: datetime, account: str, ip: str
    ) -> tuple[str, str, datetime]:
        """Create (or replace) a pending secret. Returns (base32, otpauth URI, expiry)."""
        now = self._clock()
        if now - session_created_at > timedelta(seconds=self._s.totp_enroll_recent_seconds):
            raise step_up_required()
        await self._throttle(user_id, ip, "enroll")
        secret = totp.new_secret()
        expires = now + timedelta(seconds=self._s.totp_pending_ttl_seconds)
        async with self._factory() as db, db.begin():
            sealed = totp.seal(self._keys.totp, user_id, secret)
            stmt = insert(TotpCredential).values(
                user_id=user_id,
                secret_enc=sealed,
                created_at=now,
                confirmed_at=None,
                pending_expires_at=expires,
                last_step=0,
            )
            written = await db.scalar(
                stmt.on_conflict_do_update(
                    index_elements=[TotpCredential.user_id],
                    set_={
                        "secret_enc": stmt.excluded.secret_enc,
                        "created_at": now,
                        "pending_expires_at": expires,
                        "last_step": 0,
                    },
                    # Never replace an active authenticator.
                    where=TotpCredential.confirmed_at.is_(None),
                ).returning(TotpCredential.user_id)
            )
            if written is None:
                raise ApiError(409, "TOTP_ALREADY_ENROLLED", "An authenticator is already set up.")
            self._audit(db, user_id, "totp.enrollment_started", now)
        return totp.secret_to_base32(secret), totp.otpauth_uri(secret, account=account), expires

    async def confirm(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, code: str, ip: str
    ) -> datetime:
        """Activate the pending secret and step the calling session up."""
        await self._throttle(user_id, ip, "verify")
        failure: ApiError | None = None
        until: datetime | None = None
        async with self._factory() as db, db.begin():
            now = self._clock()
            outcome = await self._consume(db, user_id, code, now, pending=True)
            if outcome == "missing":
                failure = ApiError(409, "TOTP_NOT_PENDING", "Start the authenticator setup again.")
            elif outcome == "invalid":
                failure = _invalid()
                self._audit(db, user_id, "totp.confirm_failed", now)
            else:
                await db.execute(
                    update(TotpCredential)
                    .where(TotpCredential.user_id == user_id)
                    .values(confirmed_at=now, pending_expires_at=None)
                )
                # A new authenticator starts with no recovery codes.
                await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
                until = await self._open_window(db, session_id, now)
                self._audit(db, user_id, "totp.enabled", now)
        if failure is not None or until is None:
            raise failure or _invalid()
        return until

    # --------------------------------------------------------------- step-up

    async def step_up(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, code: str, ip: str
    ) -> datetime:
        await self._throttle(user_id, ip, "verify")
        failure: ApiError | None = None
        until: datetime | None = None
        async with self._factory() as db, db.begin():
            now = self._clock()
            outcome = await self._consume(db, user_id, code, now, pending=False)
            if outcome == "missing":
                failure = ApiError(409, "TOTP_NOT_ENROLLED", "Set up an authenticator first.")
            elif outcome == "invalid":
                failure = _invalid()
                self._audit(db, user_id, "totp.step_up_failed", now)
            else:
                until = await self._open_window(db, session_id, now)
                self._audit(db, user_id, "totp.step_up", now)
        if failure is not None or until is None:
            raise failure or _invalid()
        return until

    async def disable(self, *, user_id: uuid.UUID, code: str, ip: str) -> None:
        await self._throttle(user_id, ip, "verify")
        failure: ApiError | None = None
        async with self._factory() as db, db.begin():
            now = self._clock()
            outcome = await self._consume(db, user_id, code, now, pending=False)
            if outcome == "missing":
                failure = ApiError(409, "TOTP_NOT_ENROLLED", "Set up an authenticator first.")
            elif outcome == "invalid":
                failure = _invalid()
                self._audit(db, user_id, "totp.disable_failed", now)
            else:
                await db.execute(delete(TotpCredential).where(TotpCredential.user_id == user_id))
                await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
                await db.execute(
                    update(SessionRow)
                    .where(SessionRow.user_id == user_id)
                    .values(step_up_until=None)
                )
                self._audit(db, user_id, "totp.disabled", now)
        if failure is not None:
            raise failure

    # ------------------------------------------------------- sign-in support

    async def consume_login_code(
        self, db: AsyncSession, user_id: uuid.UUID, code: str, now: datetime
    ) -> Outcome:
        """Check a sign-in code against the active secret (single use per time step)."""
        return await self._consume(db, user_id, code, now, pending=False)

    # --------------------------------------------------------- recovery codes

    def _recovery_digest(self, user_id: uuid.UUID, code: str) -> str:
        return hmac_hex(self._keys.totp, "recovery", str(user_id), code)

    async def regenerate_recovery_codes(
        self, *, user_id: uuid.UUID, ip: str
    ) -> tuple[list[str], datetime]:
        """Replace every recovery code of the account with a new set of ten.
        The caller has already been checked for step-up. Needs an active
        authenticator; the codes are returned once and only digests are kept."""
        await self._throttle(user_id, ip, "recovery")
        codes: list[str] = []
        while len(codes) < RECOVERY_CODE_COUNT:
            candidate = _new_recovery_code()
            if candidate not in codes:
                codes.append(candidate)
        async with self._factory() as db, db.begin():
            now = self._clock()
            confirmed = await db.scalar(
                select(TotpCredential.confirmed_at)
                .where(TotpCredential.user_id == user_id)
                .with_for_update()
            )
            if confirmed is None:
                raise ApiError(409, "TOTP_NOT_ENROLLED", "Set up an authenticator first.")
            await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
            for code in codes:
                db.add(
                    RecoveryCode(
                        user_id=user_id,
                        digest=self._recovery_digest(user_id, code),
                        created_at=now,
                    )
                )
            self._audit(db, user_id, "totp.recovery_codes_created", now)
        return codes, now

    async def consume_recovery_code(
        self, db: AsyncSession, user_id: uuid.UUID, code: str, now: datetime
    ) -> Outcome:
        """Spend one recovery code at sign-in. The DELETE is the compare-and-set:
        of concurrent submissions of one code only one gets the row. On success
        the authenticator and every other code are removed too, and every
        step-up window of the account is closed."""
        # Same lock order as regeneration and disable: the authenticator row first.
        confirmed = await db.scalar(
            select(TotpCredential.confirmed_at)
            .where(TotpCredential.user_id == user_id)
            .with_for_update()
        )
        if confirmed is None:
            return "invalid"
        spent = await db.scalar(
            delete(RecoveryCode)
            .where(
                RecoveryCode.user_id == user_id,
                RecoveryCode.digest == self._recovery_digest(user_id, code),
            )
            .returning(RecoveryCode.id)
        )
        if spent is None:
            return "invalid"
        await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
        await db.execute(delete(TotpCredential).where(TotpCredential.user_id == user_id))
        await db.execute(
            update(SessionRow).where(SessionRow.user_id == user_id).values(step_up_until=None)
        )
        self._audit(db, user_id, "totp.reset_by_recovery_code", now)
        return "ok"

    def dummy_recovery_check(self, code: str) -> None:
        """The same HMAC work as a real check, for a number that cannot sign in."""
        self._recovery_digest(uuid.UUID(int=0), code)

    def dummy_check(self, code: str, now: datetime) -> None:
        """The same HMAC work as a real check, for a number that has no secret."""
        totp.matching_step(b"\x00" * 20, code, now.timestamp())

    # --------------------------------------------------------------- helpers

    async def _throttle(self, user_id: uuid.UUID, ip: str, kind: str) -> None:
        s = self._s
        ip_key = hmac_hex(self._keys.identifier, "ip", ip)[:32]
        for name, subject, limit in (
            (f"totp_{kind}_user", str(user_id), s.rate_limit_totp_per_user),
            (f"totp_{kind}_ip", ip_key, s.rate_limit_totp_per_ip),
        ):
            retry = await self._limiter.hit(name, subject, limit, s.rate_limit_totp_window_seconds)
            if retry is not None:
                raise ApiError(
                    429,
                    "RATE_LIMITED",
                    "Too many attempts. Try again later.",
                    retry_after_seconds=retry,
                )

    async def _consume(
        self, db: AsyncSession, user_id: uuid.UUID, code: str, now: datetime, *, pending: bool
    ) -> Outcome:
        """Check `code` against the user's pending or confirmed secret and, if it
        matches a time step not used before, record the step. The compare-and-set
        UPDATE is what makes a code single use under concurrency."""
        row = await db.scalar(
            select(TotpCredential).where(TotpCredential.user_id == user_id).with_for_update()
        )
        if row is None:
            return "missing"
        if pending:
            if (
                row.confirmed_at is not None
                or row.pending_expires_at is None
                or row.pending_expires_at <= now
            ):
                return "missing"
        elif row.confirmed_at is None:
            return "missing"
        secret = totp.unseal(self._keys.totp, user_id, row.secret_enc)
        if secret is None:  # damaged or copied row: treat as not usable, never as a pass
            logger.error("totp_secret_unreadable")
            return "invalid"
        step = totp.matching_step(secret, code, now.timestamp())
        if step is None or step <= row.last_step:
            return "invalid"
        await db.execute(
            update(TotpCredential)
            .where(TotpCredential.user_id == user_id, TotpCredential.last_step < step)
            .values(last_step=step)
        )
        return "ok"

    async def _open_window(
        self, db: AsyncSession, session_id: uuid.UUID, now: datetime
    ) -> datetime:
        until = now + timedelta(seconds=self._s.step_up_ttl_seconds)
        stored: datetime | None = await db.scalar(
            update(SessionRow)
            .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
            # Never past the session's own expiry, in the database as well as the reply.
            .values(step_up_until=func.least(until, SessionRow.expires_at))
            .returning(SessionRow.step_up_until)
        )
        if stored is None:
            raise step_up_required()
        return stored

    def _audit(self, db: AsyncSession, user_id: uuid.UUID, action: str, now: datetime) -> None:
        db.add(
            AuditEvent(
                user_id=user_id,
                actor=f"user:{user_id}",
                action=action,
                resource=f"totp:{user_id}",
                metadata_redacted={},
                created_at=now,
            )
        )
