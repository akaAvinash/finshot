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
from app.auth.models import AuditEvent, OtpChallenge, User
from app.auth.models import Session as SessionRow
from app.auth.otp import OtpDeliveryError, OtpProvider
from app.auth.ratelimit import RateLimiter
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


def _unauthenticated() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")


def _invalid_otp() -> ApiError:
    return ApiError(401, "INVALID_OTP", "The code is invalid or has expired.")


def _csrf_failed() -> ApiError:
    return ApiError(403, "CSRF_FAILED", "The request could not be verified. Reload and try again.")


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
    ) -> None:
        self.settings = settings
        self._factory = session_factory
        self._limiter = limiter
        self._provider = provider
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
                    select(SessionRow, User)
                    .join(User, User.id == SessionRow.user_id)
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
            sess, user = row
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
        code = self._provider.new_code()
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
                metadata={"ip_hash": self._ip_hash(ip)},
            )
        try:
            await self._provider.deliver(phone, code)
        except OtpDeliveryError as exc:
            logger.warning("otp_delivery_failed", reason=str(exc))
            async with self._factory() as db, db.begin():
                await db.execute(delete(OtpChallenge).where(OtpChallenge.id == challenge_id))
            raise ApiError(
                503,
                "OTP_DELIVERY_UNAVAILABLE",
                "We could not send a code right now. Try again shortly.",
            ) from exc
        resend_at = now + timedelta(seconds=s.otp_resend_cooldown_seconds)
        return challenge_id, expires_at, resend_at

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
        )
        csrf = self.issue_token("session", str(session_id), expires_at)
        return info, token, csrf

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
