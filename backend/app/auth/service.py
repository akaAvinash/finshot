"""Authentication service: OTP challenges, sessions, CSRF decisions, audit."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts import producer as alerts
from app.auth import csrf as csrf_tokens
from app.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from app.auth.crypto import Keys, constant_time_equal, hmac_hex
from app.auth.models import AuditEvent, Invite, OtpChallenge, TotpCredential, User
from app.auth.models import Session as SessionRow
from app.auth.otp import DisabledOtpProvider, OtpDeliveryError, OtpProvider, generate_code
from app.auth.ratelimit import RateLimiter
from app.auth.stepup import StepUpService
from app.core.config import Settings
from app.core.errors import ApiError

logger = structlog.get_logger(__name__)

Clock = Callable[[], datetime]
CSRF_HEADER = "X-CSRF-Token"
_LAST_SEEN_RESOLUTION = timedelta(seconds=60)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SessionInfo:
    session_id: uuid.UUID
    user_id: uuid.UUID
    phone_e164: str
    display_name: str | None
    user_created_at: datetime
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    device_label: str | None
    totp_enabled: bool = False
    step_up_until: datetime | None = None


def _unauthenticated() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")


def _invalid_credentials() -> ApiError:
    return ApiError(401, "INVALID_CREDENTIALS", "The phone number or code is not valid.")


def _invalid_otp() -> ApiError:
    return ApiError(401, "INVALID_OTP", "The code is invalid or has expired.")


def _csrf_failed() -> ApiError:
    return ApiError(403, "CSRF_FAILED", "The request could not be verified. Reload and try again.")


def _delivery_unavailable() -> ApiError:
    return ApiError(
        503,
        "OTP_DELIVERY_UNAVAILABLE",
        "We could not send a code right now. Try again shortly.",
    )


def _rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429, "RATE_LIMITED", "Too many attempts. Try again later.", retry_after_seconds=retry_after
    )


def device_label_from_user_agent(user_agent: str | None) -> str | None:
    """A coarse label such as "Chrome on macOS". The raw User-Agent is not stored."""
    if not user_agent:
        return None
    ua = user_agent
    browser = next(
        (
            name
            for marker, name in (
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if marker in ua
        ),
        "Browser",
    )
    os_name = next(
        (
            name
            for marker, name in (
                ("Android", "Android"),
                ("iPhone", "iOS"),
                ("iPad", "iPadOS"),
                ("Windows", "Windows"),
                ("Mac OS X", "macOS"),
                ("Linux", "Linux"),
            )
            if marker in ua
        ),
        "unknown OS",
    )
    return f"{browser} on {os_name}"


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        limiter: RateLimiter,
        provider: OtpProvider,
        keys: Keys,
        clock: Clock = utc_now,
        email_provider: OtpProvider | None = None,
        stepup: StepUpService | None = None,
    ) -> None:
        self._stepup = stepup
        self.settings = settings
        self._factory = session_factory
        self._limiter = limiter
        self._provider = provider
        self._email_provider = email_provider
        self.keys = keys
        self.clock = clock

    # ------------------------------------------------------------------ helpers

    def client_ip(self, request: Request) -> str:
        hops = self.settings.trusted_proxy_hops
        if hops > 0:
            forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
            forwarded = [p for p in forwarded if p]
            if len(forwarded) >= hops:
                return forwarded[-hops]
        return request.client.host if request.client else "unknown"

    def _ip_hash(self, ip: str) -> str:
        return hmac_hex(self.keys.identifier, "ip", ip)[:32]

    def _session_digest(self, token: str) -> str:
        return hmac_hex(self.keys.session, token)

    async def _audit(
        self,
        db: AsyncSession,
        *,
        action: str,
        user_id: uuid.UUID | None,
        resource: str | None,
        metadata: dict[str, Any],
    ) -> None:
        db.add(
            AuditEvent(
                user_id=user_id,
                actor=f"user:{user_id}" if user_id else "anonymous",
                action=action,
                resource=resource,
                metadata_redacted=metadata,
                created_at=self.clock(),
            )
        )

    # -------------------------------------------------------------------- CSRF

    def issue_token(
        self, context: csrf_tokens.Context, context_id: str, expires_at: datetime
    ) -> str:
        return csrf_tokens.issue(
            self.keys,
            csrf_tokens.CsrfClaims(context=context, context_id=context_id, expires_at=expires_at),
        )

    def pre_login_expiry(self) -> datetime:
        return self.clock() + timedelta(seconds=self.settings.csrf_pre_login_ttl_seconds)

    def enforce_csrf(self, request: Request, session: SessionInfo | None) -> csrf_tokens.CsrfClaims:
        """Check Origin, header == cookie, signature, expiry and context.

        The context is decided by the server-side session, never by the mere
        presence of a cookie: a stale session cookie means pre-login."""
        origin = request.headers.get("origin")
        if origin is not None and origin != self.settings.public_origin:
            raise _csrf_failed()
        header = request.headers.get(CSRF_HEADER)
        cookie = request.cookies.get(CSRF_COOKIE)
        if not header or not cookie or not constant_time_equal(header, cookie):
            raise _csrf_failed()
        claims = csrf_tokens.verify(self.keys, header, self.clock())
        if claims is None:
            raise _csrf_failed()
        if session is not None:
            ok = claims.context == "session" and claims.context_id == str(session.session_id)
        else:
            ok = claims.context == "pre_login"
        if not ok:
            raise _csrf_failed()
        return claims

    async def csrf_for_request(
        self, request: Request
    ) -> tuple[csrf_tokens.CsrfClaims, str, bool, bool]:
        """Decide what GET /auth/csrf returns.

        Returns (claims, token, new_token_issued, clear_stale_session_cookie)."""
        ip = self.client_ip(request)
        retry = await self._limiter.hit(
            "csrf_ip",
            ip,
            self.settings.rate_limit_csrf_per_ip,
            self.settings.rate_limit_csrf_window_seconds,
        )
        if retry is not None:
            raise _rate_limited(retry)

        session_cookie = request.cookies.get(SESSION_COOKIE)
        session = await self.resolve_session(session_cookie)
        stale = session_cookie is not None and session is None

        existing_token = request.cookies.get(CSRF_COOKIE)
        existing = csrf_tokens.verify(self.keys, existing_token, self.clock())
        if existing is not None and existing_token is not None:
            if session is not None:
                reusable = existing.context == "session" and existing.context_id == str(
                    session.session_id
                )
            else:
                reusable = existing.context == "pre_login"
            if reusable:
                return existing, existing_token, False, stale

        if session is not None:
            claims = csrf_tokens.CsrfClaims("session", str(session.session_id), session.expires_at)
        else:
            claims = csrf_tokens.CsrfClaims(
                "pre_login", csrf_tokens.new_pre_login_context_id(), self.pre_login_expiry()
            )
        return claims, csrf_tokens.issue(self.keys, claims), True, stale

    # ---------------------------------------------------------------- sessions

    async def resolve_session(self, token: str | None) -> SessionInfo | None:
        """Return the session only if it exists and is unrevoked, within both its
        idle and absolute expiry, and its user is active."""
        if not token or len(token) > 256:
            return None
        now = self.clock()
        digest = self._session_digest(token)
        idle = timedelta(seconds=self.settings.session_idle_ttl_seconds)
        async with self._factory() as db:
            row = (
                await db.execute(
                    select(SessionRow, User, TotpCredential.confirmed_at)
                    .join(User, User.id == SessionRow.user_id)
                    .outerjoin(TotpCredential, TotpCredential.user_id == User.id)
                    # Revoking an invite ends access at once, even for a session a
                    # concurrent verification created just before the revocation.
                    .join(
                        Invite,
                        (Invite.phone_e164 == User.phone_e164) & Invite.revoked_at.is_(None),
                    )
                    .where(
                        SessionRow.session_digest == digest,
                        SessionRow.revoked_at.is_(None),
                        SessionRow.expires_at > now,
                        SessionRow.last_seen_at + idle > now,
                        User.status == "active",
                    )
                )
            ).first()
            if row is None:
                return None
            sess, user, totp_confirmed_at = row
            last_seen = sess.last_seen_at
            # Throttle writes, but never beyond a quarter of the idle TTL, so a
            # short idle TTL can still be renewed by regular activity.
            resolution = min(_LAST_SEEN_RESOLUTION, idle / 4)
            if now - last_seen >= resolution:
                # GREATEST: a concurrent renewal with a later timestamp must win.
                renewed = await db.scalar(
                    update(SessionRow)
                    .where(SessionRow.id == sess.id)
                    .values(last_seen_at=func.greatest(SessionRow.last_seen_at, now))
                    .returning(SessionRow.last_seen_at)
                )
                await db.commit()
                if renewed is not None:
                    last_seen = renewed
            return SessionInfo(
                session_id=sess.id,
                user_id=user.id,
                phone_e164=user.phone_e164,
                display_name=user.display_name,
                user_created_at=user.created_at,
                created_at=sess.created_at,
                last_seen_at=last_seen,
                expires_at=sess.expires_at,
                device_label=sess.device_label,
                totp_enabled=totp_confirmed_at is not None,
                step_up_until=sess.step_up_until,
            )

    def idle_expires_at(self, info: SessionInfo) -> datetime:
        idle = info.last_seen_at + timedelta(seconds=self.settings.session_idle_ttl_seconds)
        return min(idle, info.expires_at)

    # --------------------------------------------------------------------- OTP

    async def request_otp(
        self,
        *,
        request: Request,
        phone: str,
        context_id: str,
        channel: str = "sms",
    ) -> tuple[uuid.UUID, datetime, datetime]:
        s = self.settings
        ip = self.client_ip(request)

        # IP and context limits come first so a throttled caller cannot reserve
        # the per-phone cooldown and lock out the phone's real owner.
        for kind, subject, limit in (
            ("otp_req_ip", ip, s.rate_limit_otp_request_per_ip),
            ("otp_req_ctx", context_id, s.rate_limit_otp_request_per_context),
        ):
            retry = await self._limiter.hit(
                kind, subject, limit, s.rate_limit_otp_request_window_seconds
            )
            if retry is not None:
                raise _rate_limited(retry)
        retry = await self._limiter.cooldown("otp_cooldown", phone, s.otp_resend_cooldown_seconds)
        if retry is not None:
            raise _rate_limited(retry)
        retry = await self._limiter.hit(
            "otp_req_phone",
            phone,
            s.rate_limit_otp_request_per_phone,
            s.rate_limit_otp_request_window_seconds,
        )
        if retry is not None:
            raise _rate_limited(retry)

        now = self.clock()
        challenge_id = uuid.uuid4()
        # Only an invited number gets a delivered code. For anyone else the
        # challenge is created the same way, with a random code that is never
        # sent, so the response and the timing do not reveal who is invited
        # and nothing is spent.
        # Availability is decided before the invite, so an outage, a missing
        # provider or a reached cap answers every number the same way (503).
        if isinstance(self._provider_for(channel), DisabledOtpProvider):
            raise _delivery_unavailable()
        destination, provider = await self._delivery_target(phone, channel)
        deliver = destination is not None and provider is not None
        await self._enforce_spend_limits(phone, now, count=deliver)
        code = provider.new_code() if deliver and provider is not None else generate_code()
        expires_at = now + timedelta(seconds=s.otp_ttl_seconds)
        async with self._factory() as db, db.begin():
            # Purge this phone's long-expired challenges (digests must not linger).
            await db.execute(
                delete(OtpChallenge).where(
                    OtpChallenge.phone_e164 == phone,
                    OtpChallenge.expires_at < now - timedelta(hours=1),
                )
            )
            db.add(
                OtpChallenge(
                    id=challenge_id,
                    phone_e164=phone,
                    code_digest=hmac_hex(self.keys.otp, str(challenge_id), code),
                    attempts=0,
                    expires_at=expires_at,
                    created_at=now,
                    request_ip_hash=self._ip_hash(ip),
                    context_id=context_id,
                )
            )
            await self._audit(
                db,
                action="otp_requested",
                user_id=None,
                resource=f"otp_challenge:{challenge_id}",
                metadata={
                    "ip_hash": self._ip_hash(ip),
                    "channel": channel,
                    "delivery": "attempted" if deliver else "suppressed",
                },
            )
        if deliver and destination is not None and provider is not None:
            try:
                await provider.deliver(destination, code)
            except OtpDeliveryError as exc:
                logger.warning("otp_delivery_failed", reason=str(exc), channel=channel)
                async with self._factory() as db, db.begin():
                    await db.execute(delete(OtpChallenge).where(OtpChallenge.id == challenge_id))
                raise _delivery_unavailable() from exc
        resend_at = now + timedelta(seconds=s.otp_resend_cooldown_seconds)
        return challenge_id, expires_at, resend_at

    async def _delivery_target(
        self, phone: str, channel: str
    ) -> tuple[str | None, OtpProvider | None]:
        """(destination, provider) for an invited number, else (None, None)."""
        async with self._factory() as db:
            invite = await db.scalar(
                select(Invite).where(Invite.phone_e164 == phone, Invite.revoked_at.is_(None))
            )
        if invite is None:
            return None, None
        # Once an authenticator is active, a code can no longer start a session,
        # so none is sent (the response to the caller is the same).
        if await self._has_authenticator(phone):
            return None, None
        if channel == "email":
            if not invite.email or self._email_provider is None:
                return None, None
            return invite.email, self._email_provider
        return phone, self._provider

    async def _has_authenticator(self, phone: str) -> bool:
        async with self._factory() as db:
            confirmed = await db.scalar(
                select(TotpCredential.confirmed_at)
                .join(User, User.id == TotpCredential.user_id)
                .where(User.phone_e164 == phone)
            )
        return confirmed is not None

    def _provider_for(self, channel: str) -> OtpProvider:
        if channel == "email":
            return self._email_provider or DisabledOtpProvider()
        return self._provider

    async def _enforce_spend_limits(self, phone: str, now: datetime, *, count: bool) -> None:
        """Per-day delivery caps; a reached cap answers every request the same way.

        The per-phone cap counts every request for that number, invited or not,
        so an invited number cannot be told apart by when it hits the cap. (A
        third party can already exhaust a number's request limit; this adds no
        new lever.) The global cap counts each delivery attempt (including one that then
        fails at the provider; it is not refunded) and is only checked, without
        counting, for requests that make no attempt. A request rejected by either cap leaves
        the global counter unchanged."""
        s = self.settings
        day = now.strftime("%Y%m%d")
        phone_subject = f"{day}:{phone}"
        if (
            await self._limiter.exceeded("otp_spend_all", day, s.otp_daily_delivery_limit)
            is not None
            or await self._limiter.exceeded(
                "otp_spend_phone", phone_subject, s.otp_daily_delivery_limit_per_phone
            )
            is not None
        ):
            logger.warning("otp_spend_limit_reached")
            raise _delivery_unavailable()
        if (
            await self._limiter.hit(
                "otp_spend_phone", phone_subject, s.otp_daily_delivery_limit_per_phone, 86_400
            )
            is not None
        ):
            logger.warning("otp_spend_limit_reached", kind="otp_spend_phone")
            raise _delivery_unavailable()
        if count and (
            await self._limiter.hit("otp_spend_all", day, s.otp_daily_delivery_limit, 86_400)
            is not None
        ):
            logger.warning("otp_spend_limit_reached", kind="otp_spend_all")
            raise _delivery_unavailable()

    async def verify_otp(
        self,
        *,
        request: Request,
        challenge_id: uuid.UUID,
        code: str,
        context_id: str,
        current_session: SessionInfo | None,
    ) -> tuple[SessionInfo, str, str]:
        """Returns (session info, raw session token, session-bound CSRF token)."""
        s = self.settings
        ip = self.client_ip(request)
        retry = await self._limiter.hit(
            "otp_verify_ip",
            ip,
            s.rate_limit_otp_verify_per_ip,
            s.rate_limit_otp_verify_window_seconds,
        )
        if retry is not None:
            raise _rate_limited(retry)

        now = self.clock()
        # A challenge requested from another browser/context cannot be completed
        # here. This does not consume attempts, so it cannot be used to burn
        # someone else's challenge.
        async with self._factory() as db:
            bound = await db.scalar(
                select(OtpChallenge.context_id).where(OtpChallenge.id == challenge_id)
            )
        if bound is None or not constant_time_equal(bound, context_id):
            raise _invalid_otp()

        # Count the attempt atomically before checking the code. The same UPDATE
        # enforces: unconsumed, unexpired, and under the attempt limit.
        async with self._factory() as db, db.begin():
            now = self.clock()  # sampled inside the transaction for the expiry check
            challenge = (
                await db.execute(
                    update(OtpChallenge)
                    .where(
                        OtpChallenge.id == challenge_id,
                        OtpChallenge.consumed_at.is_(None),
                        OtpChallenge.expires_at > now,
                        OtpChallenge.attempts < s.otp_max_attempts,
                    )
                    .values(attempts=OtpChallenge.attempts + 1)
                    .returning(OtpChallenge.phone_e164, OtpChallenge.code_digest)
                )
            ).first()
        if challenge is None:
            raise _invalid_otp()
        phone, digest = challenge

        expected = hmac_hex(self.keys.otp, str(challenge_id), code)
        if not constant_time_equal(expected, digest):
            async with self._factory() as db, db.begin():
                await self._audit(
                    db,
                    action="otp_verify_failed",
                    user_id=None,
                    resource=f"otp_challenge:{challenge_id}",
                    metadata={"ip_hash": self._ip_hash(ip)},
                )
            raise _invalid_otp()

        token = secrets.token_urlsafe(32)
        session_id = uuid.uuid4()
        expires_at = now + timedelta(seconds=s.session_absolute_ttl_seconds)
        label = device_label_from_user_agent(request.headers.get("user-agent"))
        async with self._factory() as db, db.begin():
            # Access is the invite list: a revoked or missing invite cannot sign in,
            # even with a valid code.
            invited = await db.scalar(
                select(Invite.phone_e164).where(
                    Invite.phone_e164 == phone, Invite.revoked_at.is_(None)
                )
            )
            if invited is None:
                raise _invalid_otp()
            # Single use: whoever flips consumed_at wins; a concurrent verify loses.
            consumed = await db.scalar(
                update(OtpChallenge)
                .where(OtpChallenge.id == challenge_id, OtpChallenge.consumed_at.is_(None))
                .values(consumed_at=now)
                .returning(OtpChallenge.id)
            )
            if consumed is None:
                raise _invalid_otp()

            users = User.__table__
            user_row = (
                await db.execute(
                    pg_insert(User)
                    .values(
                        id=uuid.uuid4(),
                        phone_e164=phone,
                        phone_verified_at=now,
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=[users.c.phone_e164],
                        set_={
                            "updated_at": now,
                            "phone_verified_at": func.coalesce(users.c.phone_verified_at, now),
                        },
                    )
                    .returning(users.c.id, users.c.status, users.c.display_name, users.c.created_at)
                )
            ).one()
            if user_row.status != "active":
                raise _invalid_otp()
            # Read inside the login transaction: if it fails, the code stays unused.
            totp_enabled = (
                await db.scalar(
                    select(TotpCredential.confirmed_at).where(TotpCredential.user_id == user_row.id)
                )
            ) is not None
            if totp_enabled:
                # The authenticator is the way in now; the rolled-back transaction
                # leaves the code unused.
                raise _invalid_otp()

            # Rotation: a session that was valid before login does not survive it.
            if current_session is not None:
                await db.execute(
                    update(SessionRow)
                    .where(SessionRow.id == current_session.session_id)
                    .values(revoked_at=now)
                )
            db.add(
                SessionRow(
                    id=session_id,
                    user_id=user_row.id,
                    session_digest=self._session_digest(token),
                    created_at=now,
                    last_seen_at=now,
                    expires_at=expires_at,
                    device_label=label,
                )
            )
            await self._audit(
                db,
                action="login_succeeded",
                user_id=user_row.id,
                resource=f"session:{session_id}",
                metadata={"ip_hash": self._ip_hash(ip)},
            )
            await alerts.record(
                db,
                user_id=user_row.id,
                kind="NEW_SIGN_IN",
                dedupe_key=f"sign-in:{session_id}",
                message=(
                    f"A new session started on {label}."
                    if label
                    else "A new session started on an unrecognised device."
                ),
                at=now,
                link=("session", str(session_id)),
            )
        info = SessionInfo(
            session_id=session_id,
            user_id=user_row.id,
            phone_e164=phone,
            display_name=user_row.display_name,
            user_created_at=user_row.created_at,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            device_label=label,
            totp_enabled=totp_enabled,
        )
        csrf = self.issue_token("session", str(session_id), expires_at)
        return info, token, csrf

    async def login_with_totp(
        self,
        *,
        request: Request,
        phone: str,
        code: str,
        current_session: SessionInfo | None,
    ) -> tuple[SessionInfo, str, str]:
        """Sign in with the phone number and a current authenticator code.

        Every failure is the same 401. Attempts are throttled per IP (all
        attempts) and per phone (failures only, so a successful login does not
        use up the allowance)."""
        s = self.settings
        stepup = self._stepup
        if stepup is None:
            raise _invalid_credentials()
        ip = self.client_ip(request)
        ip_key = hmac_hex(self.keys.identifier, "ip", ip)[:32]
        phone_key = hmac_hex(self.keys.identifier, "phone", phone)[:32]
        window = s.rate_limit_totp_window_seconds
        # The IP is counted first so a throttled caller cannot use up a phone's
        # allowance. The phone allowance is reserved before the code is looked
        # at (so concurrent requests cannot exceed it) and given back on success.
        retry = await self._limiter.hit("totp_login_ip", ip_key, s.rate_limit_totp_per_ip, window)
        if retry is None:
            retry = await self._limiter.hit(
                "totp_login_phone", phone_key, s.rate_limit_totp_per_user, window
            )
        if retry is not None:
            raise _rate_limited(retry)

        now = self.clock()
        token = secrets.token_urlsafe(32)
        session_id = uuid.uuid4()
        expires_at = now + timedelta(seconds=s.session_absolute_ttl_seconds)
        label = device_label_from_user_agent(request.headers.get("user-agent"))
        failed_user: uuid.UUID | None = None
        info: SessionInfo | None = None
        async with self._factory() as db, db.begin():
            row = (
                await db.execute(
                    select(User.id, User.status, User.display_name, User.created_at)
                    .join(Invite, Invite.phone_e164 == User.phone_e164)
                    .join(TotpCredential, TotpCredential.user_id == User.id)
                    .where(
                        User.phone_e164 == phone,
                        Invite.revoked_at.is_(None),
                        TotpCredential.confirmed_at.is_not(None),
                    )
                )
            ).first()
            outcome = "missing"
            if row is not None and row.status == "active":
                outcome = await stepup.consume_login_code(db, row.id, code, now)
            else:
                stepup.dummy_check(code, now)  # similar work for an unknown number
            if row is None or outcome != "ok":
                failed_user = row.id if row is not None else None
            else:
                step_up_until = min(now + timedelta(seconds=s.step_up_ttl_seconds), expires_at)
                await self._open_session(
                    db,
                    session_id=session_id,
                    token=token,
                    user_id=row.id,
                    now=now,
                    expires_at=expires_at,
                    label=label,
                    ip=ip,
                    current_session=current_session,
                    step_up_until=step_up_until,
                    method="totp",
                )
                info = SessionInfo(
                    session_id=session_id,
                    user_id=row.id,
                    phone_e164=phone,
                    display_name=row.display_name,
                    user_created_at=row.created_at,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=expires_at,
                    device_label=label,
                    totp_enabled=True,
                    step_up_until=step_up_until,
                )
        if info is not None:
            # Best effort: the login has committed, so a failed refund must not
            # turn it into an error (the code is spent and the old session is gone).
            try:
                await self._limiter.release("totp_login_phone", phone_key)
            except Exception:
                logger.warning("totp_login_phone_refund_failed")
        else:
            async with self._factory() as db, db.begin():
                await self._audit(
                    db,
                    action="login_failed",
                    user_id=failed_user,
                    resource=None,
                    metadata={"ip_hash": self._ip_hash(ip), "method": "totp"},
                )
            raise _invalid_credentials()
        csrf = self.issue_token("session", str(session_id), expires_at)
        return info, token, csrf

    async def _open_session(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        token: str,
        user_id: uuid.UUID,
        now: datetime,
        expires_at: datetime,
        label: str | None,
        ip: str,
        current_session: SessionInfo | None,
        step_up_until: datetime | None,
        method: str,
    ) -> None:
        """Inside the login transaction: rotate, insert the session, audit, alert."""
        # Rotation: a session that was valid before login does not survive it.
        if current_session is not None:
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == current_session.session_id)
                .values(revoked_at=now)
            )
        db.add(
            SessionRow(
                id=session_id,
                user_id=user_id,
                session_digest=self._session_digest(token),
                created_at=now,
                last_seen_at=now,
                expires_at=expires_at,
                device_label=label,
                step_up_until=step_up_until,
            )
        )
        await self._audit(
            db,
            action="login_succeeded",
            user_id=user_id,
            resource=f"session:{session_id}",
            metadata={"ip_hash": self._ip_hash(ip), "method": method},
        )
        await alerts.record(
            db,
            user_id=user_id,
            kind="NEW_SIGN_IN",
            dedupe_key=f"sign-in:{session_id}",
            message=(
                f"A new session started on {label}."
                if label
                else "A new session started on an unrecognised device."
            ),
            at=now,
            link=("session", str(session_id)),
        )

    # ---------------------------------------------------------------- sessions

    async def revoke_session(self, info: SessionInfo, *, request: Request) -> None:
        async with self._factory() as db, db.begin():
            await db.execute(
                update(SessionRow)
                .where(
                    SessionRow.id == info.session_id,
                    SessionRow.user_id == info.user_id,
                    SessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=self.clock())
            )
            await self._audit(
                db,
                action="logout",
                user_id=info.user_id,
                resource=f"session:{info.session_id}",
                metadata={"ip_hash": self._ip_hash(self.client_ip(request))},
            )

    async def revoke_all_sessions(self, info: SessionInfo, *, request: Request) -> int:
        async with self._factory() as db, db.begin():
            result = await db.execute(
                update(SessionRow)
                .where(SessionRow.user_id == info.user_id, SessionRow.revoked_at.is_(None))
                .values(revoked_at=self.clock())
                .returning(SessionRow.id)
            )
            count = len(result.all())
            await alerts.record(
                db,
                user_id=info.user_id,
                kind="SIGNED_OUT_EVERYWHERE",
                dedupe_key=f"signed-out-everywhere:{uuid.uuid4()}",
                message=f"Every session of this account was signed out ({count} revoked).",
                at=self.clock(),
            )
            await self._audit(
                db,
                action="logout_all",
                user_id=info.user_id,
                resource=f"user:{info.user_id}",
                metadata={
                    "revoked": count,
                    "ip_hash": self._ip_hash(self.client_ip(request)),
                },
            )
        return count

    async def get_profile(self, info: SessionInfo) -> tuple[str | None, str]:
        """The caller's display name and timezone."""
        async with self._factory() as db:
            row = (
                await db.execute(
                    select(User.display_name, User.timezone).where(User.id == info.user_id)
                )
            ).one()
        return row.display_name, row.timezone

    async def update_profile(
        self, info: SessionInfo, *, display_name: str, timezone: str
    ) -> tuple[str | None, str]:
        now = self.clock()
        async with self._factory() as db, db.begin():
            await db.execute(
                update(User)
                .where(User.id == info.user_id)
                .values(display_name=display_name, timezone=timezone, updated_at=now)
            )
            # The values are not logged: only that the profile changed.
            await self._audit(
                db,
                action="settings.profile_updated",
                user_id=info.user_id,
                resource=f"user:{info.user_id}",
                metadata={},
            )
        return display_name, timezone

    async def revoke_other_session(self, info: SessionInfo, session_id: uuid.UUID) -> None:
        """End one of the caller's other active sessions (the caller checked step-up)."""
        if session_id == info.session_id:
            raise ApiError(409, "CURRENT_SESSION", "Sign out to end this session.")
        now = self.clock()
        idle = timedelta(seconds=self.settings.session_idle_ttl_seconds)
        async with self._factory() as db, db.begin():
            revoked = await db.scalar(
                update(SessionRow)
                .where(
                    SessionRow.id == session_id,
                    SessionRow.user_id == info.user_id,  # tenant isolation
                    SessionRow.revoked_at.is_(None),
                    SessionRow.expires_at > now,
                    SessionRow.last_seen_at + idle > now,
                )
                .values(revoked_at=now)
                .returning(SessionRow.id)
            )
            if revoked is None:
                raise ApiError(404, "SESSION_NOT_FOUND", "This session was not found.")
            await self._audit(
                db,
                action="session.revoked",
                user_id=info.user_id,
                resource=f"session:{session_id}",
                metadata={},
            )

    async def list_sessions(self, info: SessionInfo) -> list[tuple[SessionRow, bool]]:
        now = self.clock()
        idle = timedelta(seconds=self.settings.session_idle_ttl_seconds)
        async with self._factory() as db:
            rows = (
                await db.scalars(
                    select(SessionRow)
                    .where(
                        SessionRow.user_id == info.user_id,  # tenant isolation
                        SessionRow.revoked_at.is_(None),
                        SessionRow.expires_at > now,
                        SessionRow.last_seen_at + idle > now,
                    )
                    .order_by(SessionRow.last_seen_at.desc())
                )
            ).all()
        return [(row, row.id == info.session_id) for row in rows]
