"""Provider connections, exchange rates and versioned price books.

Three things the platform could not do before:

* keep provider credentials outside `.env`, encrypted, rotatable by an admin
  without a deploy;
* record what a past conversion was done at, so an old charge stays
  explainable instead of being silently re-rated;
* version prices, so publishing a new rate does not rewrite what last
  month's calls cost.

Money columns are NUMERIC, not DOUBLE PRECISION. Floats cannot represent 0.1,
and a ledger that drifts by fractions of a cent is one nobody can reconcile.

Autogenerate was not used as-is: run against hand-written migrations it also
proposed dropping the pgvector index and rewriting three dozen unrelated
columns. Only the new tables are here.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exchange_rates")),
        sa.UniqueConstraint("currency", "effective_from", name="uq_fx_currency_from"),
    )
    op.create_index(
        op.f("ix_exchange_rates_currency"), "exchange_rates", ["currency"], unique=False
    )
    op.create_index(
        op.f("ix_exchange_rates_effective_from"), "exchange_rates", ["effective_from"], unique=False
    )
    op.create_index("ix_fx_lookup", "exchange_rates", ["currency", "effective_from"], unique=False)
    op.create_table(
        "price_books",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", sa.Uuid(), nullable=True),
        sa.Column("below_cost_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_price_books_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            name=op.f("fk_price_books_published_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_books")),
        sa.UniqueConstraint("slug", "version", name="uq_price_book_slug_version"),
    )
    op.create_index(
        "ix_price_book_active", "price_books", ["status", "effective_from"], unique=False
    )
    op.create_index(
        op.f("ix_price_books_organization_id"), "price_books", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_price_books_slug"), "price_books", ["slug"], unique=False)
    op.create_table(
        "price_overrides",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("billable", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=8), nullable=True),
        sa.Column("rate_kind", sa.String(length=16), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("minimum_charge", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_price_overrides_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_price_overrides_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_overrides")),
        sa.UniqueConstraint(
            "organization_id", "billable", "region", name="uq_price_override_scope"
        ),
    )
    op.create_index(
        op.f("ix_price_overrides_organization_id"),
        "price_overrides",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "provider_connections",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("secrets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_hints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secrets_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secrets_rotated_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_provider_connections_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["secrets_rotated_by_id"],
            ["users.id"],
            name=op.f("fk_provider_connections_secrets_rotated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint("slug", "organization_id", name="uq_provider_slug_org"),
    )
    op.create_index(
        op.f("ix_provider_connections_organization_id"),
        "provider_connections",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_connections_slug"), "provider_connections", ["slug"], unique=False
    )
    op.create_index(
        "ix_provider_kind_enabled", "provider_connections", ["kind", "is_enabled"], unique=False
    )
    op.create_table(
        "price_rules",
        sa.Column("price_book_id", sa.Uuid(), nullable=False),
        sa.Column("billable", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=8), nullable=True),
        sa.Column("rate_kind", sa.String(length=16), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("fixed_fee", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("minimum_charge", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("rounding", sa.String(length=24), nullable=False),
        sa.Column("increment_seconds", sa.Integer(), nullable=False),
        sa.Column("tiers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assumed_cost", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["price_book_id"],
            ["price_books.id"],
            name=op.f("fk_price_rules_price_book_id_price_books"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_rules")),
        sa.UniqueConstraint(
            "price_book_id", "billable", "region", name="uq_price_rule_billable_region"
        ),
    )
    op.create_index(op.f("ix_price_rules_billable"), "price_rules", ["billable"], unique=False)
    op.create_index(
        op.f("ix_price_rules_price_book_id"), "price_rules", ["price_book_id"], unique=False
    )
    op.create_table(
        "provider_balances",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("period_spend", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["provider_connections.id"],
            name=op.f("fk_provider_balances_connection_id_provider_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_balances")),
    )
    op.create_index(
        "ix_provider_balance_time",
        "provider_balances",
        ["connection_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_balances_connection_id"),
        "provider_balances",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_balances_observed_at"), "provider_balances", ["observed_at"], unique=False
    )
    op.create_table(
        "provider_sync_runs",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["provider_connections.id"],
            name=op.f("fk_provider_sync_runs_connection_id_provider_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_sync_runs")),
    )
    op.create_index(
        op.f("ix_provider_sync_runs_connection_id"),
        "provider_sync_runs",
        ["connection_id"],
        unique=False,
    )
    op.create_table(
        "provider_usage_records",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("is_parent", sa.Boolean(), nullable=False),
        sa.Column("parent_category", sa.String(length=120), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["provider_connections.id"],
            name=op.f("fk_provider_usage_records_connection_id_provider_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_usage_records")),
        sa.UniqueConstraint(
            "connection_id",
            "category",
            "period_start",
            "period_end",
            name="uq_provider_usage_period",
        ),
    )
    op.create_index(
        op.f("ix_provider_usage_records_category"),
        "provider_usage_records",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_usage_records_connection_id"),
        "provider_usage_records",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_provider_usage_records_period_start"),
        "provider_usage_records",
        ["period_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("provider_usage_records")
    op.drop_table("provider_sync_runs")
    op.drop_table("provider_balances")
    op.drop_table("price_rules")
    op.drop_table("provider_connections")
    op.drop_table("price_overrides")
    op.drop_table("price_books")
    op.drop_table("exchange_rates")
