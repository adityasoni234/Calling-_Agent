"""Provider credentials: encryption, masking, and never leaking plaintext.

The point of this file is the negative assertions. A secret that round-trips
correctly but also appears in an API response, a log line or an audit row has
not been protected -- it has been copied.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.crypto import SecretUnreadable, decrypt, encrypt, mask
from app.models.billing import PlatformEvent
from app.models.provider import ProviderConnection, ProviderStatus
from app.models.user import User
from app.services.provider_service import ProviderService
from tests.conftest import REGISTRATION

TOKEN = "SK_live_7f3a9c2b1d8e4f6a0b5c"


async def _as_admin(db_session) -> User:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()
    return user


# --- the primitives ---------------------------------------------------


def test_a_secret_round_trips_but_does_not_resemble_itself() -> None:
    ciphertext = encrypt(TOKEN)
    assert ciphertext != TOKEN
    assert TOKEN not in ciphertext
    assert decrypt(ciphertext) == TOKEN


def test_encrypting_is_not_deterministic() -> None:
    """Two identical keys must not produce identical ciphertext.

    Otherwise anyone reading the table learns which tenants share a key.
    """
    assert encrypt(TOKEN) != encrypt(TOKEN)


def test_an_empty_secret_stays_empty_rather_than_becoming_a_blob() -> None:
    assert encrypt("") == ""
    assert decrypt("") == ""


def test_a_mask_shows_the_tail_an_operator_compares_against_the_dashboard() -> None:
    masked = mask(TOKEN)
    assert masked.endswith(TOKEN[-4:])
    assert TOKEN[:8] not in masked
    assert len(masked) < len(TOKEN) + 12


def test_a_short_secret_is_masked_completely() -> None:
    """Showing four of six characters is not masking."""
    assert set(mask("abc")) == {"•"}


def test_an_undecryptable_secret_raises_rather_than_returning_nothing() -> None:
    """A rotation must not silently become calls placed with no credentials."""
    with pytest.raises(SecretUnreadable):
        decrypt("not-a-fernet-token")


# --- the service ------------------------------------------------------


async def test_saving_credentials_stores_only_ciphertext(db_session, auth_headers) -> None:
    admin = await _as_admin(db_session)
    service = ProviderService(db_session)
    await service.upsert(
        slug="twilio",
        secrets={"account_sid": "AC123", "auth_token": TOKEN},
        actor_id=admin.id,
    )

    row = (
        await db_session.execute(
            select(ProviderConnection).where(ProviderConnection.slug == "twilio")
        )
    ).scalar_one()
    assert TOKEN not in str(row.secrets)
    assert row.secrets["auth_token"] != TOKEN
    assert row.secret_hints["auth_token"].endswith(TOKEN[-4:])
    assert row.secrets_rotated_at is not None
    assert row.secrets_rotated_by_id == admin.id


async def test_saving_never_claims_healthy_without_a_check(db_session, auth_headers) -> None:
    """Green on save would show a mistyped key as working."""
    await _as_admin(db_session)
    connection = await ProviderService(db_session).upsert(
        slug="deepgram", secrets={"api_key": TOKEN}
    )
    assert connection.status is ProviderStatus.DEGRADED
    assert connection.status is not ProviderStatus.HEALTHY


async def test_a_blank_field_leaves_the_existing_key_alone(db_session, auth_headers) -> None:
    """Editing one field in a form must not wipe the others.

    The form shows masked placeholders; submitting them back as blanks is
    the normal case, not a request to clear everything.
    """
    service = ProviderService(db_session)
    await service.upsert(slug="twilio", secrets={"account_sid": "AC123", "auth_token": TOKEN})
    await service.upsert(slug="twilio", secrets={"account_sid": "AC999", "auth_token": ""})

    secrets = await service.credentials("twilio")
    assert secrets["account_sid"] == "AC999"
    assert secrets["auth_token"] == TOKEN  # untouched


async def test_enabling_without_the_required_fields_is_refused(db_session, auth_headers) -> None:
    from app.core.errors import ValidationFailedError

    with pytest.raises(ValidationFailedError):
        await ProviderService(db_session).upsert(
            slug="twilio", secrets={"account_sid": "AC123"}, is_enabled=True
        )


async def test_an_unknown_provider_is_refused(db_session, auth_headers) -> None:
    from app.core.errors import ValidationFailedError

    with pytest.raises(ValidationFailedError):
        await ProviderService(db_session).upsert(slug="nonsense", secrets={"k": "v"})


async def test_a_disabled_provider_hands_out_no_credentials(db_session, auth_headers) -> None:
    service = ProviderService(db_session)
    connection = await service.upsert(slug="cartesia", secrets={"api_key": TOKEN}, is_enabled=True)
    assert await service.credentials("cartesia") != {}

    await service.set_enabled(connection.id, False)
    assert await service.credentials("cartesia") == {}


async def test_removing_a_required_key_disables_the_connection(db_session, auth_headers) -> None:
    service = ProviderService(db_session)
    connection = await service.upsert(
        slug="twilio", secrets={"account_sid": "AC1", "auth_token": TOKEN}
    )
    updated = await service.delete_secret(connection.id, "auth_token")
    assert updated.is_enabled is False
    assert updated.status is ProviderStatus.UNCONFIGURED


# --- the API ----------------------------------------------------------


async def test_the_provider_api_is_admin_only(client, auth_headers) -> None:
    assert (await client.get("/platform/providers")).status_code == 401
    assert (await client.get("/platform/providers", headers=auth_headers)).status_code == 403


async def test_the_api_lists_integrations_that_are_not_set_up_yet(
    client, auth_headers, db_session
) -> None:
    """An admin should see that Plivo exists, not discover it in the source."""
    await _as_admin(db_session)
    response = await client.get("/platform/providers", headers=auth_headers)
    assert response.status_code == 200
    by_slug = {p["slug"]: p for p in response.json()}
    assert {"twilio", "plivo", "anthropic", "deepgram", "cartesia", "razorpay"} <= set(by_slug)
    assert by_slug["plivo"]["status"] == "unconfigured"
    assert by_slug["twilio"]["required_fields"] == ["account_sid", "auth_token"]


async def test_the_api_never_returns_a_plaintext_secret(client, auth_headers, db_session) -> None:
    """The assertion this whole module exists for."""
    await _as_admin(db_session)
    saved = await client.put(
        "/platform/providers",
        json={"slug": "anthropic", "secrets": {"api_key": TOKEN}},
        headers=auth_headers,
    )
    assert saved.status_code == 200
    assert TOKEN not in saved.text
    assert saved.json()["secret_hints"]["api_key"].endswith(TOKEN[-4:])

    listed = await client.get("/platform/providers", headers=auth_headers)
    assert TOKEN not in listed.text


async def test_the_audit_row_records_which_key_changed_not_its_value(
    client, auth_headers, db_session
) -> None:
    await _as_admin(db_session)
    await client.put(
        "/platform/providers",
        json={"slug": "deepgram", "secrets": {"api_key": TOKEN}},
        headers=auth_headers,
    )
    rows = await db_session.execute(
        select(PlatformEvent).where(PlatformEvent.action == "provider.credentials_saved")
    )
    event = rows.scalars().first()
    assert event is not None
    assert event.target == "deepgram"
    assert "api_key" in (event.detail or "")
    assert TOKEN not in (event.detail or "")


async def test_checking_an_unknown_connection_is_a_404(client, auth_headers, db_session) -> None:
    await _as_admin(db_session)
    response = await client.post(f"/platform/providers/{uuid.uuid4()}/check", headers=auth_headers)
    assert response.status_code == 404
