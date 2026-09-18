"""Conversation state machine.

The states give the LLM a sense of where it is in the call, and give us a place
to hang rules (only ask for details once qualified, only close after the pitch).
Transitions are advisory, not a cage: if the customer jumps topic, the state
follows them rather than forcing them back through the script.
"""

from __future__ import annotations

import enum
import re


class ConversationState(enum.StrEnum):
    GREETING = "greeting"
    INTRODUCTION = "introduction"
    DISCOVER_REQUIREMENT = "discover_requirement"
    QUALIFY = "qualify"
    ANSWER_QUESTIONS = "answer_questions"
    HANDLE_OBJECTIONS = "handle_objections"
    CALL_TO_ACTION = "call_to_action"
    COLLECT_DETAILS = "collect_details"
    CONFIRM_INTEREST = "confirm_interest"
    COMPLETE = "complete"


LINEAR_ORDER = [
    ConversationState.GREETING,
    ConversationState.INTRODUCTION,
    ConversationState.DISCOVER_REQUIREMENT,
    ConversationState.QUALIFY,
    ConversationState.CALL_TO_ACTION,
    ConversationState.COLLECT_DETAILS,
    ConversationState.CONFIRM_INTEREST,
]
# COMPLETE is deliberately absent above. Walking the list used to end the call
# after six turns whether or not the customer was mid-sentence -- the call only
# completes when the customer closes it or the model decides it is done.

STATE_GUIDANCE = {
    ConversationState.GREETING: ("Greet warmly and confirm you are speaking to the right person."),
    ConversationState.INTRODUCTION: (
        "Say who you are and why you are calling, in one short sentence."
    ),
    ConversationState.DISCOVER_REQUIREMENT: (
        "Find out what the customer actually needs. Ask open questions."
    ),
    ConversationState.QUALIFY: ("Work through the qualification questions, one at a time."),
    ConversationState.ANSWER_QUESTIONS: (
        "Answer the customer's question directly using known facts only."
    ),
    ConversationState.HANDLE_OBJECTIONS: (
        "Acknowledge the concern first, then respond to it briefly."
    ),
    ConversationState.CALL_TO_ACTION: ("Propose the concrete next step and ask for agreement."),
    ConversationState.COLLECT_DETAILS: (
        "Collect the contact details you still need, one field at a time."
    ),
    ConversationState.CONFIRM_INTEREST: (
        "Before closing: tell them a specialist from the team will reach out with "
        "the details, and ask plainly whether they would like that. Wait for their "
        "answer -- it decides whether this lead is followed up."
    ),
    ConversationState.COMPLETE: (
        "Close warmly. Thank them by name, confirm what happens next, and say "
        "goodbye. Never hang up without saying goodbye."
    ),
}

# Deliberately code-mixed: customers say these in English, Hindi, or both.
_QUESTION = re.compile(
    r"(\?|^(what|how|why|when|where|which|who|can|could|do|does|is|are)\b"
    r"|\b(kya|kaise|kyun|kab|kahan|kitna|kitne|batao|bataiye)\b)",
    re.IGNORECASE,
)
_OBJECTION = re.compile(
    r"\b(expensive|costly|too much|budget|not interested|no need|already (have|using)"
    r"|later|busy|think about|mehnga|mehanga|nahi chahiye|abhi nahi|baad mein|paisa)\b",
    re.IGNORECASE,
)
# Only unmistakable farewells and hard declines. A bare "thank you" is ordinary
# politeness mid-call in Indian English, and treating it as a goodbye cut live
# conversations off in the middle of a sentence.
_CLOSING = re.compile(
    r"\b(bye|good\s?bye|alvida|khuda\s?hafiz|hang up|hanging up"
    r"|rakhta hoon|rakhti hoon|phone rakh\w*|call rakh\w*|band kar\w*"
    r"|no thanks|no thank you|not interested at all)\b",
    re.IGNORECASE,
)
_AGREEMENT = re.compile(
    r"\b(yes|yeah|sure|ok|okay|interested|send|share|haan|haa|bilkul|theek hai|thik hai)\b",
    re.IGNORECASE,
)


def customer_is_closing(text: str) -> bool:
    return bool(_CLOSING.search(text))


def next_state(
    current: ConversationState, customer_text: str, *, turn_count: int
) -> ConversationState:
    """Pick the next state from what the customer just said.

    Topic changes win over script order -- a question gets answered when it is
    asked, not after the pitch finishes.
    """
    if customer_is_closing(customer_text):
        return ConversationState.COMPLETE
    if _OBJECTION.search(customer_text):
        return ConversationState.HANDLE_OBJECTIONS
    if _QUESTION.search(customer_text):
        return ConversationState.ANSWER_QUESTIONS

    # After a detour, rejoin the script rather than looping in the detour.
    if current in {ConversationState.ANSWER_QUESTIONS, ConversationState.HANDLE_OBJECTIONS}:
        return (
            ConversationState.CALL_TO_ACTION
            if _AGREEMENT.search(customer_text) or turn_count >= 4
            else ConversationState.DISCOVER_REQUIREMENT
        )

    if current == ConversationState.CALL_TO_ACTION and _AGREEMENT.search(customer_text):
        return ConversationState.COLLECT_DETAILS

    if current in LINEAR_ORDER:
        index = LINEAR_ORDER.index(current)
        if index + 1 < len(LINEAR_ORDER):
            return LINEAR_ORDER[index + 1]
    return current
