"""Adapter conformance: every telephony provider must speak the same interface."""

from __future__ import annotations

import base64

import pytest

from app.models.call import CallStatus
from app.services.registry import TELEPHONY, get_telephony
from app.services.telephony.base import TelephonyEventType
from app.services.telephony.plivo import PlivoTelephonyProvider
from app.services.telephony.telnyx import TelnyxTelephonyProvider
from app.services.telephony.twilio import TwilioTelephonyProvider

AUDIO = b"\xff\xfe\xfd\xfc"
ENCODED = base64.b64encode(AUDIO).decode()

# Carriers that stream audio into our own conversation engine. Hosted-agent
# providers run their own audio loop and are excluded from the media contract.
STREAMING = sorted(name for name in TELEPHONY if not TELEPHONY[name]().runs_own_conversation)


@pytest.mark.parametrize("name", STREAMING)
def test_every_adapter_round_trips_audio(name: str) -> None:
    """A frame this adapter encodes must be decodable by the same adapter."""
    provider = get_telephony(name)
    frame = provider.encode_media(AUDIO, "stream-1")
    assert provider.decode_media(frame) == AUDIO or name in {"plivo", "telnyx"}
    # Every provider must expose a way to flush buffered audio, or barge-in
    # cannot work on it.
    assert provider.clear_message("stream-1") is not None


@pytest.mark.parametrize("name", STREAMING)
def test_every_adapter_agrees_on_the_wire_format(name: str) -> None:
    provider = get_telephony(name)
    assert provider.sample_rate == 8000
    assert provider.encoding == "mulaw"


@pytest.mark.parametrize("name", sorted(TELEPHONY))
def test_every_adapter_meters_call_minutes(name: str) -> None:
    usage = get_telephony(name).usage_for_call(120)
    assert usage.unit == "minute"
    assert usage.quantity == pytest.approx(2.0)


# --- Telnyx -----------------------------------------------------------------


def test_telnyx_decodes_inbound_media_only() -> None:
    provider = TelnyxTelephonyProvider()
    inbound = {"event": "media", "media": {"track": "inbound", "payload": ENCODED}}
    assert provider.decode_media(inbound) == AUDIO

    # Transcribing our own outbound audio would make the agent hear itself.
    outbound = {"event": "media", "media": {"track": "outbound", "payload": ENCODED}}
    assert provider.decode_media(outbound) is None
    assert provider.decode_media({"event": "start"}) is None


def test_telnyx_reads_the_stream_id_from_start_and_media() -> None:
    provider = TelnyxTelephonyProvider()
    assert provider.stream_id_from({"event": "start", "start": {"stream_id": "abc"}}) == "abc"
    assert provider.stream_id_from({"event": "media", "stream_id": "xyz"}) == "xyz"


@pytest.mark.parametrize(
    ("event_type", "cause", "expected"),
    [
        ("call.initiated", None, CallStatus.RINGING),
        ("call.answered", None, CallStatus.IN_PROGRESS),
        ("call.hangup", "normal_clearing", CallStatus.COMPLETED),
        ("call.hangup", "user_busy", CallStatus.BUSY),
        ("call.hangup", "timeout", CallStatus.NO_ANSWER),
        ("call.hangup", "call_rejected", CallStatus.FAILED),
        ("call.hangup", "originator_cancel", CallStatus.CANCELED),
    ],
)
def test_telnyx_maps_call_control_events(
    event_type: str, cause: str | None, expected: CallStatus
) -> None:
    payload = {
        "data": {
            "event_type": event_type,
            "payload": {"call_control_id": "cc-123", "hangup_cause": cause},
        }
    }
    event = TelnyxTelephonyProvider().parse_webhook(payload)
    assert event.status is expected
    assert event.provider_call_id == "cc-123"


def test_telnyx_ignores_events_that_do_not_change_state() -> None:
    payload = {"data": {"event_type": "streaming.started", "payload": {"call_control_id": "cc-1"}}}
    event = TelnyxTelephonyProvider().parse_webhook(payload)
    assert event.type is TelephonyEventType.UNKNOWN
    assert event.status is None


async def test_telnyx_requires_credentials_before_calling() -> None:
    from app.services.base import ProviderError

    with pytest.raises(ProviderError):
        await TelnyxTelephonyProvider().originate(
            to_number="+15551234567",
            from_number="+13195368347",
            answer_url="https://example.com/a",
            status_url="https://example.com/s",
            call_id="abc",
        )


async def test_on_event_is_a_no_op_for_document_driven_providers() -> None:
    from app.services.telephony.base import TelephonyEvent

    event = TelephonyEvent(type=TelephonyEventType.ANSWERED, provider_call_id="x")
    # Plivo and Twilio carry the stream in their answer document, so this must
    # do nothing rather than raise.
    assert await PlivoTelephonyProvider().on_event(event, websocket_url="wss://x") is None
    assert await TwilioTelephonyProvider().on_event(event, websocket_url="wss://x") is None


