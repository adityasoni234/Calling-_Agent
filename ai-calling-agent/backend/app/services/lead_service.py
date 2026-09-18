"""Leads: creation, CSV import, search."""

from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.lead import Lead, LeadStatus
from app.models.lead_list import LeadList, LeadListMember, LeadListSource

_DIGITS = re.compile(r"[^\d+]")
# Column names people actually use in exported CRM files.
CSV_ALIASES = {
    "name": {"name", "full_name", "customer", "customer_name", "contact", "contact_name"},
    "phone_number": {"phone", "phone_number", "mobile", "number", "contact_number", "msisdn"},
    "email": {"email", "email_address", "mail"},
    "company_name": {"company", "company_name", "organisation", "organization", "business"},
    "notes": {"notes", "note", "comment", "remarks"},
}


def normalize_phone(raw: str, default_country_code: str = "+91") -> str:
    """Best-effort E.164. Ambiguous input is kept rather than mangled."""
    cleaned = _DIGITS.sub("", (raw or "").strip())
    if not cleaned:
        return ""
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]
    if len(cleaned) == 10:
        return f"{default_country_code}{cleaned}"
    if len(cleaned) > 10 and cleaned.startswith(default_country_code.lstrip("+")):
        return f"+{cleaned}"
    return f"+{cleaned}"


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, organization_id: uuid.UUID, data: dict[str, Any]) -> Lead:
        phone = normalize_phone(str(data.get("phone_number", "")))
        existing = await self.db.execute(
            select(Lead).where(Lead.organization_id == organization_id, Lead.phone_number == phone)
        )
        if existing.scalars().first():
            raise ConflictError(
                "A lead with this phone number already exists", code="duplicate_lead"
            )

        lead = Lead(organization_id=organization_id, **{**data, "phone_number": phone})
        self.db.add(lead)
        await self.db.commit()
        await self.db.refresh(lead)
        return lead

    async def unique_list_name(self, organization_id: uuid.UUID, wanted: str) -> str:
        """Names are unique per organization, so re-uploading gets a suffix.

        Silently merging a second "leads.csv" into the first would hide rows
        the user expects to see as their own tab.
        """
        base = (wanted or "Untitled list").strip()[:150] or "Untitled list"
        taken = set(
            (
                await self.db.execute(
                    select(LeadList.name).where(LeadList.organization_id == organization_id)
                )
            ).scalars()
        )
        if base not in taken:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base} ({suffix})"
            if candidate not in taken:
                return candidate
        return f"{base} ({uuid.uuid4().hex[:6]})"

    async def import_csv(
        self,
        organization_id: uuid.UUID,
        content: bytes,
        *,
        default_country_code: str = "+91",
        list_name: str | None = None,
        source_filename: str | None = None,
    ) -> dict[str, Any]:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))

        header_map: dict[str, str] = {}
        for column in reader.fieldnames or []:
            key = column.strip().lower().replace(" ", "_")
            for field, aliases in CSV_ALIASES.items():
                if key in aliases:
                    header_map[column] = field

        if "phone_number" not in header_map.values():
            return {
                "imported": 0,
                "skipped": 0,
                "errors": ["No phone number column found"],
                "phone_numbers": [],
                "lead_list": None,
            }

        existing = await self.db.execute(
            select(Lead.phone_number).where(Lead.organization_id == organization_id)
        )
        seen = set(existing.scalars())

        imported = 0
        skipped = 0
        errors: list[str] = []
        # Every valid number in the file, new or already known. A campaign
        # import needs these: a duplicate is still someone you want called.
        phone_numbers: list[str] = []

        for line_number, row in enumerate(reader, start=2):
            values = {
                field: (row.get(column) or "").strip() for column, field in header_map.items()
            }
            phone = normalize_phone(values.get("phone_number", ""), default_country_code)
            if not phone or len(phone) < 8:
                skipped += 1
                if len(errors) < 20:
                    errors.append(f"Row {line_number}: missing or invalid phone number")
                continue
            if phone in seen:
                skipped += 1
                phone_numbers.append(phone)
                continue

            seen.add(phone)
            phone_numbers.append(phone)
            self.db.add(
                Lead(
                    organization_id=organization_id,
                    name=values.get("name") or "Unknown",
                    phone_number=phone,
                    email=values.get("email") or None,
                    company_name=values.get("company_name") or None,
                    notes=values.get("notes") or None,
                    status=LeadStatus.NEW,
                )
            )
            imported += 1

        await self.db.commit()

        lead_list = None
        if list_name and phone_numbers:
            lead_list = LeadList(
                organization_id=organization_id,
                name=await self.unique_list_name(organization_id, list_name),
                source=LeadListSource.CSV_IMPORT,
                source_filename=source_filename,
                imported_count=imported,
                skipped_count=skipped,
            )
            self.db.add(lead_list)
            await self.db.flush()
            await self.add_to_list(lead_list, phone_numbers, organization_id)
            await self.db.commit()
            await self.db.refresh(lead_list)

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "phone_numbers": phone_numbers,
            "lead_list": lead_list,
        }

    async def add_to_list(
        self, lead_list: LeadList, phone_numbers: list[str], organization_id: uuid.UUID
    ) -> int:
        """File every number from the upload under this list.

        Numbers already on file join the list too -- a duplicate row still
        means "this person is on that sheet".
        """
        if not phone_numbers:
            return 0
        lead_ids = list(
            (
                await self.db.execute(
                    select(Lead.id).where(
                        Lead.organization_id == organization_id,
                        Lead.phone_number.in_(phone_numbers),
                    )
                )
            ).scalars()
        )
        already = set(
            (
                await self.db.execute(
                    select(LeadListMember.lead_id).where(
                        LeadListMember.lead_list_id == lead_list.id
                    )
                )
            ).scalars()
        )
        added = 0
        for lead_id in lead_ids:
            if lead_id in already:
                continue
            self.db.add(LeadListMember(lead_list_id=lead_list.id, lead_id=lead_id))
            added += 1
        return added

    def search_filter(self, query: str):  # noqa: ANN201 - SQLAlchemy clause
        pattern = f"%{query.lower()}%"
        return or_(
            func.lower(Lead.name).like(pattern),
            Lead.phone_number.like(pattern),
            func.lower(func.coalesce(Lead.email, "")).like(pattern),
            func.lower(func.coalesce(Lead.company_name, "")).like(pattern),
        )
