"""Invite-only sign-in, TOTP credentials and the step-up window.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25

invites: a phone number allowed to sign in. Backfill: every existing user is
invited (their phone), so nobody is locked out by this migration.
totp_credentials: one row per user (encrypted secret, pending or confirmed).
sessions.step_up_until: end of the step-up window; null on every existing
session, so none starts stepped up.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "email IS NULL OR position('@' in email) > 1", name=op.f("ck_invites_email_shape")
        ),
        sa.PrimaryKeyConstraint("phone_e164", name=op.f("pk_invites")),
    )
    op.execute(
        "INSERT INTO invites (phone_e164, created_at) SELECT phone_e164, created_at FROM users"
    )
    op.create_table(
        "totp_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_step", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_totp_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_totp_credentials")),
    )
    op.add_column("sessions", sa.Column("step_up_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "step_up_until")
    op.drop_table("totp_credentials")
    op.drop_table("invites")
