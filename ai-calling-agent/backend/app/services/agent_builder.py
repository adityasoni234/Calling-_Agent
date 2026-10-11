"""Turn a plain-language brief into a full agent configuration.

Writing a good calling agent means knowing what a *prompt* needs: an objective,
qualification questions that sound like conversation, objections answered
without over-promising, and explicit rules about what never to say. Most people
describing their business do not think in those terms.

This asks the LLM to do that translation once, up front, and returns a draft the
user edits and saves. It never saves on its own -- a generated persona that
nobody reviewed is how an agent ends up promising things you cannot deliver.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.agent import AgentLanguage
from app.services.base import UsageRecord
from app.services.registry import get_llm

log = get_logger(__name__)

BUILDER_SYSTEM = """\
You design configurations for AI voice agents that make real phone calls.

Given a short description of a business and what the call should achieve, write
a complete agent configuration. Rules that matter:

- The name is a real human first name the customer will hear and repeat back --
  "Riya", "Arjun", "Sara". Never a job word like "manager", "agent", "advisor"
  or "assistant", and never the company name. Match it to the language and
  market the call is placed in.
- The greeting is spoken aloud in the first two seconds. Keep it under 25 words,
  and make it sound like a person, not an advert.
- Qualification questions must be things a human would actually ask on a call,
  one idea each, answerable in a sentence. Never a list read aloud.
- Objection responses acknowledge the concern first, then answer in one or two
  sentences. Never argue.
- Forbidden rules should name the specific claims this business must not make --
  regulatory limits, guarantees it cannot honour, prices it cannot commit to.
  Be concrete about the industry, not generic.
- Ending rules say when to stop: objective met, or the customer declines.
- Write everything as speech. No markdown, no bullets, no emoji.

