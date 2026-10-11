"""SMS and WhatsApp sending: the gates, the segment maths, the receipts.

These cover the rules that are expensive to get wrong -- an opt-out that does
not block, a segment count that understates the bill, a WhatsApp send outside
the session window -- rather than the happy path alone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.messaging import (
    Channel,
    ConsentMethod,
    ConsentRecord,
    Conversation,
    Message,
    MessageStatus,
    MessageTemplate,
    SuppressionReason,
    TemplateStatus,
)
from app.models.organization import Organization
from app.models.price_book import (
    Billable,
    PriceBook,
    PriceBookStatus,
    PriceRule,
    RateKind,
)
from app.models.user import User
from app.services.messaging_service import (
    MessagingService,
    SendBlocked,
    count_segments,
    normalise_number,
)
from tests.conftest import REGISTRATION

FROM = "+15550001111"
TO = "+919876543210"


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _price(db_session, billable: Billable, rate: str = "0.01") -> None:
    book = PriceBook(
        slug=f"msg-{uuid.uuid4().hex[:8]}",
        name="Messaging",
        status=PriceBookStatus.PUBLISHED,
        effective_from=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        PriceRule(
            price_book_id=book.id,
            billable=billable,
            rate_kind=RateKind.PER_UNIT,
            rate=Decimal(rate),
        )
    )
    await db_session.commit()


# --- segments ---------------------------------------------------------


def test_a_plain_message_fits_one_segment() -> None:
    assert count_segments("Hello there") == 1
    assert count_segments("A" * 160) == 1
    assert count_segments("A" * 161) == 2
    assert count_segments("A" * 306) == 2  # 153 * 2
    assert count_segments("A" * 307) == 3


def test_one_emoji_triples_the_bill() -> None:
    """A single non-GSM7 character drops the whole message to 70 chars a part.

    Counting by length alone understates the cost on exactly the messages
    customers send most.
    """
    plain = "A" * 160
    assert count_segments(plain) == 1
    assert count_segments(plain[:-1] + "😀") == 3


def test_a_rupee_sign_is_not_gsm7() -> None:
    assert count_segments("Pay ₹999 now" + "A" * 100) == 2


def test_an_empty_body_still_bills_one_segment() -> None:
    assert count_segments("") == 1


# --- numbers ----------------------------------------------------------


def test_numbers_are_normalised_so_one_contact_is_one_thread() -> None:
    for spelling in ("+91 98765 43210", "09876543210", "+919876543210"):
        number, region = normalise_number(spelling)
        assert number == TO
        assert region == "IN"


def test_an_unusable_number_is_refused_before_anything_is_reserved() -> None:
    with pytest.raises(SendBlocked):
        normalise_number("not a phone number")
    with pytest.raises(SendBlocked):
        normalise_number("+1")


# --- the gates --------------------------------------------------------


async def test_an_opted_out_number_is_recorded_not_silently_dropped(
    db_session, auth_headers
) -> None:
    """A missing message with no trace is the hardest support question there is."""
    org = await _org(db_session)
    service = MessagingService(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND)
    await service.opt_out(org.id, TO, reason=SuppressionReason.OPT_OUT)

    message = await service.prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
    )
    assert message.status is MessageStatus.SUPPRESSED
    assert message.suppression_reason == "opt_out"
    assert message.sent_at is None


async def test_opting_out_twice_is_not_an_error(db_session, auth_headers) -> None:
    """A second STOP from someone already unsubscribed is entirely normal."""
    org = await _org(db_session)
    service = MessagingService(db_session)
    first = await service.opt_out(org.id, TO, reason=SuppressionReason.OPT_OUT)
    second = await service.opt_out(org.id, TO, reason=SuppressionReason.OPT_OUT)
    assert first.id == second.id


async def test_opting_out_revokes_consent_so_the_two_records_agree(
    db_session, auth_headers
) -> None:
    org = await _org(db_session)
    db_session.add(
        ConsentRecord(
            organization_id=org.id,
            contact_number=TO,
            method=ConsentMethod.WEB_FORM,
            granted_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    service = MessagingService(db_session)
    assert await service.has_consent(org.id, TO, Channel.SMS) is True

    await service.opt_out(org.id, TO, reason=SuppressionReason.COMPLAINT)
    assert await service.has_consent(org.id, TO, Channel.SMS) is False


async def test_a_channel_specific_opt_out_leaves_the_other_channel_alone(
    db_session, auth_headers
) -> None:
    """Stopping WhatsApp is not consent withdrawn for SMS."""
    org = await _org(db_session)
    service = MessagingService(db_session)
    await service.opt_out(org.id, TO, reason=SuppressionReason.OPT_OUT, channel=Channel.WHATSAPP)
    assert await service.is_suppressed(org.id, TO, Channel.WHATSAPP) is not None
    assert await service.is_suppressed(org.id, TO, Channel.SMS) is None


async def test_requiring_consent_blocks_a_contact_who_never_gave_it(
    db_session, auth_headers
) -> None:
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND)
    message = await MessagingService(db_session).prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
        require_consent=True,
    )
    assert message.status is MessageStatus.SUPPRESSED
    assert message.suppression_reason == "no_consent"


# --- WhatsApp session rules -------------------------------------------


async def test_whatsapp_outside_the_session_window_demands_a_template(
    db_session, auth_headers
) -> None:
    """Sending free-form anyway is what gets a WhatsApp sender banned."""
    org = await _org(db_session)
    await _price(db_session, Billable.WHATSAPP_OUTBOUND)
    with pytest.raises(SendBlocked) as caught:
        await MessagingService(db_session).prepare(
            organization_id=org.id,
            channel=Channel.WHATSAPP,
            to_number=TO,
            from_number=FROM,
            body="Just checking in",
        )
    assert caught.value.code == "template_required"


async def test_a_recent_inbound_opens_the_window_for_a_free_form_reply(
    db_session, auth_headers
) -> None:
    org = await _org(db_session)
    await _price(db_session, Billable.WHATSAPP_OUTBOUND)
    service = MessagingService(db_session)
    await service.record_inbound(
        organization_id=org.id,
        channel=Channel.WHATSAPP,
        from_number=TO,
        to_number=FROM,
        body="Tell me more",
        provider="twilio",
        provider_message_id="SM_in_1",
    )
    reply = await service.prepare(
        organization_id=org.id,
        channel=Channel.WHATSAPP,
        to_number=TO,
        from_number=FROM,
        body="Happy to help",
    )
    assert reply.status is MessageStatus.QUEUED


async def test_an_unapproved_template_is_refused(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session, Billable.WHATSAPP_TEMPLATE)
    template = MessageTemplate(
        organization_id=org.id,
        channel=Channel.WHATSAPP,
        name="followup",
        body="Hi {{1}}",
        status=TemplateStatus.PENDING,
    )
    db_session.add(template)
    await db_session.commit()

    with pytest.raises(SendBlocked) as caught:
        await MessagingService(db_session).prepare(
            organization_id=org.id,
            channel=Channel.WHATSAPP,
            to_number=TO,
            from_number=FROM,
            template=template,
        )
    assert caught.value.code == "template_not_approved"


# --- idempotency ------------------------------------------------------


async def test_a_retried_send_returns_the_first_message_not_a_second_one(
    db_session, auth_headers
) -> None:
    """A retried bulk campaign must not double-charge or double-deliver."""
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND)
    service = MessagingService(db_session)
    kwargs = dict(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
        idempotency_key="campaign-7-row-42",
    )
    first = await service.prepare(**kwargs)
    second = await service.prepare(**kwargs)
    assert first.id == second.id

    total = await db_session.execute(select(Message).where(Message.organization_id == org.id))
    assert len(list(total.scalars())) == 1


# --- pricing ----------------------------------------------------------


async def test_a_message_carries_the_price_it_was_sent_under(db_session, auth_headers) -> None:
    """Recomputing from today's price book would rewrite history."""
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND, rate="0.02")
    message = await MessagingService(db_session).prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="A" * 200,  # two segments
    )
    assert message.segments == 2
    assert message.customer_charge_usd == Decimal("0.040000")
    assert message.price_rule_id is not None


