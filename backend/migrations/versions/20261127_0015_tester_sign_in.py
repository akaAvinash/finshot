"""Invite-only tester sign-in (contracts/tester-sign-in.openapi.yaml).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-27

tester_identities: a dedicated user per tester (synthetic phone number),
kept apart from regular accounts. tester_invites: single-use codes stored as
a keyed digest, at most 15 minutes long (enforced by a check). sessions gains
`tester_invite_id`: a session created from an invite is bound to it, so
revoking the invite ends the session. Nothing is backfilled; the feature is
off by default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "tester_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tester_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_tester_identities")),
    )
    op.create_table(
        "tester_invites",
        sa.Column("id", sa.Uuid(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_tester_invites_expiry_after_issue")
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '15 minutes'",
            name=op.f("ck_tester_invites_expiry_within_15_minutes"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["tester_identities.user_id"],
            name=op.f("fk_tester_invites_user_id_tester_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tester_invites")),
        sa.UniqueConstraint("code_digest", name=op.f("uq_tester_invites_code_digest")),
    )
    op.create_index("ix_tester_invites_user_id", "tester_invites", ["user_id"])
    op.add_column("sessions", sa.Column("tester_invite_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sessions_tester_invite_id_tester_invites"),
        "sessions",
        "tester_invites",
        ["tester_invite_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Tester sessions have no meaning without their invites: they go with them.
    op.execute("DELETE FROM sessions WHERE tester_invite_id IS NOT NULL")
    # Tester accounts are separate users; without the table they could not be
    # told apart from regular ones, so they go too (audit rows keep, user_id NULL).
    op.execute("DELETE FROM users WHERE id IN (SELECT user_id FROM tester_identities)")
    op.drop_constraint(
        op.f("fk_sessions_tester_invite_id_tester_invites"), "sessions", type_="foreignkey"
    )
    op.drop_column("sessions", "tester_invite_id")
    op.drop_index("ix_tester_invites_user_id", table_name="tester_invites")
    op.drop_table("tester_invites")
    op.drop_table("tester_identities")
