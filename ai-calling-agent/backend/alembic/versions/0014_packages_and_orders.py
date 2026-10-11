"""Credit packages, orders with snapshotted terms, and payment events.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_packages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="one_time"),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("tax_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_credits", sa.Integer(), nullable=False),
        sa.Column("bonus_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_per_organization", sa.Integer(), nullable=True),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_credit_packages"),
        sa.UniqueConstraint("slug", name="uq_credit_packages_slug"),
    )
    op.create_index("ix_credit_packages_slug", "credit_packages", ["slug"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("package_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reference", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("package_name", sa.String(length=120), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("tax_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("base_credits", sa.Integer(), nullable=False),
        sa.Column("bonus_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_credits", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_order_id", sa.String(length=120), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=120), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=300), nullable=True),
        sa.Column("credits_allocated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_orders_organization_id_organizations", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_orders_created_by_user_id_users", ondelete="SET NULL",
        ),
        # RESTRICT: a package referenced by a real order must never be deleted.
        sa.ForeignKeyConstraint(
            ["package_id"], ["credit_packages.id"],
            name="fk_orders_package_id_credit_packages", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("provider_order_id", name="uq_orders_provider_order_id"),
    )
    for column in ("organization_id", "reference", "status", "provider_order_id",
                   "provider_payment_id"):
        op.create_index(f"ix_orders_{column}", "orders", [column])

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_payment_events_order_id_orders",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_events"),
        # Replay protection as a database guarantee, not a code path.
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_events_provider_event"),
    )
    op.create_index("ix_payment_events_provider", "payment_events", ["provider"])
    op.create_index("ix_payment_events_event_id", "payment_events", ["event_id"])
    op.create_index("ix_payment_events_order_id", "payment_events", ["order_id"])

    # Link credit entries to the order that produced them, so a payment can be
    # traced all the way to the credits it granted.
    op.add_column("credit_entries", sa.Column("order_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_credit_entries_order_id_orders", "credit_entries", "orders",
        ["order_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_credit_entries_order_id", "credit_entries", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_credit_entries_order_id", table_name="credit_entries")
    op.drop_constraint("fk_credit_entries_order_id_orders", "credit_entries", type_="foreignkey")
    op.drop_column("credit_entries", "order_id")
    op.drop_table("payment_events")
    op.drop_table("orders")
    op.drop_table("credit_packages")
