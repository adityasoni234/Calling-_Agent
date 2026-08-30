from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The tenant boundary. Every tenant-owned row carries `organization_id`."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    # Drives campaign calling windows once Phase 7 lands.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Spend limits, checked before a call is placed. NULL falls back to the
    # deployment-wide value in settings; 0 means no cap.
    daily_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_concurrent_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)

    users: Mapped[list[User]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"
