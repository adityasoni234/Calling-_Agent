"""Record the destination country on each usage line.

Telephony rates vary by an order of magnitude between countries -- India is
about $0.05/min against the UK's $0.32 on the same account -- so a platform
dialling leads worldwide cannot price a call without knowing where it went.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("call_usage", sa.Column("region", sa.String(length=16), nullable=True))
    # Rate lookup filters on (component, provider, unit, region), so the index
    # covers the query the cost engine actually runs.
    op.create_index(
        "ix_pricing_rates_lookup",
        "pricing_rates",
        ["component", "provider", "unit", "region"],
    )


def downgrade() -> None:
    op.drop_index("ix_pricing_rates_lookup", table_name="pricing_rates")
    op.drop_column("call_usage", "region")