async def test_an_unpriced_channel_is_flagged_rather_than_given_away(
    db_session, auth_headers
) -> None:
    org = await _org(db_session)
    message = await MessagingService(db_session).prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
    )
    assert message.cost_incomplete is True


async def test_an_estimate_deducts_suppressed_recipients_before_quoting(
    db_session, auth_headers
) -> None:
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND, rate="0.01")
    service = MessagingService(db_session)
    await service.opt_out(org.id, "+919876543211", reason=SuppressionReason.OPT_OUT)

    estimate = await service.estimate(
        organization_id=org.id,
        channel=Channel.SMS,
        recipients=[TO, "+919876543211", "+919876543212", "rubbish"],
        body="Hello",
    )
    assert estimate.recipients == 4
    assert estimate.suppressed == 2  # one opted out, one unparseable
    assert estimate.as_dict()["billable_recipients"] == 2
    assert estimate.quote.charge == Decimal("0.020000")


# --- delivery receipts ------------------------------------------------


async def test_a_late_receipt_never_undoes_a_delivery(db_session, auth_headers) -> None:
    """Receipts arrive out of order and more than once."""
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND)
    service = MessagingService(db_session)
    message = await service.prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
    )
    await service.record_dispatch(message, provider="twilio", provider_message_id="SM1")
    await service.apply_status_update(provider_message_id="SM1", status=MessageStatus.DELIVERED)
    await service.apply_status_update(provider_message_id="SM1", status=MessageStatus.SENT)
    refreshed = await db_session.get(Message, message.id)
    assert refreshed.status is MessageStatus.DELIVERED


