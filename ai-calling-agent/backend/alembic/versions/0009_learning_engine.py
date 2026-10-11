"""Bandit learning engine: variants the agent can try, and what they earned.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_variants",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("slot", sa.String(length=160), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trials", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successes", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("retired_reason", sa.String(length=200), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_agent_variants_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_variants_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_variants"),
    )
    for column in ("organization_id", "agent_id", "kind", "slot", "status"):
        op.create_index(f"ix_agent_variants_{column}", "agent_variants", [column])

    op.create_table(
        "variant_trials",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("call_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("variant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reward", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name="fk_variant_trials_call_id_calls",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["agent_variants.id"],
            name="fk_variant_trials_variant_id_agent_variants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_variant_trials"),
        sa.UniqueConstraint("call_id", "variant_id", name="uq_variant_trials_call"),
    )
    op.create_index("ix_variant_trials_call_id", "variant_trials", ["call_id"])
    op.create_index("ix_variant_trials_variant_id", "variant_trials", ["variant_id"])


def downgrade() -> None:
    op.drop_table("variant_trials")
    op.drop_table("agent_variants")
