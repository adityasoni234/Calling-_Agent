"""Meta lead-ad connections, selected assets and lead events.

Tokens are the security story. A Meta user token reads a business's ad data
and can post as their Page, so it is stored as Fernet ciphertext alongside
only a masked tail and an expiry -- enough to show a status and prompt a
reconnect without ever handing the value to a browser.

Meta's own tree is mirrored rather than flattened, because a lead's value is
largely which form, ad and campaign produced it. Lead events are written
before they are processed, and the leadgen id is unique: Meta re-delivers,
and a duplicate must not become a second lead.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meta_connections",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("meta_user_id", sa.String(length=64), nullable=False),
        sa.Column("meta_user_name", sa.String(length=200), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("token_hint", sa.String(length=32), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scopes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_lead_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leads_received", sa.Integer(), nullable=False),
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
            ["connected_by_user_id"],
            ["users.id"],
            name=op.f("fk_meta_connections_connected_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_meta_connections_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meta_connections")),
        sa.UniqueConstraint("organization_id", "meta_user_id", name="uq_meta_connection"),
    )
    op.create_index(
        op.f("ix_meta_connections_meta_user_id"), "meta_connections", ["meta_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_meta_connections_organization_id"),
        "meta_connections",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "meta_assets",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("meta_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("parent_meta_id", sa.String(length=64), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("is_subscribed", sa.Boolean(), nullable=False),
        sa.Column("page_token", sa.Text(), nullable=True),
        sa.Column(
            "raw",
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
            ["connection_id"],
            ["meta_connections.id"],
            name=op.f("fk_meta_assets_connection_id_meta_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_meta_assets_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meta_assets")),
        sa.UniqueConstraint("connection_id", "meta_id", name="uq_meta_asset"),
    )
    op.create_index("ix_meta_asset_kind", "meta_assets", ["organization_id", "kind"], unique=False)
    op.create_index(
        op.f("ix_meta_assets_connection_id"), "meta_assets", ["connection_id"], unique=False
    )
    op.create_index(op.f("ix_meta_assets_meta_id"), "meta_assets", ["meta_id"], unique=False)
    op.create_index(
        op.f("ix_meta_assets_organization_id"), "meta_assets", ["organization_id"], unique=False
    )
    op.create_table(
        "meta_lead_events",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("leadgen_id", sa.String(length=64), nullable=False),
        sa.Column("form_id", sa.String(length=64), nullable=True),
        sa.Column("page_id", sa.String(length=64), nullable=True),
        sa.Column("ad_id", sa.String(length=64), nullable=True),
        sa.Column("adset_id", sa.String(length=64), nullable=True),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "raw",
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
            ["connection_id"],
            ["meta_connections.id"],
            name=op.f("fk_meta_lead_events_connection_id_meta_connections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_meta_lead_events_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_meta_lead_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meta_lead_events")),
        sa.UniqueConstraint("leadgen_id", name="uq_meta_leadgen"),
    )
    op.create_index(
        "ix_meta_lead_event_org",
        "meta_lead_events",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_meta_lead_events_form_id"), "meta_lead_events", ["form_id"], unique=False
    )
    op.create_index(
        op.f("ix_meta_lead_events_leadgen_id"), "meta_lead_events", ["leadgen_id"], unique=False
    )
    op.create_index(
        op.f("ix_meta_lead_events_organization_id"),
        "meta_lead_events",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("meta_lead_events")
    op.drop_table("meta_assets")
    op.drop_table("meta_connections")
