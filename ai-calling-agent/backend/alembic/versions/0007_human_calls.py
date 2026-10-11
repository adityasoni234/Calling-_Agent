"""Human-operated calls: the platform bridges an operator to a lead.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("mode", sa.String(length=12), nullable=False, server_default="agent"),
    )
    op.add_column("calls", sa.Column("operator_number", sa.String(length=32), nullable=True))
    op.create_index("ix_calls_mode", "calls", ["mode"], unique=False)
    # A human call has no AI agent behind it.
    op.alter_column("calls", "agent_id", existing_type=sa.Uuid(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.alter_column("calls", "agent_id", existing_type=sa.Uuid(as_uuid=True), nullable=False)
    op.drop_index("ix_calls_mode", table_name="calls")
    op.drop_column("calls", "operator_number")
    op.drop_column("calls", "mode")
