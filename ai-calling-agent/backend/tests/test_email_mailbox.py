"""Customer-owned sending mailboxes.

The assertions that matter: no token ever reaches an API response, a
disconnect destroys the grant rather than parking it, and the daily limit
is refused against rather than discovered when the provider suspends the
mailbox.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.crypto import decrypt, encrypt
from app.models.email_account import EmailAccount, MailboxProvider, MailboxStatus
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import REGISTRATION

REFRESH = "1//0gRefreshTokenThatSendsMailForever"
ACCESS = "ya29.AccessTokenGoodForOneHour"


async def _org(db_session) -> Organization:
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    return await db_session.get(Organization, user.organization_id)


async def _account(db_session, org_id, **kw) -> EmailAccount:
    account = EmailAccount(
        organization_id=org_id,
        provider=MailboxProvider.GMAIL,
        address=kw.pop("address", "owner@gmail.com"),
        display_name="Aditya",
        access_token=encrypt(ACCESS),
        refresh_token=encrypt(REFRESH),
        scopes=["https://www.googleapis.com/auth/gmail.send"],
        daily_limit=500,
        **kw,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


# --- tokens -----------------------------------------------------------


async def test_tokens_are_stored_encrypted(db_session, auth_headers) -> None:
    org = await _org(db_session)
    account = await _account(db_session, org.id)
    assert REFRESH not in account.refresh_token
    assert ACCESS not in account.access_token
    assert decrypt(account.refresh_token) == REFRESH


async def test_no_token_ever_appears_in_an_api_response(client, auth_headers, db_session) -> None:
    """A refresh token can send mail as that person indefinitely."""
    org = await _org(db_session)
    await _account(db_session, org.id)

    response = await client.get("/email/mailboxes", headers=auth_headers)
    assert response.status_code == 200
    assert REFRESH not in response.text
    assert ACCESS not in response.text
    account = response.json()["accounts"][0]
    assert "refresh_token" not in account
    assert "access_token" not in account
    # Not even a masked hint: there is no reason to show any part of it.
    assert not any("token" in key for key in account)


async def test_disconnecting_destroys_the_grant(client, auth_headers, db_session) -> None:
    """A token kept after someone asked to disconnect is not ours to hold."""
    org = await _org(db_session)
    account = await _account(db_session, org.id)
    account_id = account.id

    response = await client.delete(f"/email/mailboxes/{account_id}", headers=auth_headers)
    assert response.status_code == 200
    db_session.expire_all()
    assert await db_session.get(EmailAccount, account_id) is None


# --- quota ------------------------------------------------------------


async def test_the_daily_limit_is_reported_before_it_is_hit(
    client, auth_headers, db_session
) -> None:
    org = await _org(db_session)
    await _account(db_session, org.id, sent_today=120)

    body = (await client.get("/email/mailboxes", headers=auth_headers)).json()
    account = body["accounts"][0]
    assert account["daily_limit"] == 500
    assert account["sent_today"] == 120
    assert account["remaining_today"] == 380
    # The ceilings are stated rather than discovered when a mailbox is
    # suspended for a day.
    assert body["limits"]["gmail_personal"] == 500


async def test_an_exhausted_mailbox_is_not_usable(db_session, auth_headers) -> None:
    org = await _org(db_session)
    account = await _account(db_session, org.id, sent_today=500)
    assert account.remaining_today == 0
    assert account.is_usable is False


async def test_sending_refuses_rather_than_risking_a_suspension(db_session, auth_headers) -> None:
    """Exceeding the ceiling suspends the whole mailbox for 24 hours."""
    from app.services.email.base import OutboundEmail
    from app.services.email.mailbox import MailboxEmail

    org = await _org(db_session)
    account = await _account(db_session, org.id, sent_today=500)

    result = await MailboxEmail(account, "token").send(
        OutboundEmail(
            to_address="someone@example.com",
            subject="Hi",
            text_body="Hello",
            from_address=account.address,
        )
    )
    assert result.accepted is False
    assert result.error_code == "daily_limit"


# --- defaults and isolation -------------------------------------------


async def test_the_first_mailbox_becomes_the_default(db_session, auth_headers) -> None:
    org = await _org(db_session)
    first = await _account(db_session, org.id, address="first@gmail.com")
    assert first.is_default is True


async def test_choosing_a_default_unsets_the_others(client, auth_headers, db_session) -> None:
    org = await _org(db_session)
    first = await _account(db_session, org.id, address="first@gmail.com")
    second = await _account(db_session, org.id, address="second@gmail.com", is_default=False)

    # Read the ids before expire_all() detaches the instances.
    first_id, second_id = first.id, second.id
    response = await client.post(f"/email/mailboxes/{second_id}/default", headers=auth_headers)
    assert response.status_code == 200
    db_session.expire_all()
    assert (await db_session.get(EmailAccount, second_id)).is_default is True
    assert (await db_session.get(EmailAccount, first_id)).is_default is False


async def test_an_expired_mailbox_is_not_usable(db_session, auth_headers) -> None:
    """Only the customer can fix a revoked grant; we cannot refresh past it."""
    org = await _org(db_session)
    account = await _account(db_session, org.id)
    account.status = MailboxStatus.EXPIRED
    await db_session.commit()
    assert account.is_usable is False


async def test_one_tenant_cannot_touch_anothers_mailbox(client, auth_headers, db_session) -> None:
    org = await _org(db_session)
    account = await _account(db_session, org.id)

    rival = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "rival5@example.com", "organization_name": "R5"},
    )
    theirs = {"Authorization": f"Bearer {rival.json()['tokens']['access_token']}"}
    response = await client.delete(f"/email/mailboxes/{account.id}", headers=theirs)
    assert response.status_code == 404


async def test_the_mailbox_api_is_closed_to_anonymous_callers(client) -> None:
    assert (await client.get("/email/mailboxes")).status_code == 401
    assert (await client.post("/email/mailboxes/connect?provider=gmail")).status_code == 401


async def test_an_unknown_provider_is_refused(client, auth_headers) -> None:
    response = await client.post("/email/mailboxes/connect?provider=hotmail", headers=auth_headers)
    assert response.status_code == 404


async def test_the_callback_refuses_an_unknown_state(client) -> None:
    """A replayed or forged callback must not create a mailbox."""
    response = await client.get(
        "/email/mailbox/callback", params={"code": "abc", "state": "never-issued"}
    )
    assert response.status_code == 200
    assert "expired or was already used" in response.text
