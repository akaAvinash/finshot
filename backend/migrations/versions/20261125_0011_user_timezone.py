"""Profile timezone.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-25

users.timezone: the caller's display timezone, `Asia/Kolkata` or `UTC`.
Existing users get `Asia/Kolkata`, the value the contract reports for a user
who never saved a profile.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=32), server_default="Asia/Kolkata", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_users_timezone_valid"), "users", "timezone IN ('Asia/Kolkata', 'UTC')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_timezone_valid"), "users", type_="check")
    op.drop_column("users", "timezone")