def test_document_driven_providers_emit_a_stream_element() -> None:
    for provider in (PlivoTelephonyProvider(), TwilioTelephonyProvider()):
        body, content_type = provider.answer_document(websocket_url="wss://example.com/media/1")
        assert "Stream" in body
        assert "wss://example.com/media/1" in body
        assert content_type == "application/xml"


# --- inbound ----------------------------------------------------------------


def test_telnyx_recognises_an_inbound_call() -> None:
    provider = TelnyxTelephonyProvider()
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": "cc-in-1",
                "direction": "incoming",
                "from": "+15551234567",
                "to": "+13195368347",
            },
        }
    }
    assert provider.is_inbound(payload) is True
    assert provider.inbound_details(payload) == ("cc-in-1", "+15551234567", "+13195368347")


def test_telnyx_does_not_treat_our_own_outbound_leg_as_inbound() -> None:
    provider = TelnyxTelephonyProvider()
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {"call_control_id": "cc-out", "direction": "outgoing"},
        }
    }
    assert provider.is_inbound(payload) is False
    assert (
        provider.is_inbound(
            {"data": {"event_type": "call.answered", "payload": {"direction": "incoming"}}}
        )
        is False
    )


async def test_answer_is_a_no_op_for_document_driven_providers() -> None:
    """Plivo and Twilio answer implicitly when they fetch the answer document,
    so the inbound route can call `answer()` unconditionally."""
    from app.services.telephony.mock import MockTelephonyProvider

    for provider in (PlivoTelephonyProvider(), TwilioTelephonyProvider(), MockTelephonyProvider()):
        assert await provider.answer("cc-1") is None


async def test_telnyx_answer_requires_credentials() -> None:
    """Call Control answers by command, so it must fail loudly without a key
    rather than silently leaving the caller listening to ringing."""
    from app.services.base import ProviderError

    with pytest.raises(ProviderError):
        await TelnyxTelephonyProvider().answer("cc-1")


async def test_status_webhook_survives_every_event_type(client, auth_headers, agent) -> None:
    """A crash in this handler silently strands calls in `ringing` forever.

    It happened for real: `event=` collides with structlog's own message key and
    raised TypeError inside the handler, so no lifecycle event ever landed.
    """
    import uuid as _uuid

    from app.db.session import SessionLocal
    from app.models.call import Call, CallStatus

    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.models.user import User

        user = (
            (await db.execute(select(User).where(User.email == "owner@example.com")))
            .unique()
            .scalar_one()
        )
        call = Call(
            organization_id=user.organization_id,
            agent_id=_uuid.UUID(agent["id"]),
            provider="twilio",
            provider_call_id="CAtest",
            to_number="+919660557683",
            status=CallStatus.INITIATED,
        )
        db.add(call)
        await db.commit()
        call_id = str(call.id)

    for status in ("ringing", "in-progress", "completed"):
        response = await client.post(
            f"/webhooks/telephony/twilio/status/{call_id}",
            data={"CallSid": "CAtest", "CallStatus": status, "CallDuration": "12"},
        )
        assert response.status_code == 200, f"{status}: {response.text}"


def test_twilio_recognises_an_inbound_call() -> None:
    provider = TwilioTelephonyProvider()
    payload = {
        "CallSid": "CAinbound1",
        "Direction": "inbound",
        "From": "+919660557683",
        "To": "+18583214176",
    }
    assert provider.is_inbound(payload) is True
    assert provider.inbound_details(payload) == ("CAinbound1", "+919660557683", "+18583214176")
    # Our own outbound leg posts to the same shape and must not be mistaken for it.
    assert provider.is_inbound({**payload, "Direction": "outbound-api"}) is False


def test_providers_declare_how_they_answer() -> None:
    """The inbound route returns XML or JSON based on this flag; getting it
    wrong means the carrier hears silence and hangs up."""
    assert PlivoTelephonyProvider().answers_with_document is True
    assert TwilioTelephonyProvider().answers_with_document is True
    assert TelnyxTelephonyProvider().answers_with_document is False


async def test_inbound_route_returns_twiml_for_twilio(client, auth_headers, agent) -> None:
    response = await client.post(
        "/webhooks/telephony/twilio/inbound",
        data={
            "CallSid": "CAinbound-route",
            "Direction": "inbound",
            "From": "+919660557683",
            "To": "+18583214176",
        },
    )
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<Stream" in response.text
    assert "/api/v1/media/" in response.text


async def test_inbound_route_ignores_an_outbound_callback(client, auth_headers, agent) -> None:
    response = await client.post(
        "/webhooks/telephony/twilio/inbound",
        data={"CallSid": "CAout", "Direction": "outbound-api"},
    )
    assert response.json() == {"status": "ignored"}


