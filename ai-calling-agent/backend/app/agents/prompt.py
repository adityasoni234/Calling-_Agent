"""Builds the system prompt from an agent's configuration.

Two rules shape this file:

1. The persona block is byte-stable for a given agent, so it can be sent as a
   cached prefix. Anything that changes per turn (state, retrieved context) is
   appended after it or passed as a user message.
2. Nothing here invents facts. If the knowledge base has no answer, the prompt
   tells the model to say so.
"""

from __future__ import annotations

import re

from app.agents.state import STATE_GUIDANCE, ConversationState
from app.models.agent import Agent, AgentLanguage

LANGUAGE_RULES = {
    AgentLanguage.ENGLISH: "Speak English only. Keep it simple and clear.",
    AgentLanguage.HINDI: "Hindi mein baat karein, Roman script mein likhein (Devanagari nahi).",
    AgentLanguage.HINGLISH: (
        "Speak natural Hinglish - Hindi grammar with common English words mixed in, "
        "written in Roman script, the way people actually speak on the phone in India."
    ),
    AgentLanguage.AUTO: (
        "Mirror the customer's language exactly. If they speak Hindi, reply in Hindi "
        "(Roman script). If they mix Hindi and English, mix the same way. If they speak "
        "English, reply in English. Switch the moment they switch."
    ),
}

BASE_RULES = [
    "You are on a live phone call. Everything you write is spoken aloud by a "
    "text-to-speech engine, so write plain speech: no markdown, no bullet points, "
    "no emoji, no stage directions.",
    "Keep every reply under 40 words. Ask exactly one question at a time, then stop "
    "and let the customer answer.",
    "Never invent facts about pricing, features, availability, or timelines. If you "
    "do not know, say you will have someone confirm and move on.",
    "If the customer interrupts you, stop and address what they just said.",
    "Do not repeat yourself. Do not re-introduce yourself mid-call.",
    "Numbers, dates and prices should be written as words the way they are spoken.",
    "Acknowledge what they said before moving on -- a short 'samajh gaya' or "
    "'got it' -- so it sounds like listening rather than reading a script.",
    "Never ask two things in one breath, and never repeat a question they have already answered.",
    "If they sound busy or annoyed, offer to call back instead of pushing.",
    "Show that you were listening: refer back to something specific they said "
    "before asking the next thing. Never ask something they already answered.",
    "Follow the interesting thread. If they mention a problem, a tool they use, "
    "or a frustration, ask about that rather than returning to your script.",
    "Judge them honestly as you go. Notice whether they actually have the need, "
    "the means and the intent, and let that change how hard you push -- lean in "
    "with someone genuinely interested, wrap up quickly with someone who is not.",
    "Do not flatter, and do not agree with everything. If what they want is not "
    "something you offer, say so plainly; it earns more trust than a vague yes.",
    "Never end the call without saying goodbye, even if you are out of time.",
    "Never close while they are still answering, still asking, or clearly still "
    "engaged. If they are talking to you, the call is not over.",
    "Close in this order, always: tell them a specialist from the team will reach "
    "out with the details, ask plainly whether they would like that, wait for their "
    "answer, then thank them by name and say goodbye. Do not skip the question -- "
    "their answer is the whole point of the call.",
    "If they say yes to that follow-up, confirm it back in one line: say the team "
    "will call them on this number and roughly when. If they say no, thank them "
    "warmly anyway and close without pushing.",
    "Only after you have said goodbye, end that final line with the marker "
    "[END_CALL]. Never put the marker on a line that still asks a question.",
]

LANGUAGE_PREFERENCE_RULE = (
    "On your very first reply after the greeting, ask which language they are "
    "comfortable in -- Hindi, English, or a mix. Ask it naturally in one short "
    "sentence, then speak only that way for the rest of the call. Do not ask "
    "again."
)

