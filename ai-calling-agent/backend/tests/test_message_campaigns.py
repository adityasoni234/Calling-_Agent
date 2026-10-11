"""Bulk sends: quoting before launch, pacing, resumability, idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.lead import Lead
from app.models.messaging import Message, MessageCampaign, MessageCampaignStatus
from app.models.organization import Organization
from app.models.price_book import Billable, PriceBook, PriceBookStatus, PriceRule, RateKind
from app.models.user import User
from app.services.message_campaign_service import MessageCampaignService
from tests.conftest import REGISTRATION


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _leads(db_session, org_id, count=5) -> None:
    for i in range(count):
        db_session.add(
            Lead(
                organization_id=org_id,
                name=f"Lead {i}",
                phone_number=f"+9198765432{i:02d}",
            )
        )
    await db_session.commit()


async def _price(db_session) -> None:
    book = PriceBook(
        slug=f"c-{uuid.uuid4().hex[:8]}",
        name="Msg",
        status=PriceBookStatus.PUBLISHED,
        effective_from=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        PriceRule(
            price_book_id=book.id,
            billable=Billable.SMS_OUTBOUND,
            rate_kind=RateKind.PER_UNIT,
            rate=Decimal("0.02"),
        )
    )
    await db_session.commit()


async def _campaign(db_session, org_id, **kw) -> MessageCampaign:
    return await MessageCampaignService(db_session).create(
        organization_id=org_id,
        name=kw.get("name", "October blast"),
        channel=kw.get("channel", "sms"),
        body=kw.get("body", "Hello from us"),
        template_id=None,
        lead_list_id=None,
        from_number="+15550001111",
        messages_per_minute=60,
        scheduled_at=kw.get("scheduled_at"),
        user_id=None,
    )


async def test_a_campaign_is_quoted_before_it_launches(db_session, auth_headers) -> None:
    """Nobody should learn a bulk send's cost from their balance afterwards."""
    org = await _org(db_session)
    await _leads(db_session, org.id, 5)
    await _price(db_session)

    campaign = await _campaign(db_session, org.id)
    assert campaign.status is MessageCampaignStatus.DRAFT
    assert campaign.total_recipients == 5
    assert campaign.estimated_charge_usd == Decimal("0.100000")  # 5 x $0.02


async def test_an_empty_list_is_refused_rather_than_launched(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session)
    with pytest.raises(AppError):
        await _campaign(db_session, org.id)


async def test_dispatch_sends_every_recipient_exactly_once(db_session, auth_headers) -> None:
    """A re-run slice must not send anyone a second copy."""
    org = await _org(db_session)
    await _leads(db_session, org.id, 4)
    await _price(db_session)

    service = MessageCampaignService(db_session)
    campaign = await _campaign(db_session, org.id)
    await service.launch(campaign)

    await service.dispatch_slice(campaign)
    await service.dispatch_slice(campaign)  # re-run

    rows = await db_session.execute(select(Message).where(Message.campaign_id == campaign.id))
    messages = list(rows.scalars())
    assert len(messages) == 4
    assert len({m.to_number for m in messages}) == 4


async def test_a_completed_campaign_reports_its_real_charge(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _leads(db_session, org.id, 3)
    await _price(db_session)

    service = MessageCampaignService(db_session)
    campaign = await _campaign(db_session, org.id)
    await service.launch(campaign)
    await service.dispatch_slice(campaign)
    progress = await service.refresh_progress(campaign)

    assert progress.remaining == 0
    assert progress.percent == 100
    assert campaign.status is MessageCampaignStatus.COMPLETED
    assert campaign.actual_charge_usd == Decimal("0.060000")


async def test_a_paused_campaign_sends_nothing(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _leads(db_session, org.id, 3)
    await _price(db_session)

    service = MessageCampaignService(db_session)
    campaign = await _campaign(db_session, org.id)
    await service.launch(campaign)
    await service.set_status(campaign, MessageCampaignStatus.PAUSED)

    assert await service.dispatch_slice(campaign) == 0
    rows = await db_session.execute(select(Message).where(Message.campaign_id == campaign.id))
    assert list(rows.scalars()) == []


async def test_a_future_campaign_waits_rather_than_running(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _leads(db_session, org.id, 2)
    await _price(db_session)

    service = MessageCampaignService(db_session)
    campaign = await _campaign(
        db_session, org.id, scheduled_at=datetime.now(UTC) + timedelta(hours=2)
    )
    await service.launch(campaign)
    assert campaign.status is MessageCampaignStatus.SCHEDULED
    assert await service.dispatch_slice(campaign) == 0


async def test_opted_out_recipients_are_counted_not_messaged(db_session, auth_headers) -> None:
    from app.models.messaging import SuppressionReason
    from app.services.messaging_service import MessagingService

    org = await _org(db_session)
    await _leads(db_session, org.id, 3)
    await _price(db_session)
    await MessagingService(db_session).opt_out(
        org.id, "+919876543200", reason=SuppressionReason.OPT_OUT
    )

    service = MessageCampaignService(db_session)
    campaign = await _campaign(db_session, org.id)
    await service.launch(campaign)
    await service.dispatch_slice(campaign)
    progress = await service.refresh_progress(campaign)

    assert progress.suppressed == 1
    assert progress.sent == 2


# --- the API ----------------------------------------------------------


async def test_the_campaign_api_round_trips(client, auth_headers, db_session) -> None:
    org = await _org(db_session)
    await _leads(db_session, org.id, 3)
    await _price(db_session)

    created = await client.post(
        "/messaging/campaigns",
        json={"name": "Launch", "channel": "sms", "body": "Hi there"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["total_recipients"] == 3
    assert body["estimated_charge_usd"] == "0.060000"

    launched = await client.post(f"/messaging/campaigns/{body['id']}/launch", headers=auth_headers)
    assert launched.json()["status"] == "running"

    sent = await client.post(f"/messaging/campaigns/{body['id']}/send-now", headers=auth_headers)
    assert sent.json()["percent_complete"] == 100

    listed = await client.get("/messaging/campaigns", headers=auth_headers)
    assert len(listed.json()) == 1


async def test_one_tenant_cannot_control_anothers_campaign(
    client, auth_headers, db_session
) -> None:
    org = await _org(db_session)
    await _leads(db_session, org.id, 2)
    await _price(db_session)
    mine = await client.post(
        "/messaging/campaigns",
        json={"name": "Mine", "channel": "sms", "body": "Hi"},
        headers=auth_headers,
    )
    rival = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "rival2@example.com", "organization_name": "Rival2"},
    )
    theirs = {"Authorization": f"Bearer {rival.json()['tokens']['access_token']}"}

    response = await client.post(f"/messaging/campaigns/{mine.json()['id']}/cancel", headers=theirs)
    assert response.status_code == 404
