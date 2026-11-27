"""Phone number change challenges (contract 0.13.0, requestPhoneChange).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-27

One row per requested change. The code is stored only as a keyed digest; a
row is bound to the requesting session and account and is removed with them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phone_change_challenges",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("new_phone_e164", sa.String(16), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("suppressed", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_phone_change_challenges_attempts_non_negative")
        ),
        sa.CheckConstraint(
            r"new_phone_e164 ~ '^\+91[6-9][0-9]{9}$'",
            name=op.f("ck_phone_change_challenges_phone_format"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_phone_change_challenges_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_phone_change_challenges_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_change_challenges")),
    )
    op.create_index(
        op.f("ix_phone_change_challenges_user_id"), "phone_change_challenges", ["user_id"]
    )
    op.create_index(
        op.f("ix_phone_change_challenges_expires_at"), "phone_change_challenges", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("phone_change_challenges")
