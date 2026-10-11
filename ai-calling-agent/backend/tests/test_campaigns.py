"""Campaign control: concurrency, calling hours, retries, lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.call import Call, CallStatus
from app.models.campaign import Campaign, CampaignLead, CampaignLeadStatus
from app.models.user import User
from app.services.campaign_service import CampaignService
from tests.conftest import REGISTRATION


async def _make_campaign(client: AsyncClient, headers: dict, agent: dict, **overrides) -> dict:
    payload = {
        "name": "Diwali outreach",
        "agent_id": agent["id"],
        "max_concurrent_calls": 2,
        "calling_hours_start": "00:00:00",
        "calling_hours_end": "23:59:00",
        **overrides,
    }
    response = await client.post("/campaigns", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_campaign_lifecycle(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict
) -> None:
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    assert campaign["status"] == "draft"
    assert campaign["stats"]["total_leads"] == 1

    started = await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    paused = await client.post(f"/campaigns/{campaign['id']}/pause", headers=auth_headers)
    assert paused.json()["status"] == "paused"

    stopped = await client.post(f"/campaigns/{campaign['id']}/stop", headers=auth_headers)
    assert stopped.json()["status"] == "stopped"


async def test_cannot_start_an_empty_campaign(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    campaign = await _make_campaign(client, auth_headers, agent)
    response = await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "campaign_empty"


async def test_concurrency_is_capped_by_the_schema(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    response = await client.post(
        "/campaigns",
        json={"name": "Too wide", "agent_id": agent["id"], "max_concurrent_calls": 500},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_dispatch_respects_the_concurrency_limit(
    client: AsyncClient, auth_headers: dict, agent: dict, db_session
) -> None:
    leads = []
    for index in range(5):
        created = await client.post(
            "/leads",
            json={"name": f"Lead {index}", "phone_number": f"98765000{index:02d}"},
            headers=auth_headers,
        )
        leads.append(created.json()["id"])

    campaign = await _make_campaign(
        client, auth_headers, agent, lead_ids=leads, max_concurrent_calls=2
    )
    await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)

    first = await client.post(f"/campaigns/{campaign['id']}/dispatch", headers=auth_headers)
    assert first.status_code == 200
    # Never more than the configured limit, however many leads are waiting.
    assert first.json()["started"] == 2

    second = await client.post(f"/campaigns/{campaign['id']}/dispatch", headers=auth_headers)
    assert second.json()["started"] == 0
    assert second.json()["reason"] == "at_concurrency_limit"

    calls = (
        (
            await db_session.execute(
                select(Call).where(Call.campaign_id == uuid.UUID(campaign["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(calls) == 2


async def test_dispatch_refuses_outside_calling_hours(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)

    record = await db_session.get(Campaign, uuid.UUID(campaign["id"]))
    # A one-minute window that has certainly passed today, in a fixed zone.
    record.timezone = "Asia/Kolkata"
    record.calling_hours_start = time(3, 0)
    record.calling_hours_end = time(3, 1)
    await db_session.commit()

    response = await client.post(f"/campaigns/{campaign['id']}/dispatch", headers=auth_headers)
    body = response.json()
    assert body["started"] == 0 or body["reason"] == "outside_calling_hours"


@pytest.mark.parametrize(
    ("start", "end", "now_hour", "expected"),
    [
        (time(10, 0), time(19, 0), 12, True),
        (time(10, 0), time(19, 0), 22, False),
        (time(22, 0), time(6, 0), 23, True),  # window wrapping midnight
        (time(22, 0), time(6, 0), 12, False),
    ],
)
def test_calling_window_arithmetic(start: time, end: time, now_hour: int, expected: bool) -> None:
    campaign = Campaign(
        name="x",
        agent_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        calling_hours_start=start,
        calling_hours_end=end,
        timezone="UTC",
    )
    now = datetime(2026, 8, 28, now_hour, 30, tzinfo=UTC)
    assert CampaignService(None).within_calling_hours(campaign, now) is expected  # type: ignore[arg-type]


async def test_a_no_answer_is_retried_until_the_cap(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    campaign = await _make_campaign(
        client, auth_headers, agent, lead_ids=[lead["id"]], max_retries=1
    )
    campaign_id = uuid.UUID(campaign["id"])
    user = (
        (await db_session.execute(select(User).where(User.email == "owner@example.com")))
        .unique()
        .scalar_one()
    )

    membership = (
        (
            await db_session.execute(
                select(CampaignLead).where(CampaignLead.campaign_id == campaign_id)
            )
        )
        .scalars()
        .one()
    )

    service = CampaignService(db_session)
    call = Call(
        organization_id=user.organization_id,
        agent_id=uuid.UUID(agent["id"]),
        lead_id=uuid.UUID(lead["id"]),
        campaign_id=campaign_id,
        status=CallStatus.NO_ANSWER,
    )
    db_session.add(call)

    membership.attempts = 1
    await db_session.commit()
    await service.on_call_finished(call)
    await db_session.refresh(membership)
    assert membership.status is CampaignLeadStatus.PENDING
    assert membership.next_attempt_at is not None

    membership.attempts = 2
    await db_session.commit()
    await service.on_call_finished(call)
    await db_session.refresh(membership)
    # Past the retry cap the lead is exhausted, not dialed forever.
    assert membership.status is CampaignLeadStatus.EXHAUSTED


async def test_a_completed_call_closes_the_membership(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    campaign_id = uuid.UUID(campaign["id"])
    user = (
        (await db_session.execute(select(User).where(User.email == "owner@example.com")))
        .unique()
        .scalar_one()
    )

    call = Call(
        organization_id=user.organization_id,
        agent_id=uuid.UUID(agent["id"]),
        lead_id=uuid.UUID(lead["id"]),
        campaign_id=campaign_id,
        status=CallStatus.COMPLETED,
    )
    db_session.add(call)
    await db_session.commit()

    await CampaignService(db_session).on_call_finished(call)
    membership = (
        (
            await db_session.execute(
                select(CampaignLead).where(CampaignLead.campaign_id == campaign_id)
            )
        )
        .scalars()
        .one()
    )
    assert membership.status is CampaignLeadStatus.COMPLETED


async def test_campaign_status_transitions_are_reflected_in_stats(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict
) -> None:
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    detail = await client.get(f"/campaigns/{campaign['id']}", headers=auth_headers)
    stats = detail.json()["stats"]
    assert stats["total_leads"] == 1
    assert stats["pending"] == 1
    assert stats["active_calls"] == 0
    assert stats["within_calling_hours"] is True


async def test_inbound_call_is_accepted_and_matched_to_a_lead(
    db_session, agent: dict, lead: dict
) -> None:
    """Someone dialling in gets a call record joined to their lead history."""
    from app.models.call import CallDirection, CallStatus
    from app.services.call_service import CallService

    call = await CallService(db_session).accept_inbound(
        provider="telnyx",
        provider_call_id="cc-inbound-1",
        from_number=lead["phone_number"],
        to_number="+13195368347",
    )
    assert call is not None
    assert call.direction is CallDirection.INBOUND
    assert call.status is CallStatus.RINGING
    assert str(call.lead_id) == lead["id"]
    assert str(call.agent_id) == agent["id"]


async def test_inbound_from_an_unknown_number_still_gets_answered(db_session, agent: dict) -> None:
    from app.services.call_service import CallService

    call = await CallService(db_session).accept_inbound(
        provider="telnyx",
        provider_call_id="cc-inbound-2",
        from_number="+15550009999",
        to_number="+13195368347",
    )
    assert call is not None
    assert call.lead_id is None


async def test_dial_now_calls_outside_the_configured_window(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    """The window governs the cron. A person pressing Dial now wants a call now."""
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)

    record = await db_session.get(Campaign, uuid.UUID(campaign["id"]))
    record.timezone = "Asia/Kolkata"
    record.calling_hours_start = time(3, 0)
    record.calling_hours_end = time(3, 1)
    await db_session.commit()

    blocked = await client.post(f"/campaigns/{campaign['id']}/dispatch", headers=auth_headers)
    assert blocked.json()["reason"] == "outside_calling_hours"
    assert blocked.json()["started"] == 0

    forced = await client.post(
        f"/campaigns/{campaign['id']}/dispatch?force=true", headers=auth_headers
    )
    assert forced.json()["started"] == 1, forced.text


async def test_dial_now_ignores_the_retry_backoff(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    """A lead parked behind a 3-hour retry delay should still dial on demand."""
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)

    membership = (
        await db_session.execute(
            select(CampaignLead).where(CampaignLead.campaign_id == uuid.UUID(campaign["id"]))
        )
    ).scalar_one()
    membership.next_attempt_at = datetime.now(UTC) + timedelta(hours=3)
    await db_session.commit()

    waiting = await client.post(f"/campaigns/{campaign['id']}/dispatch", headers=auth_headers)
    assert waiting.json()["started"] == 0

    forced = await client.post(
        f"/campaigns/{campaign['id']}/dispatch?force=true", headers=auth_headers
    )
    assert forced.json()["started"] == 1, forced.text


async def test_calls_the_provider_never_finished_stop_blocking_the_dialler(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    """A dropped status webhook used to wedge the dialler permanently.

    The call sat in `ringing` forever, counted towards the concurrency cap, and
    every dispatch returned at_concurrency_limit while the UI correctly showed
    nothing live. Eleven of these had accumulated on the live deployment.
    """
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    await client.post(f"/campaigns/{campaign['id']}/start", headers=auth_headers)

    record = await db_session.get(Campaign, uuid.UUID(campaign["id"]))
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()

    # Fill the cap with calls the provider never reported a terminal status for.
    for _ in range(record.max_concurrent_calls):
        db_session.add(
            Call(
                organization_id=user.organization_id,
                agent_id=uuid.UUID(agent["id"]),
                campaign_id=record.id,
                direction="outbound",
                provider="mock",
                from_number="+10000000000",
                to_number="+919876543210",
                status=CallStatus.RINGING,
                created_at=datetime.now(UTC) - timedelta(hours=4),
            )
        )
    await db_session.commit()

    blocked = await CampaignService(db_session).active_call_count(record.id)
    assert blocked == record.max_concurrent_calls

    reaped = await CampaignService(db_session).reap_stale_calls(user.organization_id)
    assert reaped == record.max_concurrent_calls
    assert await CampaignService(db_session).active_call_count(record.id) == 0

    forced = await client.post(
        f"/campaigns/{campaign['id']}/dispatch?force=true", headers=auth_headers
    )
    assert forced.json()["started"] == 1, forced.text


async def test_a_live_call_is_not_reaped(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    """The reaper must never hang up on a call that is genuinely in progress."""
    campaign = await _make_campaign(client, auth_headers, agent, lead_ids=[lead["id"]])
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    db_session.add(
        Call(
            organization_id=user.organization_id,
            agent_id=uuid.UUID(agent["id"]),
            campaign_id=uuid.UUID(campaign["id"]),
            direction="outbound",
            provider="mock",
            from_number="+10000000000",
            to_number="+919876543210",
            status=CallStatus.IN_PROGRESS,
        )
    )
    await db_session.commit()

    assert await CampaignService(db_session).reap_stale_calls(user.organization_id) == 0


async def test_uploading_a_csv_puts_everyone_in_it_on_the_campaign(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    """The point is one step: upload a list, and those people get called."""
    campaign = await _make_campaign(client, auth_headers, agent)
    csv = (
        b"name,phone,email\n"
        b"Suresh Kumar,9876500001,suresh@example.com\n"
        b"Neha Gupta,9876500002,neha@example.com\n"
    )

    response = await client.post(
        f"/campaigns/{campaign['id']}/leads/import",
        files={"file": ("leads.csv", csv, "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 2
    assert body["attached"] == 2

    listed = await client.get(f"/campaigns/{campaign['id']}/leads", headers=auth_headers)
    assert listed.json()["total"] == 2


async def test_a_number_already_on_file_is_still_added_to_the_campaign(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict
) -> None:
    """A duplicate row still means "call this person".

    Counting it as skipped and leaving it off the campaign would quietly drop
    people from the list the user just uploaded.
    """
    campaign = await _make_campaign(client, auth_headers, agent)
    csv = f"name,phone\n{lead['name']},{lead['phone_number']}\n".encode()

    response = await client.post(
        f"/campaigns/{campaign['id']}/leads/import",
        files={"file": ("leads.csv", csv, "text/csv")},
        headers=auth_headers,
    )
    body = response.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert body["attached"] == 1, "an existing lead must still join the campaign"


async def test_do_not_call_leads_are_never_added_by_a_csv_upload(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict
) -> None:
    """A spreadsheet must not be able to override someone's opt-out."""
    await client.patch(f"/leads/{lead['id']}", json={"status": "do_not_call"}, headers=auth_headers)
    campaign = await _make_campaign(client, auth_headers, agent)
    csv = f"name,phone\n{lead['name']},{lead['phone_number']}\n".encode()

    response = await client.post(
        f"/campaigns/{campaign['id']}/leads/import",
        files={"file": ("leads.csv", csv, "text/csv")},
        headers=auth_headers,
    )
    assert response.json()["attached"] == 0

    listed = await client.get(f"/campaigns/{campaign['id']}/leads", headers=auth_headers)
    assert listed.json()["total"] == 0


