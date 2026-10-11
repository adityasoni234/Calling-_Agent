from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.refresh_token import RefreshToken


class UserRole(enum.StrEnum):
    """Roles exist from day one so RBAC is an enforcement change, not a schema one."""

    #: Owns the account: billing, team, everything below.
    OWNER = "owner"
    #: Runs the product day to day, including agents and integrations.
    ADMIN = "admin"
    #: Money without the product: invoices, refunds, credits, no call content.
    FINANCE_ADMIN = "finance_admin"
    #: Helps customers: reads conversations and call content, changes nothing
    #: commercial. The widest read access and the narrowest write access,
    #: which is deliberately the opposite shape to finance.
    SUPPORT_ADMIN = "support_admin"
    #: Keeps the pipes running: providers and settings, no customer money.
    OPERATIONS_ADMIN = "operations_admin"
    #: Does the outreach.
    OPERATOR = "operator"
    #: Reads dashboards.
    VIEWER = "viewer"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=UserRole.OWNER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Platform staff, not a customer. Can see and administer every organization,
    #: which is why it is a separate flag rather than another UserRole value --
    #: no customer self-service path can ever set it.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="users", lazy="joined")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
