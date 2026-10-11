"""Meta lead ads: signature verification, deduplication, token handling.

The important assertions are that an unsigned webhook cannot write a lead,
that a re-delivered lead does not become a second one, and that the access
token never leaves the server.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select

from app.core.crypto import decrypt, encrypt, mask
from app.models.meta import (
    MetaAsset,
    MetaAssetKind,
    MetaConnection,
    MetaConnectionStatus,
    MetaLeadEvent,
)
from app.models.organization import Organization
from app.models.user import User
from app.services.meta_service import MetaService, verify_signature
from tests.conftest import REGISTRATION

TOKEN = "EAAG_long_lived_meta_token_9f3a7c"


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _connection(db_session, org_id) -> MetaConnection:
    connection = MetaConnection(
        organization_id=org_id,
        meta_user_id="1234567890",
        meta_user_name="Aditya",
        access_token=encrypt(TOKEN),
        token_hint=mask(TOKEN),
        scopes=["leads_retrieval", "pages_show_list"],
        status=MetaConnectionStatus.CONNECTED,
    )
    db_session.add(connection)
    await db_session.flush()
    return connection


def _signed(body: dict, secret: str) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, f"sha256={digest}"


# --- signature verification -------------------------------------------


def test_a_correct_signature_verifies(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    raw, header = _signed({"object": "page"}, "app-secret")
    assert verify_signature(raw, header) is True


def test_a_wrong_secret_does_not_verify(monkeypatch) -> None:
    """An unverified lead webhook writes rows into a customer's CRM."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    raw, header = _signed({"object": "page"}, "someone-elses-secret")
    assert verify_signature(raw, header) is False


