"""Named batches of leads -- one per uploaded sheet.

A CSV upload is how most lists arrive, and people think of them by the file
they came from ("the Diwali list", "aditya 50.csv"). Keeping that grouping lets
the dashboard show each upload as its own tab instead of one undifferentiated
pile of contacts.

Membership is many-to-many on purpose: the same phone number can appear in
several uploads, and it should show under each of them rather than being
claimed by whichever file happened to arrive first.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import StrEnumType


class LeadListSource(enum.StrEnum):
    CSV_IMPORT = "csv_import"
    MANUAL = "manual"


class LeadList(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lead_lists"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_lead_lists_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    #: What the user sees on the tab. Defaults to the uploaded file's name.
    name: Mapped[str] = mapped_column(String(160))
    source: Mapped[LeadListSource] = mapped_column(
        StrEnumType(LeadListSource, 16), default=LeadListSource.CSV_IMPORT
    )
    #: The original filename, kept even if the list is renamed later.
    source_filename: Mapped[str | None] = mapped_column(String(260), nullable=True)
    #: Counts from the import that created it, so the upload can be explained
    #: after the fact without recounting rows.
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)


class LeadListMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lead_list_members"
    __table_args__ = (
        UniqueConstraint("lead_list_id", "lead_id", name="uq_lead_list_members_list_lead"),
    )

    lead_list_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("lead_lists.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
