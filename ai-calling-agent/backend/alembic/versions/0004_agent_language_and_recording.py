"""Language preference and call recording on agents.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "ask_language_preference", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "agents",
        sa.Column("record_calls", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("agents", "record_calls")
    op.drop_column("agents", "ask_language_preference")