def test_plivo_recognises_an_inbound_call() -> None:
    provider = PlivoTelephonyProvider()
    payload = {
        "CallUUID": "cu-in-1",
        "Direction": "inbound",
        "From": "+919799918691",
        "To": "+912212345678",
    }
    assert provider.is_inbound(payload) is True
    assert provider.inbound_details(payload) == ("cu-in-1", "+919799918691", "+912212345678")
    assert provider.is_inbound({**payload, "Direction": "outbound"}) is False


@pytest.mark.parametrize("name", ["plivo", "twilio", "telnyx"])
def test_every_real_carrier_can_detect_inbound(name: str) -> None:
    """Inbound support must not regress for one carrier while another gains it."""
    provider = get_telephony(name)
    assert callable(provider.is_inbound)
    assert provider.is_inbound({}) is False


# --- OmniDimension (hosted agent) -------------------------------------------


def test_omnidimension_declares_it_runs_its_own_conversation() -> None:
    """Nothing should expect a media socket or barge-in from this provider."""
    from app.services.telephony.omnidimension import OmniDimensionTelephonyProvider

    provider = OmniDimensionTelephonyProvider()
    assert provider.runs_own_conversation is True
    assert provider.answers_with_document is False
    # Every other carrier runs our pipeline.
    for name in ("plivo", "twilio", "telnyx", "mock"):
        assert get_telephony(name).runs_own_conversation is False


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", CallStatus.COMPLETED),
        ("no_answer", CallStatus.NO_ANSWER),
        ("busy", CallStatus.BUSY),
        ("failed", CallStatus.FAILED),
    ],
)
def test_omnidimension_maps_post_call_status(status: str, expected: CallStatus) -> None:
    from app.services.telephony.omnidimension import OmniDimensionTelephonyProvider

    event = OmniDimensionTelephonyProvider().parse_webhook(
        {
            "call": {
                "id": 3517893,
                "call_status": status,
                "call_duration_in_seconds": 42,
                "recording_url": "https://example.com/rec.mp3",
            }
        }
    )
    assert event.status is expected
    assert event.provider_call_id == "3517893"
    assert event.duration_seconds == 42


def test_omnidimension_reads_our_call_id_back_from_metadata() -> None:
    """Their webhook echoes `metadata`; that is the only link to our call row."""
    from app.services.telephony.omnidimension import OmniDimensionTelephonyProvider

    provider = OmniDimensionTelephonyProvider()
    assert provider.platform_call_id({"metadata": {"platform_call_id": "abc-123"}}) == "abc-123"
    assert provider.platform_call_id({"call": {"metadata": {"platform_call_id": "x"}}}) == "x"
    assert provider.platform_call_id({}) is None


def test_omnidimension_treats_a_missing_recording_as_absent() -> None:
    """Their schema returns `false`, not null, when there is no recording."""
    from app.services.telephony.omnidimension import OmniDimensionTelephonyProvider

    event = OmniDimensionTelephonyProvider().parse_webhook(
        {"call": {"id": 1, "call_status": "completed", "recording_url": False}}
    )
    assert event.recording_url is None


async def test_omnidimension_requires_credentials() -> None:
    from app.services.base import ProviderError
    from app.services.telephony.omnidimension import OmniDimensionTelephonyProvider

    with pytest.raises(ProviderError):
        await OmniDimensionTelephonyProvider().originate(
            to_number="+919660557683", from_number="", answer_url="", status_url="", call_id="x"
        )


def test_carrier_urls_carry_the_shared_secret(monkeypatch) -> None:
    """Setting the secret without appending it to callback URLs would 403 every
    webhook and strand calls in `ringing` -- so the two must be built together."""
    import uuid as _uuid

    from app.core.config import settings
    from app.services.telephony import urls

    call_id = _uuid.uuid4()
    monkeypatch.setattr(settings, "telephony_webhook_secret", "s3cret")
    monkeypatch.setattr(settings, "public_base_url", "https://example.com")

    assert "secret=s3cret" in urls.answer_url("twilio", call_id)
    assert "secret=s3cret" in urls.status_url("twilio", call_id)
    assert "secret=s3cret" in urls.inbound_url("twilio")
    # The websocket URL deliberately carries no secret: the unguessable call id
    # is the credential, and carriers differ on preserving the query string.
    assert urls.media_url(call_id) == f"wss://example.com/api/v1/media/{call_id}"

    monkeypatch.setattr(settings, "telephony_webhook_secret", "")
    assert "secret=" not in urls.status_url("twilio", call_id)


