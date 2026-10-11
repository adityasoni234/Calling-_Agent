"""The bandit: reward shape, policy behaviour, and the safety rails."""

from __future__ import annotations

import random
import uuid

from app.agents.variants import apply_variants
from app.models.agent import Agent
from app.models.call import Call, CallStatus
from app.models.lead import Lead, LeadStatus
from app.models.learning import AgentVariant, VariantKind, VariantStatus
from app.services.learning_service import MIN_TRIALS_TO_JUDGE, reward_for


def make_call(**kwargs) -> Call:
    defaults = dict(
        status=CallStatus.COMPLETED,
        duration_seconds=90,
        extracted_data={},
        organization_id=uuid.uuid4(),
        direction="outbound",
        provider="mock",
        from_number="+10000000000",
        to_number="+919876543210",
    )
    defaults.update(kwargs)
    return Call(**defaults)


def make_lead(status: LeadStatus = LeadStatus.CONTACTED) -> Lead:
    return Lead(
        organization_id=uuid.uuid4(), name="Test", phone_number="+919876543210", status=status
    )


# --- the reward -------------------------------------------------------


def test_a_failed_call_earns_nothing() -> None:
    assert reward_for(make_call(status=CallStatus.NO_ANSWER, duration_seconds=0), None) == 0.0


def test_an_opt_in_outscores_a_long_chat_without_one() -> None:
    """The thing we optimise for is someone saying yes, not time on the phone."""
    opted_in = reward_for(
        make_call(duration_seconds=40, extracted_data={"followup_opt_in": True}), None
    )
    just_long = reward_for(make_call(duration_seconds=300, extracted_data={}), None)
    assert opted_in > just_long


def test_a_longer_conversation_beats_an_instant_hangup() -> None:
    """A purely binary reward would rate these the same and learn nothing."""
    assert reward_for(make_call(duration_seconds=90), None) > reward_for(
        make_call(duration_seconds=4), None
    )


def test_getting_someone_to_opt_out_is_punished() -> None:
    """It costs a lead permanently, whatever else the call achieved."""
    good = make_call(duration_seconds=120, extracted_data={"interest_level": "high"})
    assert reward_for(good, make_lead(LeadStatus.DO_NOT_CALL)) < reward_for(good, make_lead())


def test_reward_always_lands_between_zero_and_one() -> None:
    """A reward outside [0,1] would corrupt every Beta posterior it touches."""
    extremes = [
        make_call(duration_seconds=0, extracted_data={}),
        make_call(
            duration_seconds=10_000,
            extracted_data={"followup_opt_in": True, "interest_level": "high", "_turns": 500},
        ),
    ]
    for call in extremes:
        for lead in (None, make_lead(LeadStatus.QUALIFIED), make_lead(LeadStatus.DO_NOT_CALL)):
            assert 0.0 <= reward_for(call, lead) <= 1.0


# --- the policy -------------------------------------------------------


def arm(successes: float, trials: int, content: str = "hello") -> AgentVariant:
    return AgentVariant(
        organization_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind=VariantKind.GREETING,
        content=content,
        status=VariantStatus.ACTIVE,
        successes=successes,
        trials=trials,
    )


def test_an_untested_arm_is_not_rated_as_perfect() -> None:
    """Without smoothing, one lucky call would read as a 100% winner."""
    assert arm(1, 1).mean_reward < 0.9
    assert arm(0, 0).mean_reward == 0.5


def test_more_evidence_moves_the_estimate_closer_to_the_truth() -> None:
    assert abs(arm(80, 100).mean_reward - 0.8) < abs(arm(4, 5).mean_reward - 0.8)


def test_thompson_sampling_favours_the_better_arm_but_still_explores() -> None:
    """Exploitation without exploration never discovers a better phrasing."""
    random.seed(7)
    good, weak = arm(80, 100), arm(20, 100)
    picks = 0
    for _ in range(400):
        g = random.betavariate(good.successes + 1, good.trials - good.successes + 1)
        w = random.betavariate(weak.successes + 1, weak.trials - weak.successes + 1)
        picks += g > w
    assert picks > 380, "the better arm must dominate"

    random.seed(7)
    fresh, known = arm(0, 0), arm(50, 100)
    explored = 0
    for _ in range(400):
        f = random.betavariate(fresh.successes + 1, fresh.trials - fresh.successes + 1)
        k = random.betavariate(known.successes + 1, known.trials - known.successes + 1)
        explored += f > k
    assert 60 < explored < 340, "an untried arm must get real but not unlimited traffic"


def test_an_arm_is_never_judged_before_it_has_enough_calls() -> None:
    """Retiring on four calls would discard good phrasings as noise."""
    assert MIN_TRIALS_TO_JUDGE >= 20


# --- applying a variant -----------------------------------------------


def test_applying_a_variant_does_not_rewrite_the_saved_agent() -> None:
    """The agent row is the user's configuration, not the experiment's scratchpad."""
    agent = Agent(
        organization_id=uuid.uuid4(),
        name="Aditya",
        greeting="original greeting",
        objection_handling=[{"objection": "too busy", "response": "original response"}],
    )
    chosen = {
        "greeting:": arm(0, 0, "experimental greeting"),
        "objection:too busy": AgentVariant(
            organization_id=agent.organization_id,
            agent_id=uuid.uuid4(),
            kind=VariantKind.OBJECTION,
            slot="too busy",
            content="experimental response",
            status=VariantStatus.ACTIVE,
        ),
    }

    trial = apply_variants(agent, chosen)

    assert trial.greeting == "experimental greeting"
    assert trial.objection_handling[0]["response"] == "experimental response"
    assert agent.greeting == "original greeting", "the saved agent must be untouched"
    assert agent.objection_handling[0]["response"] == "original response"


def test_an_agent_with_no_variants_is_returned_unchanged() -> None:
    agent = Agent(organization_id=uuid.uuid4(), name="Aditya", greeting="hello")
    assert apply_variants(agent, {}) is agent