If the business is regulated (finance, health, insurance, legal), include the
forbidden rules that regulation implies, even if the user did not mention them.
"""


# Models occasionally return an array as a single string, sometimes carrying
# fragments of the tool-call envelope. Losing an otherwise good configuration to
# that is not acceptable, so the common shapes are coerced rather than rejected.
_MARKUP = re.compile(r"<[^>]*>")


def _to_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = _MARKUP.sub(" ", value)
        parts = re.split(r"[\n;]+|(?<=[.!?])\s{2,}", cleaned)
        return [part.strip(" -•\t") for part in parts if part.strip(" -•\t")]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(_MARKUP.sub(" ", item).strip())
            elif isinstance(item, dict):
                text = item.get("item") or item.get("text") or item.get("value")
                if isinstance(text, str) and text.strip():
                    out.append(text.strip())
        return out
    return []


class ObjectionResponse(BaseModel):
    """An explicit shape: `list[dict[str, str]]` in the schema was too vague and
    the model returned nothing for it."""

    objection: str = Field(description="What the customer says, in their words", max_length=200)
    response: str = Field(description="How to answer, one or two sentences", max_length=600)


# A caller who hears "Hi, this is manager" hangs up. Models reach for the role
# word often enough that the prompt alone cannot be trusted with it.
_ROLE_WORDS = {
    "agent",
    "advisor",
    "adviser",
    "assistant",
    "associate",
    "bot",
    "consultant",
    "executive",
    "manager",
    "operator",
    "representative",
    "rep",
    "sales",
    "support",
    "team",
    "specialist",
    "officer",
    "caller",
    "ai",
}
_FALLBACK_NAMES = ("Riya", "Arjun", "Sara", "Kabir", "Anaya", "Neel")


def _looks_like_a_role(name: str) -> bool:
    words = [word for word in re.split(r"[^A-Za-z]+", name.lower()) if word]
    return not words or all(word in _ROLE_WORDS for word in words)


class AgentBlueprint(BaseModel):
    """The content half of an agent. Technical settings keep their defaults."""

    name: str = Field(
        description="A real human first name for the persona, never a job word", max_length=60
    )
    role_title: str = Field(description="Their job title", max_length=120)
    personality: str = Field(description="Two lines on tone and manner", max_length=600)
    primary_objective: str = Field(description="The one goal of the call", max_length=400)
    secondary_objectives: list[str] = Field(default_factory=list, max_length=5)
    greeting: str = Field(description="Opening line, under 25 words", max_length=300)
    qualification_questions: list[str] = Field(default_factory=list, max_length=6)
    forbidden_rules: list[str] = Field(default_factory=list, max_length=8)
    ending_rules: list[str] = Field(default_factory=list, max_length=5)

    @field_validator(
        "secondary_objectives",
        "qualification_questions",
        "forbidden_rules",
        "ending_rules",
        "objection_handling",
        mode="before",
    )
    @classmethod
    def _trim_to_cap(cls, value: object, info: ValidationInfo) -> object:
        """Keep the first N rather than rejecting the whole draft.

        A rich brief naturally yields more objectives or rules than these caps.
        Throwing away a good sixteen-second generation because one list had six
        items instead of five is the wrong trade -- the caps exist to keep the
        prompt small, and the first items are the ones the model ranked highest.
        """
        if not isinstance(value, list):
            return value
        caps = {
            "secondary_objectives": 5,
            "qualification_questions": 6,
            "forbidden_rules": 8,
            "ending_rules": 5,
            "objection_handling": 6,
        }
        cap = caps.get(info.field_name or "")
        if cap is not None and len(value) > cap:
            log.info(
                "agent_builder.trimmed", field=info.field_name, kept=cap, dropped=len(value) - cap
            )
            return value[:cap]
        return value

    @field_validator("role_title", "personality", "primary_objective", "greeting", mode="before")
    @classmethod
    def _trim_text(cls, value: object, info: ValidationInfo) -> object:
        """Same reasoning as the list caps: trim, do not discard the draft."""
        caps = {
            "role_title": 120,
            "personality": 600,
            "primary_objective": 400,
            "greeting": 300,
        }
        cap = caps.get(info.field_name or "")
        if isinstance(value, str) and cap and len(value) > cap:
            log.info("agent_builder.trimmed_text", field=info.field_name, length=len(value))
            return value[:cap].rstrip()
        return value

    @field_validator("name")
    @classmethod
    def _must_be_a_person(cls, value: str) -> str:
        name = " ".join(value.split()).strip(" .,-")
        if _looks_like_a_role(name):
            # Deterministic, so regenerating the same brief is not a lottery.
            return _FALLBACK_NAMES[len(name) % len(_FALLBACK_NAMES)]
        return name

    objection_handling: list[ObjectionResponse] = Field(
        default_factory=list,
        max_length=6,
        description="The three or four objections this business actually hears",
    )
    language: AgentLanguage = AgentLanguage.AUTO

    @field_validator(
        "secondary_objectives",
        "qualification_questions",
        "forbidden_rules",
        "ending_rules",
        mode="before",
    )
    @classmethod
    def _coerce_lists(cls, value: object) -> list[str]:
        return _to_string_list(value)

    @field_validator("objection_handling", mode="before")
    @classmethod
    def _coerce_objections(cls, value: object) -> object:
        if not isinstance(value, list):
            return []
        pairs = []
        for item in value:
            if not isinstance(item, dict):
                continue
            objection = item.get("objection") or item.get("concern") or ""
            response = item.get("response") or item.get("answer") or ""
            if objection and response:
                pairs.append({"objection": str(objection), "response": str(response)})
        return pairs


#: Models emit these when a field cannot be filled from the source material.
#: An agent called "<UNKNOWN>" would introduce itself that way on a live call.
_PLACEHOLDERS = ("<unknown>", "n/a", "not specified", "unspecified", "none provided")


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDERS


def _explain_failure(exc: Exception) -> str:
    """Say what the user can actually do about it."""
    detail = str(exc).lower()
    if "401" in detail or "invalid x-api-key" in detail or "authentication" in detail:
        return (
            "The AI provider rejected our API key. It has expired or been revoked — "
            "add a new one under Settings, then try again."
        )
    if "429" in detail or "rate limit" in detail:
        return "The AI provider is rate limiting us. Wait a minute and try again."
    if "credit" in detail or "402" in detail or "billing" in detail:
        return "The AI provider account is out of credit. Top it up, then try again."
    return "Could not generate the agent. Try again, or write it by hand."


async def generate_blueprint(
    *, brief: str, company_name: str, language: AgentLanguage = AgentLanguage.AUTO
) -> tuple[AgentBlueprint, list[UsageRecord]]:
    text = brief.strip()
    # Someone who pastes a written brief or a full system prompt has given us
    # the most specific input we will ever get. Paraphrasing it into generic
    # sales copy throws that away -- the instruction below says to mine it.
    detailed = len(text) > 1200 or text.count("\n") > 12

    prompt = (
        f"Company: {company_name or 'the company'}\n"
        f"Preferred language: {language.value}\n\n"
        f"Source material:\n{text}\n\n"
    )
    if detailed:
        prompt += (
            "This is a detailed brief, and it is authoritative. Build the "
            "configuration FROM it, not merely inspired by it:\n"
            "- Keep the exact persona name, role and company it specifies.\n"
            "- Carry over its specific questions, objection responses and "
            "prohibitions verbatim where they fit a field, rather than "
            "rewriting them into something blander.\n"
            "- Keep its domain vocabulary and any product or regulatory terms.\n"
            "- Where it is silent on a field, infer something consistent with "
            "its tone. Where it is explicit, follow it exactly.\n"
            "- If it is longer than the fields can hold, keep the parts that "
            "change what the agent SAYS, and drop background and rationale.\n\n"
            "Write the configuration."
        )
    else:
        prompt += "Write the configuration."

    try:
        data, usage = await get_llm().complete_json(
            system=BUILDER_SYSTEM,
            prompt=prompt,
            schema=AgentBlueprint.model_json_schema(),
            max_tokens=2000,
        )
    except Exception as exc:
        log.error("agent_builder.llm_failed", error=str(exc))
        # "Try again" is bad advice when the cause is a dead API key -- retrying
        # fails identically and the user never learns what to fix.
        raise AppError(
            _explain_failure(exc),
            code="generation_failed",
            status_code=502,
        ) from exc

    try:
        blueprint = AgentBlueprint.model_validate(data)
    except ValidationError as exc:
        log.warning("agent_builder.invalid", error=str(exc))
        raise AppError(
            "The generated configuration was malformed. Try rephrasing your brief.",
            code="generation_invalid",
            status_code=502,
        ) from exc

    # A model that could not read the brief returns placeholders rather than
    # failing. Saving that gives the customer an agent that opens the call with
    # "Hi, this is <UNKNOWN>".
    empty = [
        field
        for field in ("name", "role_title", "primary_objective", "greeting")
        if _is_placeholder(str(getattr(blueprint, field, "")))
    ]
    if empty:
        log.warning("agent_builder.placeholders", fields=empty)
        raise AppError(
            "The brief did not give enough to work from — "
            f"{', '.join(f.replace('_', ' ') for f in empty)} came back empty. "
            "Say who the agent is, who they are calling, and what a good call achieves.",
            code="generation_incomplete",
            status_code=502,
        )

    log.info("agent_builder.generated", name=blueprint.name)
    return blueprint, usage