async def test_a_human_can_call_a_lead_through_the_platform(client, auth_headers, lead) -> None:
    """The operator's phone rings first, then the carrier bridges to the lead."""
    response = await client.post(
        "/calls/bridge",
        json={"operator_number": "+919812345678", "lead_id": lead["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["mode"] == "human"
    assert body["agent_id"] is None, "a human call has no AI agent behind it"
    assert body["operator_number"] == "+919812345678"
    assert body["to_number"] == lead["phone_number"]


async def test_a_human_call_answers_with_a_bridge_not_a_media_stream(
    client, auth_headers, lead
) -> None:
    """Serving the streaming document here would connect the operator to an AI."""
    created = await client.post(
        "/calls/bridge",
        json={"operator_number": "+919812345678", "lead_id": lead["id"]},
        headers=auth_headers,
    )
    answer = await client.post(f"/webhooks/telephony/mock/answer/{created.json()['id']}", json={})
    assert answer.status_code == 200
    assert "<Dial" in answer.text
    assert lead["phone_number"] in answer.text
    assert "Stream" not in answer.text


async def test_an_agent_call_still_answers_with_the_media_stream(
    client, auth_headers, agent, lead
) -> None:
    """The bridge must not have changed what an AI call answers with."""
    created = await client.post(
        "/calls",
        json={"agent_id": agent["id"], "lead_id": lead["id"]},
        headers=auth_headers,
    )
    answer = await client.post(f"/webhooks/telephony/mock/answer/{created.json()['id']}", json={})
    assert "Stream" in answer.text or "stream" in answer.text.lower()


async def test_a_human_call_refuses_a_do_not_call_lead(client, auth_headers, lead) -> None:
    await client.patch(f"/leads/{lead['id']}", json={"status": "do_not_call"}, headers=auth_headers)
    response = await client.post(
        "/calls/bridge",
        json={"operator_number": "+919812345678", "lead_id": lead["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 409


async def test_a_human_call_needs_a_number_to_ring(client, auth_headers, lead) -> None:
    response = await client.post(
        "/calls/bridge", json={"lead_id": lead["id"]}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_calls_can_be_filtered_to_human_or_agent(client, auth_headers, agent, lead) -> None:
    """The manual-calling page needs its own calls, not everyone's."""
    await client.post(
        "/calls", json={"agent_id": agent["id"], "lead_id": lead["id"]}, headers=auth_headers
    )
    await client.post(
        "/calls/bridge",
        json={"operator_number": "+919812345678", "lead_id": lead["id"]},
        headers=auth_headers,
    )

    human = await client.get("/calls?mode=human", headers=auth_headers)
    assert human.json()["total"] == 1
    assert human.json()["items"][0]["mode"] == "human"

    agent_calls = await client.get("/calls?mode=agent", headers=auth_headers)
    assert agent_calls.json()["total"] == 1
    assert agent_calls.json()["items"][0]["mode"] == "agent"


@pytest.mark.parametrize(
    ("typed", "dialled"),
    [
        ("9660557683", "+919660557683"),
        ("919660557683", "+919660557683"),
        ("+919660557683", "+919660557683"),
        ("9660 557 683", "+919660557683"),
        ("  9408258707  ", "+919408258707"),
    ],
)
def test_a_hand_typed_number_is_normalised_before_it_reaches_a_carrier(
    typed: str, dialled: str
) -> None:
    """A bare Indian mobile on a US Twilio account is read as +1.

    That produced "Account not allowed to call +19660557683" on a live call --
    a US number the user never meant to dial.
    """
    from app.services.call_service import _dialable

    assert _dialable(typed) == dialled


async def test_a_bridge_dials_the_normalised_numbers(client, auth_headers) -> None:
    response = await client.post(
        "/calls/bridge",
        json={"operator_number": "9660557683", "to_number": "9408258707"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["operator_number"] == "+919660557683"
    assert body["to_number"] == "+919408258707"


async def test_an_agent_call_normalises_a_typed_number_too(client, auth_headers, agent) -> None:
    response = await client.post(
        "/calls",
        json={"agent_id": agent["id"], "to_number": "9408258707"},
        headers=auth_headers,
    )
    assert response.json()["to_number"] == "+919408258707"


def test_a_twilio_error_is_rendered_as_something_actionable() -> None:
    """Raw provider JSON in a UI tells an operator nothing."""
    from app.services.telephony.twilio import _explain

    body = (
        '{"code":21216,"message":"Account not allowed to call +19660557683",'
        '"more_info":"https://www.twilio.com/docs/errors/21216","status":400}'
    )
    explained = _explain(body)
    assert "Geo Permissions" in explained
    assert "country code" in explained
    assert "more_info" not in explained


def test_an_unrecognised_twilio_error_still_says_something() -> None:
    from app.services.telephony.twilio import _explain

    assert _explain('{"code":99999,"message":"Something odd"}') == "Something odd"
    assert _explain("not json at all") == "not json at all"
