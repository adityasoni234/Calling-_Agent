from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import AGENT_PAYLOAD, REGISTRATION


async def test_create_and_list_agent(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict
) -> None:
    assert agent["name"] == "Riya"
    assert agent["language"] == "auto"

    listing = await client.get("/agents", headers=auth_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == agent["id"]


async def test_agent_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/agents", json=AGENT_PAYLOAD)
    assert response.status_code == 401


async def test_update_agent(client: AsyncClient, auth_headers: dict[str, str], agent: dict) -> None:
    response = await client.patch(
        f"/agents/{agent['id']}",
        json={"greeting": "Namaste, main Riya bol rahi hoon.", "temperature": 0.4},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["greeting"].startswith("Namaste")
    assert response.json()["temperature"] == 0.4


async def test_agent_rejects_unknown_fields(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict
) -> None:
    response = await client.patch(
        f"/agents/{agent['id']}", json={"nonsense": True}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_prompt_preview_contains_the_configuration(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict
) -> None:
    response = await client.get(f"/agents/{agent['id']}/prompt", headers=auth_headers)
    assert response.status_code == 200

    prompt = response.json()["system_prompt"]
    assert "Riya" in prompt
    assert "Acme Telecom" in prompt
    assert "Book a product demo" in prompt
    assert "What is your monthly call volume?" in prompt
    assert "Never promise a discount" in prompt
    # The one-question-at-a-time rule is not optional.
    assert "one question at a time" in prompt.lower()
    assert response.json()["estimated_tokens"] > 0


async def test_agents_are_scoped_to_their_organization(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict
) -> None:
    other = await client.post(
        "/auth/register",
        json={**REGISTRATION, "email": "other@example.com", "organization_name": "Other Co"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    assert (await client.get("/agents", headers=other_headers)).json()["total"] == 0
    leaked = await client.get(f"/agents/{agent['id']}", headers=other_headers)
    assert leaked.status_code == 404


async def test_delete_agent(client: AsyncClient, auth_headers: dict[str, str], agent: dict) -> None:
    response = await client.delete(f"/agents/{agent['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert (await client.get("/agents", headers=auth_headers)).json()["total"] == 0
