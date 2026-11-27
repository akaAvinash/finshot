"""Record when a delivery was last attempted (for the email send caps).

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
    op.add_column(
        "alert_deliveries", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_alert_deliveries_last_attempt_at",
        "alert_deliveries",
        ["last_attempt_at"],
        postgresql_where=sa.text("last_attempt_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_last_attempt_at", table_name="alert_deliveries")
    op.drop_column("alert_deliveries", "last_attempt_at")
