"""Post-call processing: summarise, extract, score, schedule follow-up.

Output is validated with Pydantic before it touches the database. An LLM that
returns a malformed score must not be able to corrupt lead data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.call import Call, CallTurn
from app.models.lead import InterestLevel, Lead, LeadStatus
from app.services.cost_service import CostService
from app.services.registry import get_llm

log = get_logger(__name__)

EXTRACTION_SYSTEM = (
    "You analyse sales call transcripts. Report only what the transcript supports. "
    "Leave a field empty rather than guessing. Never invent a budget, timeline, or "
    "commitment the customer did not state."
)


class CallExtraction(BaseModel):
    summary: str = Field(default="", max_length=2000)
    requirement: str = Field(default="", max_length=500)
    budget: str = Field(default="", max_length=200)
    timeline: str = Field(default="", max_length=200)
    interest_level: InterestLevel = InterestLevel.UNKNOWN
    objections: list[str] = Field(default_factory=list)
    follow_up_required: bool = False
    follow_up_time: datetime | None = None
    lead_score: int = Field(default=0, ge=0, le=100)
    email: str | None = None
    outcome: str = Field(default="unknown", max_length=40)

    @field_validator("interest_level", mode="before")
    @classmethod
    def _coerce_interest(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered if lowered in set(InterestLevel) else InterestLevel.UNKNOWN
        return value

    @field_validator("objections", mode="before")
    @classmethod
    def _coerce_objections(cls, value: object) -> object:
        if isinstance(value, str):
            return [value] if value.strip() else []
        return value or []


OUTCOME_TO_STATUS = {
    "qualified": LeadStatus.QUALIFIED,
    "interested": LeadStatus.INTERESTED,
    "follow_up": LeadStatus.CALLBACK,
    "callback": LeadStatus.CALLBACK,
    "not_interested": LeadStatus.NOT_INTERESTED,
    "do_not_call": LeadStatus.DO_NOT_CALL,
    "converted": LeadStatus.CONVERTED,
}


class PostCallService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def process(self, call_id: uuid.UUID) -> CallExtraction | None:
        call = await self.db.get(Call, call_id)
        if call is None:
            return None

        transcript = await self._transcript(call_id)
        if not transcript.strip():
            log.info("postcall.skipped", call_id=str(call_id), reason="empty transcript")
            call.summary = "No conversation took place."
            await self.db.commit()
            return None

        extraction = await self._extract(call, transcript)
        if extraction is None:
            return None

        call.summary = extraction.summary
        call.extracted_data = extraction.model_dump(mode="json")
        await self.db.commit()

        if call.lead_id:
            await self._apply_to_lead(call.lead_id, extraction)

        log.info("postcall.done", call_id=str(call_id), score=extraction.lead_score)
        return extraction

    async def _transcript(self, call_id: uuid.UUID) -> str:
        result = await self.db.execute(
            select(CallTurn).where(CallTurn.call_id == call_id).order_by(CallTurn.turn_index)
        )
        return "\n".join(f"{turn.role}: {turn.content}" for turn in result.scalars())

    async def _extract(self, call: Call, transcript: str) -> CallExtraction | None:
        schema = CallExtraction.model_json_schema()
        prompt = (
            "Summarise this call in two or three sentences and extract the structured "
            "fields. Score the lead from 0 to 100 based only on stated interest, "
            "budget fit, and urgency.\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            data, usage = await get_llm().complete_json(
                system=EXTRACTION_SYSTEM, prompt=prompt, schema=schema
            )
        except Exception as exc:
            log.error("postcall.llm_failed", call_id=str(call.id), error=str(exc))
            return None

        await CostService(self.db).record_usage(call=call, records=usage)

        try:
            return CallExtraction.model_validate(data)
        except ValidationError as exc:
            # Salvage the summary rather than losing the whole call.
            log.warning("postcall.invalid_extraction", call_id=str(call.id), error=str(exc))
            return CallExtraction(summary=str(data.get("summary", ""))[:2000])

    async def _apply_to_lead(self, lead_id: uuid.UUID, extraction: CallExtraction) -> None:
        lead = await self.db.get(Lead, lead_id)
        if lead is None:
            return

        lead.interest_level = extraction.interest_level
        lead.lead_score = extraction.lead_score
        if extraction.email and not lead.email:
            lead.email = extraction.email

        status = OUTCOME_TO_STATUS.get(extraction.outcome.lower())
        if status is None:
            status = {
                InterestLevel.HIGH: LeadStatus.QUALIFIED,
                InterestLevel.MEDIUM: LeadStatus.INTERESTED,
                InterestLevel.LOW: LeadStatus.NOT_INTERESTED,
            }.get(extraction.interest_level, LeadStatus.CONTACTED)
        # A do-not-call decision is never walked back by a later heuristic.
        if lead.status != LeadStatus.DO_NOT_CALL:
            lead.status = status

        if extraction.follow_up_required:
            lead.follow_up_at = extraction.follow_up_time or datetime.now(UTC) + timedelta(days=1)

        notes = [note for note in [lead.notes, extraction.summary] if note]
        lead.notes = "\n\n".join(notes)[-4000:]
        await self.db.commit()
