"""Who started each call, and how.

Calls could only be traced to an organization, so the question "which of your
team placed this" had no answer. Existing rows are backfilled from what can be
inferred -- campaign_id implies campaign dispatch, inbound direction implies an
inbound route -- and anything genuinely unknown is left as its default rather
than guessed at.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("initiated_by_user_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "calls",
        sa.Column("source", sa.String(length=12), nullable=False, server_default="manual"),
    )
    op.add_column("calls", sa.Column("source_detail", sa.String(length=200), nullable=True))
    op.add_column("calls", sa.Column("agent_version", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_calls_initiated_by_user_id_users",
        "calls",
        "users",
        ["initiated_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_calls_initiated_by_user_id", "calls", ["initiated_by_user_id"])
    op.create_index("ix_calls_source", "calls", ["source"])

    # Backfill only what the data actually proves.
    op.execute("UPDATE calls SET source = 'campaign' WHERE campaign_id IS NOT NULL")
    op.execute("UPDATE calls SET source = 'inbound' WHERE direction = 'inbound'")
    op.execute(
        "UPDATE calls SET source_detail = 'backfilled: origin not recorded at the time' "
        "WHERE source_detail IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_calls_source", table_name="calls")
    op.drop_index("ix_calls_initiated_by_user_id", table_name="calls")
    op.drop_constraint("fk_calls_initiated_by_user_id_users", "calls", type_="foreignkey")
    for column in ("agent_version", "source_detail", "source", "initiated_by_user_id"):
        op.drop_column("calls", column)
