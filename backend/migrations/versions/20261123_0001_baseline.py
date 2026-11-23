"""Baseline: empty schema.

Establishes the migration history. Domain tables are added in later revisions
once their API contract is agreed.

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
