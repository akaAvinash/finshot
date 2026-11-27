"""Changing an account's phone number (contract 0.13.0, Settings tag).

Two steps in one stepped-up session: `request` sends a one-time code by SMS to
the new number, `confirm` checks it and moves the account, its invite and its
other sessions over in one transaction.

Takeover rules kept here:
- The challenge is bound to the requesting session and account, single use,
  at most `otp_max_attempts` attempts, and expires with the OTP TTL.
- The code digest uses its own label, so a phone-change code can never verify
  a sign-in challenge and the reverse.
- A number that already belongs to an account or has any invite is answered
  like any other number, but nothing is sent and the challenge is marked
  `suppressed`, so it can never be confirmed. This keeps the API from telling
  which numbers have accounts. The confirm transaction checks again under a
  per-number lock, so a race cannot take a number either.
- Audit rows never contain a phone number or a code."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import structlog
from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.alerts import producer as alerts
from app.auth.crypto import constant_time_equal, hmac_hex
from app.auth.models import Invite, PhoneChangeChallenge, User
from app.auth.models import Session as SessionRow
from app.auth.otp import DisabledOtpProvider, OtpDeliveryError, generate_code, mask_phone
from app.auth.service import AuthService, SessionInfo, _delivery_unavailable, _rate_limited
from app.core.errors import ApiError

logger = structlog.get_logger(__name__)


def phone_unchanged() -> ApiError:
    return ApiError(400, "PHONE_UNCHANGED", "This is already your phone number.")


def code_invalid() -> ApiError:
    return ApiError(
        400, "PHONE_CHANGE_CODE_INVALID", "The code is invalid or has expired. Request a new code."
    )


class PhoneChangeService:
    def __init__(self, auth: AuthService) -> None:
        self._auth = auth

    def _digest(self, challenge_id: uuid.UUID, code: str) -> str:
        return hmac_hex(self._auth.keys.otp, "phone-change", str(challenge_id), code)

    async def _taken(self, phone: str) -> bool:
        async with self._auth._factory() as db:
            user = await db.scalar(select(User.id).where(User.phone_e164 == phone))
            invite = await db.scalar(select(Invite.phone_e164).where(Invite.phone_e164 == phone))
        return user is not None or invite is not None

    async def request(
        self, *, request: Request, session: SessionInfo, new_phone: str
    ) -> tuple[uuid.UUID, datetime, datetime, str]:
        auth = self._auth
        s = auth.settings
        limiter = auth._limiter
        if new_phone == session.phone_e164:
            raise phone_unchanged()
        ip = auth.client_ip(request)
        for kind, subject, limit, window in (
            (
                "phone_change_user",
                str(session.user_id),
                s.rate_limit_phone_change_per_user,
                s.rate_limit_phone_change_window_seconds,
            ),
            (
                "otp_req_ip",
                ip,
                s.rate_limit_otp_request_per_ip,
                s.rate_limit_otp_request_window_seconds,
            ),
        ):
            retry = await limiter.hit(kind, subject, limit, window)
            if retry is not None:
                raise _rate_limited(retry)
        retry = await limiter.cooldown("otp_cooldown", new_phone, s.otp_resend_cooldown_seconds)
        if retry is not None:
            raise _rate_limited(retry)
        retry = await limiter.hit(
            "otp_req_phone",
            new_phone,
            s.rate_limit_otp_request_per_phone,
            s.rate_limit_otp_request_window_seconds,
        )
        if retry is not None:
            raise _rate_limited(retry)

        provider = auth._provider
        # Availability first, so a missing provider answers every number alike.
        if isinstance(provider, DisabledOtpProvider):
            raise _delivery_unavailable()
        suppressed = await self._taken(new_phone)
        now = auth.clock()
        await auth._enforce_spend_limits(new_phone, now, count=not suppressed)
        challenge_id = uuid.uuid4()
        code = generate_code() if suppressed else provider.new_code()
        expires_at = now + timedelta(seconds=s.otp_ttl_seconds)
        async with auth._factory() as db, db.begin():
            db.add(
                PhoneChangeChallenge(
                    id=challenge_id,
                    user_id=session.user_id,
                    session_id=session.session_id,
                    new_phone_e164=new_phone,
                    code_digest=self._digest(challenge_id, code),
                    suppressed=suppressed,
                    attempts=0,
                    expires_at=expires_at,
                    created_at=now,
                )
            )
            await auth._audit(
                db,
                action="phone.change_requested",
                user_id=session.user_id,
                resource=f"phone_change:{challenge_id}",
                metadata={
                    "ip_hash": auth._ip_hash(ip),
                    "delivery": "suppressed" if suppressed else "attempted",
                },
            )
        if not suppressed:
            try:
                await provider.deliver(new_phone, code)
            except OtpDeliveryError as exc:
                logger.warning("phone_change_delivery_failed", reason=str(exc))
                async with auth._factory() as db, db.begin():
                    await db.execute(
                        update(PhoneChangeChallenge)
                        .where(PhoneChangeChallenge.id == challenge_id)
                        .values(consumed_at=now)
                    )
                raise _delivery_unavailable() from exc
        resend_at = now + timedelta(seconds=s.otp_resend_cooldown_seconds)
        return challenge_id, expires_at, resend_at, mask_phone(new_phone)

    async def confirm(
        self, *, request: Request, session: SessionInfo, challenge_id: uuid.UUID, code: str
    ) -> None:
        auth = self._auth
        s = auth.settings
        ip = auth.client_ip(request)
        retry = await auth._limiter.hit(
            "phone_change_verify_user",
            str(session.user_id),
            s.rate_limit_phone_change_verify_per_user,
            s.rate_limit_phone_change_window_seconds,
        )
        if retry is not None:
            raise _rate_limited(retry)

        # Count the attempt before checking the code; the same UPDATE enforces
        # owner, session, single use, expiry and the attempt limit.
        async with auth._factory() as db, db.begin():
            now = auth.clock()
            row = (
                await db.execute(
                    update(PhoneChangeChallenge)
                    .where(
                        PhoneChangeChallenge.id == challenge_id,
                        PhoneChangeChallenge.user_id == session.user_id,
                        PhoneChangeChallenge.session_id == session.session_id,
                        PhoneChangeChallenge.consumed_at.is_(None),
                        PhoneChangeChallenge.expires_at > now,
                        PhoneChangeChallenge.attempts < s.otp_max_attempts,
                    )
                    .values(attempts=PhoneChangeChallenge.attempts + 1)
                    .returning(
                        PhoneChangeChallenge.new_phone_e164,
                        PhoneChangeChallenge.code_digest,
                        PhoneChangeChallenge.suppressed,
                    )
                )
            ).first()
        if row is None:
            await self._failed(session, challenge_id, ip, "challenge")
            raise code_invalid()
        new_phone, digest, suppressed = row
        if not constant_time_equal(self._digest(challenge_id, code), digest) or suppressed:
            await self._failed(session, challenge_id, ip, "code")
            raise code_invalid()

        try:
            async with auth._factory() as db, db.begin():
                # Serialise every change to the same number, then take the account
                # row. Read the clock only after both locks: waiting for them must
                # not let an expired challenge or a closed step-up window through.
                lock_key = func.hashtextextended(f"phone:{new_phone}", 0)
                await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
                user = await db.scalar(
                    select(User).where(User.id == session.user_id).with_for_update()
                )
                now = auth.clock()
                consumed = await db.scalar(
                    update(PhoneChangeChallenge)
                    .where(
                        PhoneChangeChallenge.id == challenge_id,
                        PhoneChangeChallenge.consumed_at.is_(None),
                        PhoneChangeChallenge.expires_at > now,
                    )
                    .values(consumed_at=now)
                    .returning(PhoneChangeChallenge.id)
                )
                if consumed is None:
                    raise code_invalid()
                taken = await db.scalar(
                    select(func.count()).select_from(User).where(User.phone_e164 == new_phone)
                ) or await db.scalar(
                    select(func.count()).select_from(Invite).where(Invite.phone_e164 == new_phone)
                )
                if taken:
                    raise code_invalid()
                if user is None or user.status != "active":
                    raise code_invalid()
                # The initiating session must still be live and stepped up: another
                # session may have ended it while this request waited.
                live = await db.scalar(
                    select(SessionRow.id).where(
                        SessionRow.id == session.session_id,
                        SessionRow.user_id == session.user_id,
                        SessionRow.revoked_at.is_(None),
                        SessionRow.expires_at > now,
                        SessionRow.step_up_until > now,
                    )
                )
                if live is None:
                    raise code_invalid()
                old_phone = user.phone_e164
                old_invite = await db.scalar(
                    select(Invite)
                    .where(Invite.phone_e164 == old_phone, Invite.revoked_at.is_(None))
                    .with_for_update()
                )
                if old_invite is None:
                    raise code_invalid()
                db.add(Invite(phone_e164=new_phone, email=old_invite.email, created_at=now))
                old_invite.revoked_at = now
                user.phone_e164 = new_phone
                user.phone_verified_at = now
                user.updated_at = now
                ended = await db.execute(
                    update(SessionRow)
                    .where(
                        SessionRow.user_id == session.user_id,
                        SessionRow.id != session.session_id,
                        SessionRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                await auth._audit(
                    db,
                    action="phone.changed",
                    user_id=session.user_id,
                    resource=f"phone_change:{challenge_id}",
                    metadata={
                        "ip_hash": auth._ip_hash(ip),
                        "sessions_ended": int(ended.rowcount or 0),  # type: ignore[attr-defined]
                    },
                )
                await alerts.record(
                    db,
                    user_id=session.user_id,
                    kind="PHONE_CHANGED",
                    dedupe_key=f"phone-changed:{challenge_id}",
                    message=(
                        "Your account's phone number was changed and your other sessions "
                        "were signed out. If this was not you, contact the owner now."
                    ),
                    at=now,
                    link=("session", str(session.session_id)),
                )
        except IntegrityError:
            # A concurrent change took the number first.
            raise code_invalid() from None

    async def _failed(
        self, session: SessionInfo, challenge_id: uuid.UUID, ip: str, reason: str
    ) -> None:
        async with self._auth._factory() as db, db.begin():
            await self._auth._audit(
                db,
                action="phone.change_failed",
                user_id=session.user_id,
                resource=f"phone_change:{challenge_id}",
                metadata={"ip_hash": self._auth._ip_hash(ip), "reason": reason},
            )
