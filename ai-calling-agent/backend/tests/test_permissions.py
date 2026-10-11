"""Role enforcement. Previously roles existed but nothing checked them."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.permissions import CAPABILITIES, Capability, can
from app.models.user import User, UserRole
from tests.conftest import REGISTRATION


async def _as(db_session, role: UserRole) -> None:
    """Demote the signed-in test user, so one fixture covers every role."""
    user = (
        await db_session.execute(select(User).where(User.email == REGISTRATION["email"]))
    ).scalar_one()
    user.role = role
    await db_session.commit()


# --- the table itself -------------------------------------------------


def test_a_viewer_can_look_but_not_spend() -> None:
    assert can(UserRole.VIEWER, Capability.READ)
    assert not can(UserRole.VIEWER, Capability.PLACE_CALLS)
    assert not can(UserRole.VIEWER, Capability.BUY_CREDITS)


def test_an_operator_works_the_phones_but_cannot_reconfigure() -> None:
    assert can(UserRole.OPERATOR, Capability.PLACE_CALLS)
    assert can(UserRole.OPERATOR, Capability.MANAGE_LEADS)
    assert not can(UserRole.OPERATOR, Capability.MANAGE_AGENTS)
    assert not can(UserRole.OPERATOR, Capability.MANAGE_INTEGRATIONS)


def test_only_an_owner_touches_money_or_the_team() -> None:
    for role in (UserRole.VIEWER, UserRole.OPERATOR, UserRole.ADMIN):
        assert not can(role, Capability.BUY_CREDITS), role
        assert not can(role, Capability.MANAGE_BILLING), role
        assert not can(role, Capability.MANAGE_TEAM), role
    assert can(UserRole.OWNER, Capability.BUY_CREDITS)
    assert can(UserRole.OWNER, Capability.MANAGE_BILLING)


def test_each_role_contains_the_one_below_it() -> None:
    """A privilege ladder with a gap is how an admin ends up unable to work."""
    from app.core.permissions import CAPABILITIES

    ladder = [UserRole.VIEWER, UserRole.OPERATOR, UserRole.ADMIN, UserRole.OWNER]
    for lower, higher in zip(ladder, ladder[1:], strict=False):
        assert CAPABILITIES[lower] <= CAPABILITIES[higher], f"{higher} lost {lower}'s rights"


# --- enforcement on real endpoints ------------------------------------


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.ADMIN])
async def test_only_permitted_roles_can_place_a_call(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, lead: dict, db_session, role
) -> None:
    """A call costs real money, so this is the guard that matters most."""
    await _as(db_session, role)
    response = await client.post(
        "/calls", json={"agent_id": agent["id"], "lead_id": lead["id"]}, headers=auth_headers
    )
    if can(role, Capability.PLACE_CALLS):
        assert response.status_code != 403, response.text
    else:
        assert response.status_code == 403


async def test_a_viewer_cannot_start_a_campaign(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, db_session
) -> None:
    """A campaign dials a whole list; a read-only account must not."""
    await _as(db_session, UserRole.VIEWER)
    created = await client.post(
        "/campaigns", json={"name": "x", "agent_id": agent["id"]}, headers=auth_headers
    )
    assert created.status_code == 403


async def test_an_operator_cannot_revoke_the_api_keys(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Someone working the phones must not be able to break every integration."""
    await _as(db_session, UserRole.OPERATOR)
    response = await client.post("/integrations/keys", json={"name": "x"}, headers=auth_headers)
    assert response.status_code == 403


async def test_an_operator_cannot_rewrite_an_agent(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, db_session
) -> None:
    """What the agent says is a compliance surface, not a daily-work surface."""
    await _as(db_session, UserRole.OPERATOR)
    response = await client.patch(
        f"/agents/{agent['id']}", json={"name": "Changed"}, headers=auth_headers
    )
    assert response.status_code == 403


async def test_a_viewer_can_still_read(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Locking a viewer out of reading would make the role pointless."""
    await _as(db_session, UserRole.VIEWER)
    for path in ("/leads", "/calls", "/campaigns", "/agents"):
        assert (await client.get(path, headers=auth_headers)).status_code == 200, path


async def test_an_owner_is_unaffected(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict, db_session
) -> None:
    """The guards must not have broken the role everyone currently has."""
    await _as(db_session, UserRole.OWNER)
    created = await client.post(
        "/campaigns", json={"name": "owner campaign", "agent_id": agent["id"]}, headers=auth_headers
    )
    assert created.status_code == 201, created.text


async def test_no_customer_role_can_reach_the_platform_api(
    client: AsyncClient, auth_headers: dict[str, str], db_session
) -> None:
    """Platform access is a separate flag; no role may grant it."""
    for role in (UserRole.VIEWER, UserRole.OPERATOR, UserRole.ADMIN, UserRole.OWNER):
        await _as(db_session, role)
        response = await client.get("/platform/organizations", headers=auth_headers)
        assert response.status_code == 403, role


# --- the separated admin roles ----------------------------------------


def test_finance_cannot_read_customer_conversations() -> None:
    """A billing dispute is settled from the ledger, not by reading calls."""
    assert can(UserRole.FINANCE_ADMIN, Capability.MANAGE_BILLING)
    assert not can(UserRole.FINANCE_ADMIN, Capability.VIEW_CONVERSATIONS)
    assert not can(UserRole.FINANCE_ADMIN, Capability.PLACE_CALLS)


def test_support_can_read_everything_and_spend_nothing() -> None:
    """The mirror image of finance, on purpose."""
    assert can(UserRole.SUPPORT_ADMIN, Capability.VIEW_CONVERSATIONS)
    assert not can(UserRole.SUPPORT_ADMIN, Capability.MANAGE_BILLING)
    assert not can(UserRole.SUPPORT_ADMIN, Capability.BUY_CREDITS)


def test_operations_runs_the_pipes_and_touches_no_money() -> None:
    assert can(UserRole.OPERATIONS_ADMIN, Capability.MANAGE_INTEGRATIONS)
    assert can(UserRole.OPERATIONS_ADMIN, Capability.MANAGE_SETTINGS)
    assert not can(UserRole.OPERATIONS_ADMIN, Capability.MANAGE_BILLING)
    assert not can(UserRole.OPERATIONS_ADMIN, Capability.MANAGE_TEAM)


def test_only_the_owner_manages_the_team_and_the_money() -> None:
    for capability in (Capability.MANAGE_TEAM, Capability.MANAGE_BILLING):
        holders = [r for r in UserRole if can(r, capability)]
        assert UserRole.OWNER in holders
        assert UserRole.OPERATOR not in holders
        assert UserRole.VIEWER not in holders
    assert not can(UserRole.ADMIN, Capability.MANAGE_TEAM)


def test_every_role_has_an_explicit_capability_set() -> None:
    """A role missing from the table silently has no permissions at all."""
    for role in UserRole:
        assert role in CAPABILITIES, f"{role} is not in the capability table"
        assert CAPABILITIES[role], f"{role} has no capabilities"
