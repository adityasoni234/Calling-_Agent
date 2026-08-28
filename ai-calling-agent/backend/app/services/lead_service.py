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

    async def import_csv(
        self, organization_id: uuid.UUID, content: bytes, *, default_country_code: str = "+91"
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
            return {"imported": 0, "skipped": 0, "errors": ["No phone number column found"]}

        existing = await self.db.execute(
            select(Lead.phone_number).where(Lead.organization_id == organization_id)
        )
        seen = set(existing.scalars())

        imported = 0
        skipped = 0
        errors: list[str] = []

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
                continue

            seen.add(phone)
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
        return {"imported": imported, "skipped": skipped, "errors": errors}

    def search_filter(self, query: str):  # noqa: ANN201 - SQLAlchemy clause
        pattern = f"%{query.lower()}%"
        return or_(
            func.lower(Lead.name).like(pattern),
            Lead.phone_number.like(pattern),
            func.lower(func.coalesce(Lead.email, "")).like(pattern),
            func.lower(func.coalesce(Lead.company_name, "")).like(pattern),
        )
