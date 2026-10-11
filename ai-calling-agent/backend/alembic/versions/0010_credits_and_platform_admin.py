"""Credits, plans, suspension and a platform-admin audit trail.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("plan", sa.String(length=16), nullable=False, server_default="trial"),
    )
    op.add_column(
        "organizations",
        sa.Column("credit_balance", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "organizations",
        sa.Column("credit_overdraft", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "organizations", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("suspended_reason", sa.String(length=300), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "credit_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=False),
        sa.Column("call_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("provider_cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_credit_entries_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name="fk_credit_entries_call_id_calls",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_credit_entries_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_entries"),
    )
    op.create_index("ix_credit_entries_organization_id", "credit_entries", ["organization_id"])
    op.create_index("ix_credit_entries_kind", "credit_entries", ["kind"])
    op.create_index("ix_credit_entries_call_id", "credit_entries", ["call_id"])

    op.create_table(
        "platform_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_platform_events_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_platform_events_organization_id_organizations",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_events"),
    )
    op.create_index("ix_platform_events_actor_user_id", "platform_events", ["actor_user_id"])
    op.create_index("ix_platform_events_action", "platform_events", ["action"])


def downgrade() -> None:
    op.drop_table("platform_events")
    op.drop_table("credit_entries")
    op.drop_column("users", "is_platform_admin")
    for column in (
        "suspended_reason",
        "suspended_at",
        "credit_overdraft",
        "credit_balance",
        "plan",
    ):
        op.drop_column("organizations", column)