RECORDING_NOTICE_RULE = (
    "Mention once, in the first thirty seconds and in a single short clause, "
    "that the call is recorded for quality. Do not dwell on it or apologise."
)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if str(item).strip())


def build_system_prompt(agent: Agent) -> str:
    """The stable, cacheable half of the prompt. Identical on every turn."""
    parts: list[str] = [
        f"You are {agent.name}, a {agent.role_title} at {agent.company_name or 'the company'}.",
        f"Personality: {agent.personality}" if agent.personality else "",
        "",
        "## Objective",
        agent.primary_objective
        or "Have a helpful conversation and understand what the customer needs.",
    ]

    if agent.secondary_objectives:
        parts += ["", "Secondary objectives:", _bullets(list(agent.secondary_objectives))]

    parts += [
        "",
        "## Language",
        LANGUAGE_RULES.get(agent.language, LANGUAGE_RULES[AgentLanguage.AUTO]),
    ]
    rules = list(BASE_RULES)
    if agent.ask_language_preference:
        rules.insert(1, LANGUAGE_PREFERENCE_RULE)
    if agent.record_calls:
        rules.append(RECORDING_NOTICE_RULE)
    parts += ["", "## How to talk", _bullets(rules)]

    if agent.forbidden_rules:
        parts += [
            "",
            "## Never do this",
            _bullets(list(agent.forbidden_rules)),
        ]

    if agent.qualification_questions:
        parts += [
            "",
            "## Qualification questions",
            "Work these in naturally over the call, one at a time - never as a list:",
            _bullets(list(agent.qualification_questions)),
        ]

    if agent.objection_handling:
        lines = [
            f'If they say "{item.get("objection", "")}": {item.get("response", "")}'
            for item in agent.objection_handling
            if item.get("objection")
        ]
        parts += ["", "## Handling objections", _bullets(lines)]

    if agent.ending_rules:
        parts += ["", "## When to end the call", _bullets(list(agent.ending_rules))]

    transfer = agent.transfer_rules or {}
    if transfer.get("enabled"):
        conditions = transfer.get("conditions") or ["the customer explicitly asks for a human"]
        parts += [
            "",
            "## Transfer to a human",
            "Write the marker [TRANSFER] on its own at the end of your reply when:",
            _bullets(list(conditions)),
        ]

    if agent.system_instructions:
        parts += ["", "## Additional instructions", agent.system_instructions]

    return "\n".join(part for part in parts if part != "").strip()


def build_turn_context(
    state: ConversationState,
    *,
    retrieved: list[str] | None = None,
    digest: str | None = None,
    wrapping_up: bool = False,
) -> str:
    """The volatile half: appended per turn, never part of the cached prefix."""
    blocks = [f"[Current stage: {state.value}] {STATE_GUIDANCE[state]}"]

    if wrapping_up:
        blocks.append(
            "[Time is nearly up] Bring this to a natural close within the next "
            "reply or two. Confirm the next step, thank them, and end. Do not "
            "start a new topic or ask another qualifying question."
        )

    if digest:
        blocks.append(f"[Earlier in this call] {digest}")

    if retrieved:
        joined = "\n\n".join(retrieved)
        blocks.append(
            "[Company knowledge - use only these facts, and if they do not answer the "
            f"question say you will confirm and follow up]\n{joined}"
        )
    return "\n\n".join(blocks)


def build_greeting(agent: Agent, lead_name: str | None = None) -> str:
    """Fill the greeting template.

    Tolerates a template written without a space around `{name}` and a lead with
    no name -- both otherwise produce audible glitches ("NamasteAditya", or a
    stranded comma) that the customer hears in the first second of the call.
    """
    if agent.greeting:
        name = (lead_name or "").strip()
        text = agent.greeting.replace("{name}", f" {name} " if name else " ")
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.!?])", r"\1", text)
        return text.strip()
    who = f" {lead_name}" if lead_name else ""
    company = agent.company_name or "our team"
    return f"Hello{who}, this is {agent.name} from {company}. How are you today?"
