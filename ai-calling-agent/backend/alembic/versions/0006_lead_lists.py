"""Named lead lists, so each uploaded sheet keeps its identity.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_lists",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_filename", sa.String(length=260), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_lead_lists_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lead_lists"),
        sa.UniqueConstraint("organization_id", "name", name="uq_lead_lists_org_name"),
    )
    op.create_index(
        "ix_lead_lists_organization_id", "lead_lists", ["organization_id"], unique=False
    )

    op.create_table(
        "lead_list_members",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("lead_list_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("lead_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["lead_list_id"],
            ["lead_lists.id"],
            name="fk_lead_list_members_lead_list_id_lead_lists",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name="fk_lead_list_members_lead_id_leads",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_lead_list_members"),
        sa.UniqueConstraint("lead_list_id", "lead_id", name="uq_lead_list_members_list_lead"),
    )
    op.create_index(
        "ix_lead_list_members_lead_list_id", "lead_list_members", ["lead_list_id"], unique=False
    )
    op.create_index("ix_lead_list_members_lead_id", "lead_list_members", ["lead_id"], unique=False)


def downgrade() -> None:
    op.drop_table("lead_list_members")
    op.drop_table("lead_lists")
