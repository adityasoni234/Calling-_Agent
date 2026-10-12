"""Platform staff sessions against customer accounts.

A session is a row rather than only a signed claim, so that ending one takes
effect at once instead of whenever the token happens to expire. The handoff
code is stored as a digest and marked used on first exchange, which is what
makes it single-use.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impersonation_sessions",
        sa.Column("admin_user_id", sa.Uuid(), nullable=True),
        sa.Column("admin_email", sa.String(length=320), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_email", sa.String(length=320), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("organization_name", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=16), nullable=True),
        sa.Column("handoff_digest", sa.String(length=64), nullable=True),
        sa.Column("handoff_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handoff_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_ip", sa.String(length=64), nullable=True),
        sa.Column("started_user_agent", sa.String(length=400), nullable=True),
        sa.Column("writes_performed", sa.Integer(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False),
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
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_impersonation_sessions_admin_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_impersonation_sessions_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_impersonation_sessions_target_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impersonation_sessions")),
    )
    op.create_index(
        op.f("ix_impersonation_sessions_admin_user_id"),
        "impersonation_sessions",
        ["admin_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_impersonation_sessions_target_user_id"),
        "impersonation_sessions",
        ["target_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_impersonation_sessions_expires_at"),
        "impersonation_sessions",
        ["expires_at"],
        unique=False,
    )
    # The exchange looks a session up by digest alone, on a table that only
    # ever grows, so this index is the difference between a constant-time
    # lookup and a scan of every visit staff have ever made.
    op.create_index(
        op.f("ix_impersonation_sessions_handoff_digest"),
        "impersonation_sessions",
        ["handoff_digest"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("impersonation_sessions")