async def test_a_read_receipt_may_follow_a_delivery(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND)
    service = MessagingService(db_session)
    message = await service.prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
    )
    await service.record_dispatch(message, provider="twilio", provider_message_id="SM2")
    await service.apply_status_update(provider_message_id="SM2", status=MessageStatus.DELIVERED)
    await service.apply_status_update(provider_message_id="SM2", status=MessageStatus.READ)
    refreshed = await db_session.get(Message, message.id)
    assert refreshed.status is MessageStatus.READ
    assert refreshed.read_at is not None


async def test_a_receipt_for_an_unknown_message_is_ignored_not_fatal(
    db_session, auth_headers
) -> None:
    result = await MessagingService(db_session).apply_status_update(
        provider_message_id="SM_never_seen", status=MessageStatus.DELIVERED
    )
    assert result is None


# --- inbound and threads ----------------------------------------------


async def test_an_inbound_reply_lands_in_the_existing_thread(db_session, auth_headers) -> None:
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND)
    service = MessagingService(db_session)
    sent = await service.prepare(
        organization_id=org.id,
        channel=Channel.SMS,
        to_number=TO,
        from_number=FROM,
        body="Hello",
    )
    inbound = await service.record_inbound(
        organization_id=org.id,
        channel=Channel.SMS,
        from_number="0" + TO[3:],  # same person, written differently
        to_number=FROM,
        body="Yes please",
        provider="twilio",
        provider_message_id="SM_in_2",
    )
    assert inbound.conversation_id == sent.conversation_id
    assert await service.unread_total(org.id) == 1


async def test_sms_and_whatsapp_to_one_number_are_separate_threads(
    db_session, auth_headers
) -> None:
    """Different senders, different rules, different costs."""
    org = await _org(db_session)
    service = MessagingService(db_session)
    sms = await service.conversation_for(org.id, TO, Channel.SMS)
    whatsapp = await service.conversation_for(org.id, TO, Channel.WHATSAPP)
    await db_session.commit()
    assert sms.id != whatsapp.id

    rows = await db_session.execute(
        select(Conversation).where(Conversation.organization_id == org.id)
    )
    assert len(list(rows.scalars())) == 2


# --- the API ----------------------------------------------------------


async def _second_org(client) -> dict[str, str]:
    response = await client.post(
        "/auth/register",
        json={
            **REGISTRATION,
            "email": "rival@example.com",
            "organization_name": "Rival Co",
        },
    )
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


async def test_the_messaging_api_is_closed_to_anonymous_callers(client) -> None:
    assert (await client.get("/messaging/conversations")).status_code == 401
    assert (await client.post("/messaging/messages", json={})).status_code == 401


