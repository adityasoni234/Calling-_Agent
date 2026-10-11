"""Hold credits for a call in flight, instead of charging only afterwards.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("settled_amount", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_credit_reservations_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"],
            name="fk_credit_reservations_call_id_calls", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_reservations"),
        # One hold per call: a retried origination must not stack two.
        sa.UniqueConstraint("call_id", name="uq_credit_reservations_call"),
    )
    op.create_index(
        "ix_credit_reservations_organization_id", "credit_reservations", ["organization_id"]
    )
    op.create_index("ix_credit_reservations_call_id", "credit_reservations", ["call_id"])
    op.create_index("ix_credit_reservations_status", "credit_reservations", ["status"])


def downgrade() -> None:
    op.drop_table("credit_reservations")
