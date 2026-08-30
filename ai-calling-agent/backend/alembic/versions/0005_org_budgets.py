"""Per-organization spend limits.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("daily_budget_usd", sa.Float(), nullable=True))
    op.add_column("organizations", sa.Column("monthly_budget_usd", sa.Float(), nullable=True))
    op.add_column("organizations", sa.Column("max_concurrent_calls", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "max_concurrent_calls")
    op.drop_column("organizations", "monthly_budget_usd")
    op.drop_column("organizations", "daily_budget_usd")
