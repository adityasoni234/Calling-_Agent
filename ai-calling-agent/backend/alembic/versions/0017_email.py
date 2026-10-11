"""Bulk email: addresses, validation verdicts, campaigns and suppression.

Email is modelled apart from SMS and WhatsApp because its failure modes
differ in kind. A phone number is reachable or it is not; an address can be
syntactically perfect, have working MX, and still end a sending reputation.
So a verdict carries the method that produced it and a confidence, never a
boolean.

Three rules live in the schema: a hard bounce suppresses permanently and no
campaign setting overrides it, an unsubscribe belongs to the address rather
than the list it arrived on, and every send records the verdict it was
authorised under.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_addresses",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "flags",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("bounce_count", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_email_addresses_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_addresses")),
        sa.UniqueConstraint("organization_id", "address", name="uq_email_address_org"),
    )
    op.create_index(
        "ix_email_address_verdict", "email_addresses", ["organization_id", "verdict"], unique=False
    )
    op.create_index(
        op.f("ix_email_addresses_address"), "email_addresses", ["address"], unique=False
    )
    op.create_index(op.f("ix_email_addresses_domain"), "email_addresses", ["domain"], unique=False)
    op.create_index(
        op.f("ix_email_addresses_organization_id"),
        "email_addresses",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "email_campaigns",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("preheader", sa.String(length=300), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("from_name", sa.String(length=120), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("lead_list_id", sa.Uuid(), nullable=True),
        sa.Column("include_risky", sa.Boolean(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emails_per_minute", sa.Integer(), nullable=False),
        sa.Column("total_recipients", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("risky_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.Column("unknown_count", sa.Integer(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("delivered_count", sa.Integer(), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False),
        sa.Column("clicked_count", sa.Integer(), nullable=False),
        sa.Column("bounced_count", sa.Integer(), nullable=False),
        sa.Column("complained_count", sa.Integer(), nullable=False),
        sa.Column("unsubscribed_count", sa.Integer(), nullable=False),
        sa.Column("estimated_charge_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("actual_charge_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("consent_confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["consent_confirmed_by_id"],
            ["users.id"],
            name=op.f("fk_email_campaigns_consent_confirmed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_email_campaigns_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_list_id"],
            ["lead_lists.id"],
            name=op.f("fk_email_campaigns_lead_list_id_lead_lists"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_email_campaigns_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_campaigns")),
    )
    op.create_index(
        op.f("ix_email_campaigns_organization_id"),
        "email_campaigns",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "email_messages",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("sent_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict_at_send", sa.String(length=16), nullable=True),
        sa.Column("provider", sa.String(length=48), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("provider_cost_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("customer_charge_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("price_rule_id", sa.Uuid(), nullable=True),
        sa.Column("cost_incomplete", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("unsubscribe_token", sa.String(length=64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
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
            ["campaign_id"],
            ["email_campaigns.id"],
            name=op.f("fk_email_messages_campaign_id_email_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_email_messages_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_email_messages_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["price_rule_id"],
            ["price_rules.id"],
            name=op.f("fk_email_messages_price_rule_id_price_rules"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sent_by_user_id"],
            ["users.id"],
            name=op.f("fk_email_messages_sent_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_messages")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_email_idempotency"),
    )
    op.create_index(
        "ix_email_message_org_time",
        "email_messages",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_message_provider", "email_messages", ["provider_message_id"], unique=False
    )
    op.create_index(
        op.f("ix_email_messages_campaign_id"), "email_messages", ["campaign_id"], unique=False
    )
    op.create_index(
        op.f("ix_email_messages_organization_id"),
        "email_messages",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_messages_to_address"), "email_messages", ["to_address"], unique=False
    )
    op.create_index(
        op.f("ix_email_messages_unsubscribe_token"),
        "email_messages",
        ["unsubscribe_token"],
        unique=False,
    )
    op.create_table(
        "email_suppressions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
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
            name=op.f("fk_email_suppressions_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["email_messages.id"],
            name=op.f("fk_email_suppressions_source_message_id_email_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_suppressions")),
        sa.UniqueConstraint("organization_id", "address", name="uq_email_suppression"),
    )
    op.create_index(
        "ix_email_suppression_lookup",
        "email_suppressions",
        ["organization_id", "address"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_suppressions_address"), "email_suppressions", ["address"], unique=False
    )
    op.create_index(
        op.f("ix_email_suppressions_organization_id"),
        "email_suppressions",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("email_suppressions")
    op.drop_table("email_messages")
    op.drop_table("email_campaigns")
    op.drop_table("email_addresses")
