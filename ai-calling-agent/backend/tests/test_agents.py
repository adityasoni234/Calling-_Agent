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


async def test_generate_drafts_an_agent_from_a_brief(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """The builder returns a draft to review; it must never save on its own."""
    response = await client.post(
        "/agents/generate",
        json={
            "brief": (
                "We are a stock advisory service. Call people who signed up on our "
                "website and book a fifteen minute demo of the platform."
            ),
            "company_name": "Stockwala",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["draft"]["name"]
    assert body["draft"]["company_name"] == "Stockwala"
    assert "forbidden rules" in body["notes"]

    # Nothing was persisted.
    assert (await client.get("/agents", headers=auth_headers)).json()["total"] == 0


async def test_generate_rejects_a_brief_that_says_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/agents/generate", json={"brief": "call people"}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_language_preference_and_recording_reach_the_prompt(
    client: AsyncClient, auth_headers: dict[str, str], agent: dict
) -> None:
    prompt = (await client.get(f"/agents/{agent['id']}/prompt", headers=auth_headers)).json()[
        "system_prompt"
    ]
    assert "which language" in prompt.lower()
    assert "recorded" in prompt.lower()

    off = await client.patch(
        f"/agents/{agent['id']}",
        json={"ask_language_preference": False, "record_calls": False},
        headers=auth_headers,
    )
    assert off.status_code == 200
    prompt = (await client.get(f"/agents/{agent['id']}/prompt", headers=auth_headers)).json()[
        "system_prompt"
    ]
    assert "which language" not in prompt.lower()
    assert "recorded" not in prompt.lower()


def test_blueprint_coerces_malformed_model_output() -> None:
    """A model returning an array as a string must not lose the whole config.

    Seen live: `secondary_objectives` came back as one string carrying fragments
    of the tool-call envelope, and the entire generation was rejected.
    """
    from app.services.agent_builder import AgentBlueprint

    blueprint = AgentBlueprint.model_validate(
        {
            "name": "Kabir",
            "role_title": "Membership Advisor",
            "personality": "Warm and encouraging.",
            "primary_objective": "Book a free trial session",
            "secondary_objectives": (
                '<parameter name="item">Learn their goal</parameter>\nAsk when they can visit'
            ),
            "greeting": "Hi, this is Kabir from the gym.",
            "qualification_questions": ["What is your fitness goal?"],
            "forbidden_rules": None,
            "ending_rules": [{"item": "End once a trial is booked"}],
            "objection_handling": [
                {"concern": "too costly", "answer": "We have a free trial first."},
                {"objection": "", "response": "dropped"},
            ],
        }
    )
    assert blueprint.secondary_objectives == ["Learn their goal", "Ask when they can visit"]
    assert blueprint.forbidden_rules == []
    assert blueprint.ending_rules == ["End once a trial is booked"]
    assert blueprint.objection_handling[0].objection == "too costly"
    assert len(blueprint.objection_handling) == 1


def test_a_job_word_is_never_used_as_the_persona_name() -> None:
    """A caller who hears "Hi, this is manager" knows it is a bot."""
    from app.services.agent_builder import AgentBlueprint

    for role in ["manager", "Sales Executive", "AI assistant", "  agent "]:
        blueprint = AgentBlueprint(
            name=role,
            role_title="Advisor",
            personality="Warm.",
            primary_objective="Qualify.",
            greeting="Hello.",
        )
        assert blueprint.name.isalpha()
        assert blueprint.name.lower() not in {
            "manager",
            "sales executive",
            "ai assistant",
            "agent",
        }


def test_a_real_persona_name_survives_untouched() -> None:
    from app.services.agent_builder import AgentBlueprint

    blueprint = AgentBlueprint(
        name="  Riya ",
        role_title="Advisor",
        personality="Warm.",
        primary_objective="Qualify.",
        greeting="Hello.",
    )
    assert blueprint.name == "Riya"
