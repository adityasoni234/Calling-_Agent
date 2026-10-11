from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import REGISTRATION


async def test_register_creates_owner_and_organization(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json=REGISTRATION)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["user"]["email"] == REGISTRATION["email"]
    assert body["user"]["role"] == "owner"
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert body["tokens"]["expires_in"] > 0
    # The password must never travel back to the client in any form.
    assert "password" not in response.text and "hashed" not in response.text


async def test_register_rejects_duplicate_email(client: AsyncClient, registered: dict) -> None:
    response = await client.post("/auth/register", json={**REGISTRATION, "full_name": "Other"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={**REGISTRATION, "password": "short"})
    assert response.status_code == 422

    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"][0]["field"] == "password"


async def test_login_returns_tokens(client: AsyncClient, registered: dict) -> None:
    response = await client.post(
        "/auth/login",
        json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
    )
    assert response.status_code == 200
    assert response.json()["tokens"]["access_token"]


async def test_login_with_wrong_password_is_rejected(client: AsyncClient, registered: dict) -> None:
    response = await client.post(
        "/auth/login", json={"email": REGISTRATION["email"], "password": "wrong-password-1"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_for_unknown_email_gives_the_same_error(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}
    )
    assert response.status_code == 401
    # Identical to the wrong-password case, so the endpoint is not an enumeration oracle.
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_missing"


async def test_me_rejects_a_forged_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_invalid"


async def test_me_returns_user_and_organization(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["email"] == REGISTRATION["email"]
    assert body["organization"]["name"] == REGISTRATION["organization_name"]
    assert body["organization"]["slug"] == "acme-sales"


async def test_update_profile(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.patch("/auth/me", json={"full_name": "Priya S."}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == "Priya S."


async def test_refresh_rotates_the_token(client: AsyncClient, registered: dict) -> None:
    original = registered["tokens"]["refresh_token"]

    response = await client.post("/auth/refresh", json={"refresh_token": original})
    assert response.status_code == 200

    rotated = response.json()["refresh_token"]
    assert rotated != original

    # The rotated token works...
    assert (await client.post("/auth/refresh", json={"refresh_token": rotated})).status_code == 200


async def test_replaying_a_rotated_token_kills_every_session(
    client: AsyncClient, registered: dict
) -> None:
    original = registered["tokens"]["refresh_token"]
    rotated = (await client.post("/auth/refresh", json={"refresh_token": original})).json()[
        "refresh_token"
    ]

    replay = await client.post("/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "token_reuse_detected"

    # Reuse detection must revoke the whole chain, not just the replayed token.
    followup = await client.post("/auth/refresh", json={"refresh_token": rotated})
    assert followup.status_code == 401


async def test_logout_revokes_the_refresh_token(client: AsyncClient, registered: dict) -> None:
    token = registered["tokens"]["refresh_token"]

    assert (await client.post("/auth/logout", json={"refresh_token": token})).status_code == 200
    assert (await client.post("/auth/refresh", json={"refresh_token": token})).status_code == 401


async def test_change_password_revokes_sessions(
    client: AsyncClient, registered: dict, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/auth/change-password",
        json={"current_password": REGISTRATION["password"], "password": "brand-new-pass-7"},
        headers=auth_headers,
    )
    assert response.status_code == 200

    stale = await client.post(
        "/auth/refresh", json={"refresh_token": registered["tokens"]["refresh_token"]}
    )
    assert stale.status_code == 401

    logged_in = await client.post(
        "/auth/login", json={"email": REGISTRATION["email"], "password": "brand-new-pass-7"}
    )
    assert logged_in.status_code == 200


async def test_change_password_requires_the_current_one(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/auth/change-password",
        json={"current_password": "not-the-password", "password": "brand-new-pass-7"},
        headers=auth_headers,
    )
    assert response.status_code == 401


async def test_organization_slugs_stay_unique(client: AsyncClient, registered: dict) -> None:
    response = await client.post(
        "/auth/register", json={**REGISTRATION, "email": "second@example.com"}
    )
    assert response.status_code == 201
    assert response.json()["user"]["organization_id"] != registered["user"]["organization_id"]


async def test_seed_script_applies_the_same_password_policy_as_the_api() -> None:
    """The CLI must not be a way around the password rules.

    An account created by `make seed` is reachable from the internet the moment
    a tunnel is running, so a weak password here is a real exposure.
    """
    from scripts.seed import seed

    assert await seed("someone@example.com", "12345678", "Weak", "Weak Co") == 2
    assert await seed("someone@example.com", "short1!", "Short", "Short Co") == 2
    assert await seed("someone@example.com", "correct-horse-9", "Fine", "Fine Co") == 0


async def test_the_platform_flag_reaches_the_client(client: AsyncClient, db_session) -> None:
    """The admin UI gates on this; omitting it hid the panel from its own admin."""
    from sqlalchemy import select

    from app.models.user import User
    from tests.conftest import REGISTRATION

    registered = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "flag@example.com", "organization_name": "Flag Co"},
    )
    headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}

    # A customer is not platform staff.
    assert registered.json()["user"]["is_platform_admin"] is False
    assert (await client.get("/auth/me", headers=headers)).json()["is_platform_admin"] is False

    user = (
        await db_session.execute(select(User).where(User.email == "flag@example.com"))
    ).scalar_one()
    user.is_platform_admin = True
    await db_session.commit()

    assert (await client.get("/auth/me", headers=headers)).json()["is_platform_admin"] is True
