"""Who placed each call, and how it was started.

Calls could previously only be traced to an organization, so "which of your
team made this call" had no answer. These are the directive's §V–VI tests.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.models.call import Call, CallMode, CallSource
from app.models.user import User
from tests.conftest import REGISTRATION


async def test_a_dashboard_call_records_the_person_who_placed_it(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, lead: dict, db_session
) -> None:
    created = await client.post(
        "/calls", json={"agent_id": agent["id"], "lead_id": lead["id"]}, headers=auth_headers
    )
    assert created.status_code == 201, created.text
    body = created.json()

    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    assert body["initiated_by_user_id"] == str(user.id)
    assert body["source"] == "manual"
    assert REGISTRATION["email"] in body["source_detail"]


async def test_a_manual_bridge_is_manual_source_but_human_mode(
    client: AsyncClient, auth_headers: dict[str, str], lead: dict
) -> None:
    """Source says who started it; mode says who talks. They are not the same."""
    created = await client.post(
        "/calls/bridge",
        json={"operator_number": "9812345678", "lead_id": lead["id"]},
        headers=auth_headers,
    )
    body = created.json()
    assert body["source"] == CallSource.MANUAL
    assert body["mode"] == CallMode.HUMAN
    assert body["initiated_by_user_id"] is not None


async def test_an_agent_call_is_manual_source_with_agent_mode(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, lead: dict
) -> None:
    """Pressing a button to launch an AI is a manual *start* of an AI call.

    Classifying it as a manual call would make the manual-calling analytics
    meaningless.
    """
    created = await client.post(
        "/calls", json={"agent_id": agent["id"], "lead_id": lead["id"]}, headers=auth_headers
    )
    assert created.json()["source"] == CallSource.MANUAL
    assert created.json()["mode"] == CallMode.AGENT


async def test_a_campaign_call_has_no_initiating_person(
    client: AsyncClient, auth_headers: dict, agent: dict, lead: dict, db_session
) -> None:
    """A dispatcher tick placed it. Attributing it to a person would be a lie."""
    campaign = await client.post(
        "/campaigns",
        json={
            "name": "Attribution",
            "agent_id": agent["id"],
            "lead_ids": [lead["id"]],
            "calling_hours_start": "00:00:00",
            "calling_hours_end": "23:59:00",
        },
        headers=auth_headers,
    )
    campaign_id = uuid.UUID(campaign.json()["id"])
    await client.post(f"/campaigns/{campaign_id}/start", headers=auth_headers)
    await client.post(f"/campaigns/{campaign_id}/dispatch?force=true", headers=auth_headers)

    call = (
        (await db_session.execute(select(Call).where(Call.campaign_id == campaign_id)))
        .scalars()
        .first()
    )
    assert call is not None
    assert call.source is CallSource.CAMPAIGN
    assert call.initiated_by_user_id is None
    assert "Attribution" in (call.source_detail or "")


async def test_calls_can_be_filtered_by_source_and_by_person(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, lead: dict, db_session
) -> None:
    """The admin's first question is "show me everything this user did"."""
    await client.post(
        "/calls", json={"agent_id": agent["id"], "lead_id": lead["id"]}, headers=auth_headers
    )
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()

    by_source = await client.get("/calls?source=manual", headers=auth_headers)
    assert by_source.json()["total"] >= 1

    by_person = await client.get(f"/calls?initiated_by={user.id}", headers=auth_headers)
    assert by_person.json()["total"] >= 1

    nobody = await client.get("/calls?source=inbound", headers=auth_headers)
    assert nobody.json()["total"] == 0


async def test_a_call_pins_the_agent_configuration_it_ran_under(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, lead: dict
) -> None:
    """Editing an agent must not rewrite the history of its past calls."""
    first = await client.post(
        "/calls", json={"agent_id": agent["id"], "lead_id": lead["id"]}, headers=auth_headers
    )
    version = first.json()["agent_version"]
    assert version is not None

    await client.patch(
        f"/agents/{agent['id']}", json={"greeting": "Completely new"}, headers=auth_headers
    )
    assert (await client.get(f"/calls/{first.json()['id']}", headers=auth_headers)).json()[
        "agent_version"
    ] == version
