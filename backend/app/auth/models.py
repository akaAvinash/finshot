"""Phase A tables: users, otp_challenges, sessions, audit_events.

Money, brokers, strategies, orders and the other kit tables are deferred to
their own phases. Every private record that belongs to a person carries
``user_id``; queries must filter on it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID_DEFAULT = text("gen_random_uuid()")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(r"phone_e164 ~ '^\+91[6-9][0-9]{9}$'", name="phone_format"),
        CheckConstraint("status IN ('active', 'disabled')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    phone_e164: Mapped[str] = mapped_column(String(16), unique=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_otp_challenges_phone_e164_created_at", "phone_e164", "created_at"),
        Index("ix_otp_challenges_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    phone_e164: Mapped[str] = mapped_column(String(16))
    # HMAC of (challenge id, code) under a key derived from AUTH_SECRET_KEY.
    # The code itself is never stored.
    code_digest: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # HMAC of the requester's IP, never the raw address.
    request_ip_hash: Mapped[str | None] = mapped_column(String(64))
    # Pre-login (or session) CSRF context that requested the code. Verification
    # must arrive in the same context.
    context_id: Mapped[str] = mapped_column(String(64))


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # HMAC of the session token. The token itself is never stored.
    session_digest: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_label: Mapped[str | None] = mapped_column(String(100))
    # End of the TOTP step-up window on this session; null when closed.
    step_up_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    # Kept (set to NULL) if the user is ever deleted, so history survives.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str | None] = mapped_column(String(128))
    # Never contains phone numbers, OTPs, tokens or raw IPs.
    metadata_redacted: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    """A phone number allowed to sign in. There is no sign-up and no admin role:
    the owner manages invites with `python -m app.auth.admin`. Revoking keeps
    the row (and ends access) so the history stays."""

    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("email IS NULL OR position('@' in email) > 1", name="email_shape"),
    )

    phone_e164: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TotpCredential(Base):
    """An authenticator secret, AES-GCM encrypted under a key derived from
    AUTH_SECRET_KEY. `confirmed_at` null means a pending enrolment that expires
    at `pending_expires_at`. `last_step` is the last accepted 30-second time
    step: a code is accepted once."""

    __tablename__ = "totp_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_step: Mapped[int] = mapped_column(BigInteger, server_default="0")
