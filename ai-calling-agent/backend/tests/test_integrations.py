"""The CRM integration surface: API keys in, signed webhooks out."""

from __future__ import annotations

import hashlib
import hmac
import json

from httpx import AsyncClient

from app.services.integration_service import sign
from tests.conftest import REGISTRATION


async def test_an_api_key_authenticates_the_same_api_a_browser_uses(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A CRM must be able to call in without a browser login."""
    created = await client.post("/integrations/keys", json={"name": "Zoho"}, headers=auth_headers)
    assert created.status_code == 201, created.text
    raw = created.json()["key"]
    assert raw.startswith("cak_")

    listed = await client.get("/leads", headers={"X-API-Key": raw})
    assert listed.status_code == 200, listed.text


async def test_the_plaintext_key_is_never_returned_again(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Storing only the hash is the whole point; a list endpoint must not leak it."""
    await client.post("/integrations/keys", json={"name": "Salesforce"}, headers=auth_headers)
    listed = await client.get("/integrations/keys", headers=auth_headers)
    assert listed.status_code == 200
    for key in listed.json():
        assert "key" not in key
        assert "hashed_key" not in key


async def test_a_revoked_key_stops_working(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/integrations/keys", json={"name": "Temporary"}, headers=auth_headers
    )
    raw = created.json()["key"]
    assert (await client.get("/leads", headers={"X-API-Key": raw})).status_code == 200

    await client.delete(f"/integrations/keys/{created.json()['id']}", headers=auth_headers)
    assert (await client.get("/leads", headers={"X-API-Key": raw})).status_code == 401


async def test_a_made_up_key_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/leads", headers={"X-API-Key": "cak_nonsense"})).status_code == 401


async def test_an_api_key_cannot_reach_another_organization(
    client: AsyncClient, auth_headers: dict[str, str], lead: dict
) -> None:
    """A key is the tenant boundary; leaking across it would be the worst bug here."""
    other = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "crm@example.com", "organization_name": "Other Co"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    their_key = (
        await client.post("/integrations/keys", json={"name": "Theirs"}, headers=other_headers)
    ).json()["key"]

    # Their key sees their own (empty) leads, never ours.
    theirs = await client.get("/leads", headers={"X-API-Key": their_key})
    assert theirs.status_code == 200
    assert theirs.json()["total"] == 0

    leaked = await client.get(f"/leads/{lead['id']}", headers={"X-API-Key": their_key})
    assert leaked.status_code == 404


async def test_a_webhook_must_be_https(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Payloads carry lead names and phone numbers."""
    response = await client.post(
        "/integrations/webhooks",
        json={"url": "http://crm.example.com/hook"},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_registering_a_webhook_returns_a_signing_secret_once(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/integrations/webhooks",
        json={"url": "https://crm.example.com/hook", "events": ["call.completed"]},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["secret"]

    listed = await client.get("/integrations/webhooks", headers=auth_headers)
    for endpoint in listed.json():
        assert "secret" not in endpoint, "the secret must not be re-servable"


def test_the_signature_is_reproducible_by_the_receiver() -> None:
    """A receiver has to be able to recompute this, or it cannot trust us."""
    secret = "shhh"
    body = json.dumps({"event": "call.completed"}, separators=(",", ":")).encode()
    timestamp = "1700000000"

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    assert sign(secret, body, timestamp) == expected


def test_the_timestamp_is_inside_the_signature() -> None:
    """Otherwise a captured delivery can be replayed against the endpoint."""
    body = b"{}"
    assert sign("s", body, "1") != sign("s", body, "2")


async def test_events_are_advertised(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/integrations/events", headers=auth_headers)
    assert "call.completed" in response.json()
    assert "lead.qualified" in response.json()
