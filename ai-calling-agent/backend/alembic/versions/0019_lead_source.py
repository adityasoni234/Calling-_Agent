"""Lead source attribution.

Where a lead came from was being kept in the `extra` JSON blob, which
cannot be filtered or grouped cheaply -- and "which campaign actually
converts" is the question a pipeline exists to answer. Meta lead ads make
it concrete: a lead is worth knowing the form, ad and campaign for.

Existing rows are backfilled to "manual", which is what they were.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("source", sa.String(length=64), nullable=False, server_default="manual"),
    )
    op.add_column("leads", sa.Column("source_detail", sa.String(length=200), nullable=True))
    op.create_index("ix_leads_source", "leads", ["source"])


def downgrade() -> None:
    op.drop_index("ix_leads_source", table_name="leads")
    op.drop_column("leads", "source_detail")
    op.drop_column("leads", "source")