async def test_sending_through_the_api_records_the_server_decided_price(
    client, auth_headers, db_session
) -> None:
    """The client sends a recipient and a body. It never sends a price."""
    org = await _org(db_session)
    await _price(db_session, Billable.SMS_OUTBOUND, rate="0.015")

    response = await client.post(
        "/messaging/messages",
        json={"to_number": TO, "channel": "sms", "body": "Hello there"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["to_number"] == TO
    assert body["segments"] == 1
    # Serialised as a string: a JSON number is a float and would reintroduce
    # exactly the drift the Decimal migration removed.
    assert body["customer_charge_usd"] == "0.015000"
    assert isinstance(body["customer_charge_usd"], str)
    assert str(org.id)  # the send was scoped to this tenant


async def test_a_suppressed_send_is_a_201_with_an_explanation_not_an_error(
    client, auth_headers, db_session
) -> None:
    """The request succeeded and produced a record; a 4xx would read as a bug."""
    await _price(db_session, Billable.SMS_OUTBOUND)
    await client.post(
        "/messaging/suppressions",
        json={"contact_number": TO, "reason": "opt_out"},
        headers=auth_headers,
    )
    response = await client.post(
        "/messaging/messages",
        json={"to_number": TO, "channel": "sms", "body": "Hello"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "suppressed"
    assert response.json()["suppression_reason"] == "opt_out"


async def test_an_estimate_needs_no_permission_to_spend(client, auth_headers, db_session) -> None:
    await _price(db_session, Billable.SMS_OUTBOUND, rate="0.01")
    response = await client.post(
        "/messaging/estimate",
        json={"channel": "sms", "recipients": [TO, "+919876543212"], "body": "Hi"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["billable_recipients"] == 2
    assert body["total_segments"] == 2
    assert body["customer_charge_usd"] == "0.020000"


async def test_a_template_cannot_be_born_approved(client, auth_headers) -> None:
    """Only the provider approves. A self-approved template bans the sender."""
    response = await client.post(
        "/messaging/templates",
        json={"name": "welcome", "channel": "whatsapp", "body": "Hi {{1}}"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "draft"
    assert response.json()["placeholder_count"] == 1


async def test_one_tenant_cannot_read_anothers_messages(client, auth_headers, db_session) -> None:
    await _price(db_session, Billable.SMS_OUTBOUND)
    mine = await client.post(
        "/messaging/messages",
        json={"to_number": TO, "channel": "sms", "body": "Confidential"},
        headers=auth_headers,
    )
    message_id = mine.json()["id"]

    theirs = await _second_org(client)
    assert (
        await client.get(f"/messaging/messages/{message_id}", headers=theirs)
    ).status_code == 404
    assert (await client.get("/messaging/messages", headers=theirs)).json()["total"] == 0


async def test_removing_an_opt_out_does_not_restore_consent(
    client, auth_headers, db_session
) -> None:
    """Un-suppressing must not quietly re-authorise contact."""
    org_id = (await _org(db_session)).id  # read before expire_all() detaches it
    service = MessagingService(db_session)
    await client.post(
        "/messaging/consent",
        json={"contact_number": TO, "method": "web_form"},
        headers=auth_headers,
    )
    created = await client.post(
        "/messaging/suppressions",
        json={"contact_number": TO, "reason": "opt_out"},
        headers=auth_headers,
    )
    await client.delete(f"/messaging/suppressions/{created.json()['id']}", headers=auth_headers)
    db_session.expire_all()
    assert await service.has_consent(org_id, TO, Channel.SMS) is False


async def test_the_inbox_lists_threads_newest_first_with_unread_counts(
    client, auth_headers, db_session
) -> None:
    org = await _org(db_session)
    service = MessagingService(db_session)
    await service.record_inbound(
        organization_id=org.id,
        channel=Channel.SMS,
        from_number=TO,
        to_number=FROM,
        body="Is this still available?",
        provider="twilio",
        provider_message_id="SM_api_1",
    )
    response = await client.get("/messaging/conversations", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["unread_count"] == 1
    assert items[0]["contact_number"] == TO

    assert (await client.get("/messaging/unread", headers=auth_headers)).json()["unread"] == 1

    marked = await client.post(
        f"/messaging/conversations/{items[0]['id']}/read", headers=auth_headers
    )
    assert marked.json()["unread_count"] == 0


async def test_the_inbox_reports_whether_a_free_form_whatsapp_reply_is_allowed(
    client, auth_headers, db_session
) -> None:
    """Computed server-side so the UI does not re-derive the 24-hour rule."""
    org = await _org(db_session)
    service = MessagingService(db_session)
    await service.record_inbound(
        organization_id=org.id,
        channel=Channel.WHATSAPP,
        from_number=TO,
        to_number=FROM,
        body="Hi",
        provider="twilio",
        provider_message_id="SM_api_2",
    )
    response = await client.get("/messaging/conversations?channel=whatsapp", headers=auth_headers)
    assert response.json()["items"][0]["session_open"] is True