async def test_campaign_import_rejects_a_non_csv(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    campaign = await _make_campaign(client, auth_headers, agent)
    response = await client.post(
        f"/campaigns/{campaign['id']}/leads/import",
        files={"file": ("leads.xlsx", b"not a csv", "application/vnd.ms-excel")},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_a_whole_sheet_can_be_added_to_a_campaign(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    """Dialling an uploaded list should not mean hand-picking its leads."""
    imported = await client.post(
        "/leads/import",
        files={"file": ("march.csv", b"name,phone\nA,9876600001\nB,9876600002\n", "text/csv")},
        headers=auth_headers,
    )
    list_id = imported.json()["lead_list"]["id"]
    campaign = await _make_campaign(client, auth_headers, agent)

    added = await client.post(
        f"/campaigns/{campaign['id']}/leads/from-sheet",
        json={"lead_list_id": list_id},
        headers=auth_headers,
    )
    assert added.status_code == 200, added.text
    assert "2 lead(s)" in added.json()["message"]

    listed = await client.get(f"/campaigns/{campaign['id']}/leads", headers=auth_headers)
    assert listed.json()["total"] == 2


async def test_adding_a_sheet_twice_does_not_duplicate_anyone(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    imported = await client.post(
        "/leads/import",
        files={"file": ("again.csv", b"name,phone\nA,9876600011\n", "text/csv")},
        headers=auth_headers,
    )
    list_id = imported.json()["lead_list"]["id"]
    campaign = await _make_campaign(client, auth_headers, agent)

    for _ in range(2):
        await client.post(
            f"/campaigns/{campaign['id']}/leads/from-sheet",
            json={"lead_list_id": list_id},
            headers=auth_headers,
        )

    listed = await client.get(f"/campaigns/{campaign['id']}/leads", headers=auth_headers)
    assert listed.json()["total"] == 1


async def test_a_sheet_never_adds_do_not_call_leads(
    client: AsyncClient, auth_headers: dict, agent: dict
) -> None:
    """A spreadsheet must not be able to override someone's opt-out."""
    imported = await client.post(
        "/leads/import",
        files={"file": ("optout.csv", b"name,phone\nStop Calling,9876600021\n", "text/csv")},
        headers=auth_headers,
    )
    list_id = imported.json()["lead_list"]["id"]
    lead_id = (await client.get("/leads", headers=auth_headers)).json()["items"][0]["id"]
    await client.patch(f"/leads/{lead_id}", json={"status": "do_not_call"}, headers=auth_headers)

    campaign = await _make_campaign(client, auth_headers, agent)
    added = await client.post(
        f"/campaigns/{campaign['id']}/leads/from-sheet",
        json={"lead_list_id": list_id},
        headers=auth_headers,
    )
    assert "0 lead(s)" in added.json()["message"]
