"""SMS and WhatsApp: messages, conversations, templates, consent.

Modelled apart from calls rather than as a Call with a flag: a message has no
duration, arrives in a thread, can be inbound without ringing anything, and on
WhatsApp may require a pre-approved template. Sharing a table would have meant
a column that is null for one kind on nearly every row.

Four invariants live in the schema rather than in whoever remembers them: a
suppression row blocks a send, consent is a dated record and not a boolean,
idempotency keys are unique per tenant so a retried campaign cannot
double-send, and money is NUMERIC.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consent_records",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("contact_number", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=True),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
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
            name=op.f("fk_consent_records_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_records")),
    )
    op.create_index(
        "ix_consent_lookup", "consent_records", ["organization_id", "contact_number"], unique=False
    )
    op.create_index(
        op.f("ix_consent_records_contact_number"),
        "consent_records",
        ["contact_number"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_records_organization_id"),
        "consent_records",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "message_templates",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "variables",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("provider_template_id", sa.String(length=120), nullable=True),
        sa.Column("provider_synced_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_message_templates_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_templates")),
        sa.UniqueConstraint("organization_id", "name", "channel", name="uq_template_name"),
    )
    op.create_index(
        op.f("ix_message_templates_organization_id"),
        "message_templates",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "conversations",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("contact_number", sa.String(length=32), nullable=False),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unread_count", sa.Integer(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
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
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_conversations_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_conversations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint(
            "organization_id", "channel", "contact_number", name="uq_conversation_scope"
        ),
    )
    op.create_index(
        "ix_conversation_recent",
        "conversations",
        ["organization_id", "last_message_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversations_contact_number"), "conversations", ["contact_number"], unique=False
    )
    op.create_index(op.f("ix_conversations_lead_id"), "conversations", ["lead_id"], unique=False)
    op.create_index(
        op.f("ix_conversations_organization_id"), "conversations", ["organization_id"], unique=False
    )
    op.create_table(
        "message_campaigns",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("from_number", sa.String(length=32), nullable=True),
        sa.Column("lead_list_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("messages_per_minute", sa.Integer(), nullable=False),
        sa.Column("total_recipients", sa.Integer(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("delivered_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("estimated_charge_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("actual_charge_usd", sa.Numeric(precision=18, scale=6), nullable=True),
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
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_message_campaigns_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_list_id"],
            ["lead_lists.id"],
            name=op.f("fk_message_campaigns_lead_list_id_lead_lists"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_message_campaigns_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["message_templates.id"],
            name=op.f("fk_message_campaigns_template_id_message_templates"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_campaigns")),
    )
    op.create_index(
        op.f("ix_message_campaigns_organization_id"),
        "message_campaigns",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("sent_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("from_number", sa.String(length=32), nullable=False),
        sa.Column("to_number", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "media_urls",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column(
            "template_variables",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("segments", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=8), nullable=True),
        sa.Column("provider", sa.String(length=48), nullable=True),
        sa.Column("provider_message_id", sa.String(length=120), nullable=True),
        sa.Column("provider_status", sa.String(length=48), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("provider_cost", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("provider_currency", sa.String(length=8), nullable=True),
        sa.Column("provider_cost_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("customer_charge_usd", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("price_rule_id", sa.Uuid(), nullable=True),
        sa.Column("credits_charged", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("cost_incomplete", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("suppression_reason", sa.String(length=48), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
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
            ["message_campaigns.id"],
            name=op.f("fk_messages_campaign_id_message_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_messages_lead_id_leads"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_messages_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["price_rule_id"],
            ["price_rules.id"],
            name=op.f("fk_messages_price_rule_id_price_rules"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sent_by_user_id"],
            ["users.id"],
            name=op.f("fk_messages_sent_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["message_templates.id"],
            name=op.f("fk_messages_template_id_message_templates"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_message_idempotency"),
    )
    op.create_index(
        "ix_message_org_time", "messages", ["organization_id", "created_at"], unique=False
    )
    op.create_index("ix_message_provider_sid", "messages", ["provider_message_id"], unique=False)
    op.create_index("ix_message_status", "messages", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_messages_campaign_id"), "messages", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_messages_channel"), "messages", ["channel"], unique=False)
    op.create_index(
        op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False
    )
    op.create_index(
        op.f("ix_messages_organization_id"), "messages", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_messages_to_number"), "messages", ["to_number"], unique=False)
    op.create_table(
        "suppressions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("contact_number", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=True),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
            name=op.f("fk_suppressions_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["messages.id"],
            name=op.f("fk_suppressions_source_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppressions")),
        sa.UniqueConstraint(
            "organization_id", "contact_number", "channel", name="uq_suppression_scope"
        ),
    )
    op.create_index(
        "ix_suppression_lookup", "suppressions", ["organization_id", "contact_number"], unique=False
    )
    op.create_index(
        op.f("ix_suppressions_contact_number"), "suppressions", ["contact_number"], unique=False
    )
    op.create_index(
        op.f("ix_suppressions_organization_id"), "suppressions", ["organization_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("suppressions")
    op.drop_table("messages")
    op.drop_table("message_campaigns")
    op.drop_table("conversations")
    op.drop_table("message_templates")
    op.drop_table("consent_records")
