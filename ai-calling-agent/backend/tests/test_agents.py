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


def test_a_dead_api_key_is_reported_as_a_key_problem() -> None:
    """ "Try again" is useless advice when every retry fails identically."""
    from app.services.agent_builder import _explain_failure

    message = _explain_failure(
        Exception('[anthropic] 401: {"error":{"message":"invalid x-api-key"}}')
    )
    assert "API key" in message
    assert "Settings" in message
    assert "Try again, or write it by hand" not in message


def test_an_out_of_credit_account_is_reported_as_billing() -> None:
    from app.services.agent_builder import _explain_failure

    assert "credit" in _explain_failure(Exception("[cartesia] 402: Insufficient credits")).lower()


def test_an_unknown_failure_keeps_the_generic_advice() -> None:
    from app.services.agent_builder import _explain_failure

    assert "write it by hand" in _explain_failure(Exception("something odd happened"))


async def test_a_long_pasted_prompt_is_accepted(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A written system prompt is the best input we can get; 2,000 chars refused it."""
    brief = (
        "# STOCKVALA — AI VOICE SALES CLOSER\n"
        "## Master System Prompt | CRM + MT5 Manager\n\n" + ("Detailed instruction line.\n" * 400)
    )
    assert len(brief) > 2000

    response = await client.post("/agents/generate", json={"brief": brief}, headers=auth_headers)
    assert response.status_code != 422, response.text


async def test_a_brief_beyond_the_hard_limit_says_which_field_is_too_long(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """ "Input validation failed" leaves the user guessing what to change."""
    response = await client.post(
        "/agents/generate", json={"brief": "x" * 40_001}, headers=auth_headers
    )
    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert "brief" in message.lower()
    assert "longer than allowed" in message
    assert message != "Input validation failed"


async def test_a_missing_field_is_named_too(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post("/agents/generate", json={}, headers=auth_headers)
    assert response.status_code == 422
    assert "brief" in response.json()["error"]["message"].lower()


def test_placeholder_values_are_recognised() -> None:
    """An agent named "<UNKNOWN>" would introduce itself that way on a live call."""
    from app.services.agent_builder import _is_placeholder

    for bad in ["<UNKNOWN>", "<unknown>", " N/A ", "not specified", "None provided"]:
        assert _is_placeholder(bad), bad
    for good in ["Kabir", "Senior Consultant", "Riya"]:
        assert not _is_placeholder(good), good


def test_an_over_long_list_is_trimmed_not_rejected() -> None:
    """A rich brief yields six objectives; binning the whole draft over one is wrong."""
    from app.services.agent_builder import AgentBlueprint

    blueprint = AgentBlueprint.model_validate(
        {
            "name": "Kabir",
            "role_title": "Consultant",
            "personality": "Warm.",
            "primary_objective": "Book a demo.",
            "greeting": "Hello.",
            "secondary_objectives": [f"objective {i}" for i in range(9)],
            "qualification_questions": [f"question {i}" for i in range(11)],
            "forbidden_rules": [f"rule {i}" for i in range(14)],
        }
    )
    assert len(blueprint.secondary_objectives) == 5
    assert len(blueprint.qualification_questions) == 6
    assert len(blueprint.forbidden_rules) == 8
    # The highest-ranked items are the ones kept.
    assert blueprint.secondary_objectives[0] == "objective 0"


def test_over_long_text_is_trimmed_not_rejected() -> None:
    from app.services.agent_builder import AgentBlueprint

    blueprint = AgentBlueprint.model_validate(
        {
            "name": "Kabir",
            "role_title": "x" * 400,
            "personality": "y" * 900,
            "primary_objective": "Book a demo.",
            "greeting": "z" * 700,
        }
    )
    assert len(blueprint.role_title) <= 120
    assert len(blueprint.personality) <= 600
    assert len(blueprint.greeting) <= 300
