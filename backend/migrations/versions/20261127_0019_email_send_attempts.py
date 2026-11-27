"""Timestamped real-email send attempts (for the mailbox daily and per-user hourly caps).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_send_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_email_send_attempts_at", "email_send_attempts", ["at"])
    op.create_index("ix_email_send_attempts_user_id_at", "email_send_attempts", ["user_id", "at"])


def downgrade() -> None:
    op.drop_table("email_send_attempts")
