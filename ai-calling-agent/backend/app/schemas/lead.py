from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.lead import InterestLevel, LeadStatus
from app.services.lead_service import normalize_phone


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone_number: str = Field(min_length=6, max_length=32)
    email: EmailStr | None = None
    company_name: str | None = Field(default=None, max_length=200)
    status: LeadStatus = LeadStatus.NEW
    interest_level: InterestLevel = InterestLevel.UNKNOWN
    lead_score: int = Field(default=0, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("phone_number")
    @classmethod
    def _normalize(cls, value: str) -> str:
        normalized = normalize_phone(value)
        if len(normalized) < 8:
            raise ValueError("Phone number looks too short to dial")
        return normalized


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    company_name: str | None = None
    status: LeadStatus | None = None
    interest_level: InterestLevel | None = None
    lead_score: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=4000)
    follow_up_at: datetime | None = None


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    phone_number: str
    email: str | None
    company_name: str | None
    #: Where the lead came from -- csv, manual, api, or meta:<form id>.
    #: Shown in the table because "which source converts" is the question
    #: the pipeline exists to answer.
    source: str = "manual"
    source_detail: str | None = None
    status: LeadStatus
    interest_level: InterestLevel
    lead_score: int
    notes: str | None
    call_count: int
    last_called_at: datetime | None
    follow_up_at: datetime | None
    extra: dict[str, Any]
    created_at: datetime


class LeadListRead(BaseModel):
    """One uploaded sheet, as the dashboard shows it on a tab."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source: str
    source_filename: str | None
    imported_count: int
    skipped_count: int
    #: Live membership count, which drifts from imported_count as leads are
    #: deleted -- the tab must show what is actually there now.
    lead_count: int = 0
    created_at: datetime


class LeadListUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)


class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]
    #: The sheet this upload created, when it created one.
    lead_list: LeadListRead | None = None