def test_a_tampered_body_does_not_verify(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    _, header = _signed({"object": "page"}, "app-secret")
    assert verify_signature(b'{"object":"evil"}', header) is False


def test_a_missing_or_malformed_header_does_not_verify(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    assert verify_signature(b"{}", None) is False
    assert verify_signature(b"{}", "md5=abc") is False
    assert verify_signature(b"{}", "") is False


def test_nothing_verifies_when_no_secret_is_configured(monkeypatch) -> None:
    """Fail closed. An unconfigured app must not accept every webhook."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "")
    raw, header = _signed({"object": "page"}, "anything")
    assert verify_signature(raw, header) is False


# --- tokens -----------------------------------------------------------


async def test_the_token_is_stored_encrypted_and_only_hinted(db_session, auth_headers) -> None:
    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    await db_session.commit()

    assert TOKEN not in connection.access_token
    assert decrypt(connection.access_token) == TOKEN
    assert connection.token_hint.endswith(TOKEN[-4:])
    assert TOKEN[:10] not in connection.token_hint


async def test_an_expired_token_is_not_usable(db_session, auth_headers) -> None:
    from datetime import UTC, datetime, timedelta

    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    connection.token_expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    assert connection.is_usable is False


async def test_a_live_token_is_usable(db_session, auth_headers) -> None:
    from datetime import UTC, datetime, timedelta

    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    connection.token_expires_at = datetime.now(UTC) + timedelta(days=30)
    await db_session.commit()
    assert connection.is_usable is True


# --- lead events ------------------------------------------------------


async def test_a_redelivered_lead_does_not_become_a_second_lead(db_session, auth_headers) -> None:
    """Meta re-delivers. The leadgen id is the deduplication key."""
    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    db_session.add(
        MetaAsset(
            organization_id=org.id,
            connection_id=connection.id,
            kind=MetaAssetKind.PAGE,
            meta_id="page-1",
            name="My Page",
        )
    )
    await db_session.commit()

    service = MetaService(db_session)
    entry = {"id": "page-1"}
    change = {"field": "leadgen", "value": {"leadgen_id": "lead-1", "form_id": "form-1"}}

    first = await service.record_event(entry, change)
    second = await service.record_event(entry, change)
    assert first is not None
    assert first.id == second.id

    rows = list(
        (
            await db_session.execute(
                select(MetaLeadEvent).where(MetaLeadEvent.leadgen_id == "lead-1")
            )
        ).scalars()
    )
    assert len(rows) == 1


async def test_an_event_is_recorded_before_it_is_processed(db_session, auth_headers) -> None:
    """A crash mid-processing must not lose the lead."""
    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    db_session.add(
        MetaAsset(
            organization_id=org.id,
            connection_id=connection.id,
            kind=MetaAssetKind.PAGE,
            meta_id="page-2",
            name="Page",
        )
    )
    await db_session.commit()

    event = await MetaService(db_session).record_event(
        {"id": "page-2"},
        {"field": "leadgen", "value": {"leadgen_id": "lead-2", "ad_id": "ad-9"}},
    )
    assert event is not None
    assert event.processed_at is None  # recorded, not yet processed
    assert event.raw["change"]["value"]["ad_id"] == "ad-9"


async def test_an_event_for_an_unknown_page_is_kept_not_discarded(db_session, auth_headers) -> None:
    """A lead for a page we cannot attribute is still evidence something arrived."""
    event = await MetaService(db_session).record_event(
        {"id": "page-nobody-owns"},
        {"field": "leadgen", "value": {"leadgen_id": "orphan-1"}},
    )
    assert event is not None
    assert event.organization_id is None


async def test_an_event_without_a_leadgen_id_is_ignored(db_session, auth_headers) -> None:
    assert await MetaService(db_session).record_event({"id": "p"}, {"value": {}}) is None


# --- the API ----------------------------------------------------------


async def test_the_meta_api_is_closed_to_anonymous_callers(client) -> None:
    assert (await client.get("/meta/status")).status_code == 401
    assert (await client.post("/meta/connect")).status_code == 401


async def test_status_says_when_the_platform_is_not_set_up(
    client, auth_headers, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "")
    response = await client.get("/meta/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["platform_configured"] is False
    assert any("Meta app id" in b for b in body["blockers"])
    assert "leads_retrieval" in body["required_scopes"]


async def test_the_webhook_refuses_an_unsigned_delivery(client, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "app-secret")
    response = await client.post(
        "/meta/webhook",
        json={"object": "page", "entry": []},
    )
    assert response.status_code == 403


async def test_the_verification_handshake_requires_the_right_token(client, monkeypatch) -> None:
    """Echoing without checking lets anyone register our endpoint."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "meta_verify_token", "the-token")

    wrong = await client.get(
        "/meta/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "x"},
    )
    assert wrong.status_code == 403

    right = await client.get(
        "/meta/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "the-token",
            "hub.challenge": "challenge-123",
        },
    )
    assert right.status_code == 200
    assert right.text == "challenge-123"


async def test_the_status_response_never_contains_the_token(
    client, auth_headers, db_session
) -> None:
    """The assertion the encryption exists for."""
    org = await _org(db_session)
    await _connection(db_session, org.id)
    await db_session.commit()

    response = await client.get("/meta/status", headers=auth_headers)
    assert TOKEN not in response.text
    connection = response.json()["connections"][0]
    assert connection["token_hint"].endswith(TOKEN[-4:])
    assert "access_token" not in connection


async def test_disconnecting_destroys_the_token(client, auth_headers, db_session) -> None:
    """A credential kept after someone asked to disconnect is one we should not have."""
    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    await db_session.commit()
    connection_id = connection.id

    response = await client.delete(f"/meta/connections/{connection_id}", headers=auth_headers)
    assert response.status_code == 200
    # The delete happened in the request's own session; this one still holds
    # the row in its identity map until told otherwise.
    db_session.expire_all()
    assert await db_session.get(MetaConnection, connection_id) is None


async def test_one_tenant_cannot_touch_anothers_connection(
    client, auth_headers, db_session
) -> None:
    org = await _org(db_session)
    connection = await _connection(db_session, org.id)
    await db_session.commit()

    rival = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "rival4@example.com", "organization_name": "R4"},
    )
    theirs = {"Authorization": f"Bearer {rival.json()['tokens']['access_token']}"}
    response = await client.delete(f"/meta/connections/{connection.id}", headers=theirs)
    assert response.status_code == 404
