"""Support sessions on customer accounts.

These tests are about what a session *cannot* do. The happy path is three
lines; the value is in the refusals, because every one of them is a way the
feature could quietly become a privilege-escalation path or a way to spend a
customer's money under their own name.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.activity import ActivityEvent
from app.models.billing import PlatformEvent
from app.models.impersonation import ImpersonationSession
from app.models.user import User
from tests.conftest import REGISTRATION

REASON = "Customer reports the agent hangs up on Hindi calls"
CUSTOMER = {
    **REGISTRATION,
    "email": "customer@example.com",
    "organization_name": "Customer Co",
}


async def _make_admin(db_session, email: str = REGISTRATION["email"]) -> User:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()
    return user


async def _customer(client: AsyncClient) -> dict:
    response = await client.post("/auth/register", json=CUSTOMER)
    assert response.status_code == 201, response.text
    return response.json()["user"]


async def _open_session(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user_id: str,
    *,
    mode: str = "read_only",
    reason: str = REASON,
) -> dict:
    response = await client.post(
        "/platform/impersonation",
        headers=auth_headers,
        json={"user_id": user_id, "reason": reason, "mode": mode},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _enter(client: AsyncClient, handoff: dict) -> dict:
    response = await client.post("/auth/impersonation/exchange", json={"code": handoff["code"]})
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_session_opens_and_reads_the_customers_account(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    await _make_admin(db_session)
    customer = await _customer(client)

    handoff = await _open_session(client, auth_headers, customer["id"])
    entered = await _enter(client, handoff)

    assert entered["user"]["email"] == CUSTOMER["email"]
    assert entered["session"]["read_only"] is True
    assert entered["session"]["admin_email"] == REGISTRATION["email"]

    headers = {"Authorization": f"Bearer {entered['access_token']}"}
    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    # The identity is the customer's, which is the whole point: staff see
    # exactly what the customer sees, not an admin's view of it.
    assert me.json()["email"] == CUSTOMER["email"]


async def test_a_handoff_code_cannot_be_used_twice(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """A code that works twice is a code worth stealing from a log."""
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"])

    await _enter(client, handoff)
    replay = await client.post("/auth/impersonation/exchange", json={"code": handoff["code"]})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "handoff_invalid"


async def test_an_expired_handoff_code_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"])

    session = (
        await db_session.execute(
            select(ImpersonationSession).where(
                ImpersonationSession.id == uuid.UUID(handoff["session"]["id"])
            )
        )
    ).scalar_one()
    session.handoff_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post("/auth/impersonation/exchange", json={"code": handoff["code"]})
    assert response.status_code == 401


async def test_a_read_only_session_cannot_write_anything(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """The method guard, not the capability guard.

    This asserts the backstop: an endpoint nobody remembered to decorate with
    a capability is still refused, because the refusal keys off the HTTP
    method rather than off a list somebody has to maintain.
    """
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"])
    entered = await _enter(client, handoff)
    headers = {"Authorization": f"Bearer {entered['access_token']}"}

    response = await client.patch("/auth/me", headers=headers, json={"full_name": "Changed"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "impersonation_read_only"

    # And the name really is unchanged -- the refusal is not cosmetic.
    me = await client.get("/auth/me", headers=headers)
    assert me.json()["full_name"] != "Changed"


async def test_a_read_write_session_can_write_but_never_spend(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """The line that no reason box unlocks.

    A read-write session exists so staff can fix a misconfiguration. Buying
    credits in the customer's name is not a misconfiguration, and the ledger
    would record the customer as having bought them.
    """
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"], mode="read_write")
    entered = await _enter(client, handoff)
    headers = {"Authorization": f"Bearer {entered['access_token']}"}

    allowed = await client.patch("/auth/me", headers=headers, json={"full_name": "Fixed Name"})
    assert allowed.status_code == 200

    spend = await client.post(
        "/billing/orders", headers=headers, json={"package_id": str(customer["id"])}
    )
    assert spend.status_code == 403
    assert spend.json()["error"]["code"] == "impersonation_forbidden"


async def test_ending_a_session_kills_its_token_immediately(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """The reason a session is a row and not only a signed claim.

    If revocation waited for the token to expire, "end this session" would
    mean "end it within half an hour", which is not what an admin clicking
    that button believes.
    """
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"])
    entered = await _enter(client, handoff)
    headers = {"Authorization": f"Bearer {entered['access_token']}"}

    assert (await client.get("/auth/me", headers=headers)).status_code == 200

    revoked = await client.post(
        f"/platform/impersonation/{handoff['session']['id']}/end", headers=auth_headers
    )
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False

    after = await client.get("/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "impersonation_ended"


async def test_an_expired_session_stops_working_without_a_sweeper(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"])
    entered = await _enter(client, handoff)
    headers = {"Authorization": f"Bearer {entered['access_token']}"}

    session = (
        await db_session.execute(
            select(ImpersonationSession).where(
                ImpersonationSession.id == uuid.UUID(handoff["session"]["id"])
            )
        )
    ).scalar_one()
    session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    db_session.expire_all()

    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_staff_can_leave_their_own_read_only_session(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Exiting is a POST in a session that refuses POSTs, so it needs its own
    way out. Without one, staff close the tab and the session runs its clock."""
    await _make_admin(db_session)
    customer = await _customer(client)
    handoff = await _open_session(client, auth_headers, customer["id"])
    entered = await _enter(client, handoff)
    headers = {"Authorization": f"Bearer {entered['access_token']}"}

    left = await client.post("/auth/impersonation/end", headers=headers)
    assert left.status_code == 200
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_platform_admins_cannot_be_impersonated(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Otherwise support staff could borrow an owner's platform rights, and
    the audit trail would name the owner."""
    await _make_admin(db_session)
    await _customer(client)
    other = await _make_admin(db_session, email=CUSTOMER["email"])

    response = await client.post(
        "/platform/impersonation",
        headers=auth_headers,
        json={"user_id": str(other.id), "reason": REASON, "mode": "read_only"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("reason", ["", "test", "looking"])
async def test_a_throwaway_reason_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], db_session, reason: str
) -> None:
    """A box that accepts "test" trains people to type "test"."""
    await _make_admin(db_session)
    customer = await _customer(client)
    response = await client.post(
        "/platform/impersonation",
        headers=auth_headers,
        json={"user_id": customer["id"], "reason": reason, "mode": "read_only"},
    )
    assert response.status_code == 422


async def test_the_customer_is_told_in_their_own_timeline(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """An internal log the customer cannot see is not having told them."""
    await _make_admin(db_session)
    customer = await _customer(client)
    await _open_session(client, auth_headers, customer["id"])

    activity = (
        (
            await db_session.execute(
                select(ActivityEvent).where(ActivityEvent.action == "account.accessed_by_support")
            )
        )
        .scalars()
        .all()
    )
    assert len(activity) == 1
    assert activity[0].reason == REASON
    assert REGISTRATION["email"] in (activity[0].actor_label or "")

    events = (
        (
            await db_session.execute(
                select(PlatformEvent).where(PlatformEvent.action == "impersonation.started")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].target == CUSTOMER["email"]


async def test_only_platform_admins_can_open_a_session(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """auth_headers here belongs to an ordinary customer -- no admin flag set."""
    response = await client.post(
        "/platform/impersonation",
        headers=auth_headers,
        json={"user_id": "00000000-0000-0000-0000-000000000000", "reason": REASON},
    )
    assert response.status_code == 403


async def test_the_customer_can_read_the_support_visit_themselves(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """The row existing is not the same as the customer being able to see it.

    This is the endpoint that turns "we logged it" into "we told them", so it
    is checked from the customer's own session, not an admin's.
    """
    await _make_admin(db_session)
    customer = await _customer(client)
    await _open_session(client, auth_headers, customer["id"])

    login = await client.post(
        "/auth/login",
        json={"email": CUSTOMER["email"], "password": CUSTOMER["password"]},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    response = await client.get("/settings/activity", headers=headers)
    assert response.status_code == 200
    visits = [row for row in response.json() if row["action"] == "account.accessed_by_support"]
    assert len(visits) == 1
    assert visits[0]["actor_type"] == "platform_admin"
    assert visits[0]["reason"] == REASON


async def test_one_customer_cannot_read_anothers_activity(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """The timeline is scoped by organization, so an account only ever sees
    its own visits -- including when the reason text names someone else."""
    await _make_admin(db_session)
    customer = await _customer(client)
    await _open_session(client, auth_headers, customer["id"])

    # auth_headers is the first organization; the visit was to the second.
    response = await client.get("/settings/activity", headers=auth_headers)
    assert response.status_code == 200
    assert all(row["action"] != "account.accessed_by_support" for row in response.json())
