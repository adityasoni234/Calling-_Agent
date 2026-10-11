"""Customer-owned mailboxes connected by OAuth.

Email sending moves from one platform sender to each customer's own Gmail
or Outlook account. It costs the platform nothing, mail arrives from a
domain the recipient recognises rather than a shared IP, and nobody is
asked to paste a credential -- consent happens in Google's or Microsoft's
own dialog.

Refresh tokens are the asset worth guarding: one can send mail as that
person indefinitely, so they are stored as Fernet ciphertext and deleted
rather than deactivated on disconnect.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scopes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("sent_today", sa.Integer(), nullable=False),
        sa.Column("quota_reset_at", sa.DateTime(timezone=True), nullable=True),
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
            ["connected_by_user_id"],
            ["users.id"],
            name=op.f("fk_email_accounts_connected_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_email_accounts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_accounts")),
        sa.UniqueConstraint("organization_id", "address", name="uq_email_account"),
    )
    op.create_index(op.f("ix_email_accounts_address"), "email_accounts", ["address"], unique=False)
    op.create_index(
        op.f("ix_email_accounts_organization_id"),
        "email_accounts",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("email_accounts")
