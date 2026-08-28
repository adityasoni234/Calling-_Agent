from __future__ import annotations

import pytest

from app.agents.state import ConversationState, customer_is_closing, next_state


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mujhe kya milega?", ConversationState.ANSWER_QUESTIONS),
        ("what does it cost", ConversationState.ANSWER_QUESTIONS),
        ("ye bahut mehnga hai", ConversationState.HANDLE_OBJECTIONS),
        ("not interested right now", ConversationState.HANDLE_OBJECTIONS),
        ("ok thank you bye", ConversationState.COMPLETE),
    ],
)
def test_customer_topic_wins_over_script_order(
    text: str, expected: ConversationState
) -> None:
    assert next_state(ConversationState.INTRODUCTION, text, turn_count=1) is expected


def test_script_advances_on_a_neutral_reply() -> None:
    assert (
        next_state(ConversationState.INTRODUCTION, "haan bataiye aage", turn_count=1)
        is ConversationState.ANSWER_QUESTIONS
    )
    assert (
        next_state(ConversationState.GREETING, "yes speaking", turn_count=0)
        is ConversationState.INTRODUCTION
    )


def test_conversation_rejoins_the_script_after_a_detour() -> None:
    assert (
        next_state(ConversationState.HANDLE_OBJECTIONS, "haan theek hai", turn_count=1)
        is ConversationState.CALL_TO_ACTION
    )


def test_agreement_at_the_call_to_action_collects_details() -> None:
    assert (
        next_state(ConversationState.CALL_TO_ACTION, "haan bhej dijiye", turn_count=5)
        is ConversationState.COLLECT_DETAILS
    )


def test_closing_detection_is_bilingual() -> None:
    assert customer_is_closing("theek hai bye")
    assert customer_is_closing("thanks, goodbye")
    assert not customer_is_closing("ek minute ruko")
