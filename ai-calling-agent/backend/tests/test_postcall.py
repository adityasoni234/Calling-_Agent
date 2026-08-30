"""Post-call summarisation, extraction, and lead scoring."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.models.call import Call, CallStatus, CallTurn
from app.models.lead import InterestLevel, Lead, LeadStatus
from app.models.user import User
from app.services.postcall_service import CallExtraction, PostCallService

TRANSCRIPT = [
    ("agent", "Hello, this is Riya from Acme Telecom."),
    ("customer", "Haan boliye, price kya hoga?"),
    ("agent", "Pricing depends on your usage. Aapka monthly volume kitna hoga?"),
    ("customer", "Budget thoda tight hai, but interested hoon. My email is ravi@example.com"),
]


@pytest.fixture
async def completed_call(db_session, agent: dict, lead: dict, auth_headers: dict) -> Call:
    user = (
        (await db_session.execute(select(User).where(User.email == "owner@example.com")))
        .unique()
        .scalar_one()
    )
    call = Call(
        organization_id=user.organization_id,
        agent_id=uuid.UUID(agent["id"]),
        lead_id=uuid.UUID(lead["id"]),
        status=CallStatus.COMPLETED,
        duration_seconds=95,
        provider="mock",
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)

    for index, (role, content) in enumerate(TRANSCRIPT):
        db_session.add(CallTurn(call_id=call.id, turn_index=index, role=role, content=content))
    await db_session.commit()
    return call


async def test_extraction_populates_summary_and_structured_data(
    db_session, completed_call: Call
) -> None:
    extraction = await PostCallService(db_session).process(completed_call.id)
    assert extraction is not None

    await db_session.refresh(completed_call)
    assert completed_call.summary
    assert completed_call.extracted_data is not None
    # Every field the spec requires is present in the stored payload.
    for field in (
        "requirement",
        "budget",
        "timeline",
        "interest_level",
        "objections",
        "follow_up_required",
        "lead_score",
    ):
        assert field in completed_call.extracted_data


async def test_extraction_updates_the_lead(db_session, completed_call: Call) -> None:
    await PostCallService(db_session).process(completed_call.id)

    lead = await db_session.get(Lead, completed_call.lead_id)
    assert lead is not None
    assert lead.lead_score > 0
    assert lead.interest_level is not InterestLevel.UNKNOWN
    assert lead.status is not LeadStatus.NEW
    assert lead.notes


async def test_an_empty_transcript_is_not_summarised(db_session, agent: dict) -> None:
    user = (
        (await db_session.execute(select(User).where(User.email == "owner@example.com")))
        .unique()
        .scalar_one()
    )
    call = Call(
        organization_id=user.organization_id,
        agent_id=uuid.UUID(agent["id"]),
        status=CallStatus.NO_ANSWER,
        provider="mock",
    )
    db_session.add(call)
    await db_session.commit()

    assert await PostCallService(db_session).process(call.id) is None
    await db_session.refresh(call)
    assert call.summary == "No conversation took place."


def test_extraction_schema_rejects_an_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        CallExtraction(lead_score=250)


def test_extraction_schema_coerces_loose_model_output() -> None:
    extraction = CallExtraction.model_validate(
        {"interest_level": "VERY HIGH", "objections": "too expensive", "lead_score": 40}
    )
    # An unrecognised level falls back rather than corrupting the lead record.
    assert extraction.interest_level is InterestLevel.UNKNOWN
    assert extraction.objections == ["too expensive"]


async def test_a_do_not_call_lead_is_never_re_enabled(db_session, completed_call: Call) -> None:
    lead = await db_session.get(Lead, completed_call.lead_id)
    lead.status = LeadStatus.DO_NOT_CALL
    await db_session.commit()

    await PostCallService(db_session).process(completed_call.id)
    await db_session.refresh(lead)
    assert lead.status is LeadStatus.DO_NOT_CALL


async def test_reprocess_endpoint(
    client: AsyncClient, auth_headers: dict, completed_call: Call
) -> None:
    response = await client.post(f"/calls/{completed_call.id}/reprocess", headers=auth_headers)
    assert response.status_code == 200

    detail = await client.get(f"/calls/{completed_call.id}", headers=auth_headers)
    body = detail.json()
    assert body["summary"]
    assert len(body["turns"]) == len(TRANSCRIPT)
