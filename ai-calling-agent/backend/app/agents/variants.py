"""Apply the bandit's chosen phrasings to an agent, for one call.

A detached copy is used rather than mutating the loaded row: the agent is a
database object, and writing an experiment's wording onto it would quietly
rewrite the user's own configuration.
"""

from __future__ import annotations

import copy

from app.models.agent import Agent
from app.models.learning import AgentVariant, VariantKind


def apply_variants(agent: Agent, chosen: dict[str, AgentVariant]) -> Agent:
    if not chosen:
        return agent

    trial = copy.copy(agent)
    objections = [dict(item) for item in (agent.objection_handling or [])]
    extra_rules: list[str] = []

    for variant in chosen.values():
        if variant.kind is VariantKind.GREETING:
            trial.greeting = variant.content
        elif variant.kind is VariantKind.OBJECTION and variant.slot:
            for item in objections:
                if str(item.get("objection", "")).strip()[:160] == variant.slot:
                    item["response"] = variant.content
                    break
            else:
                objections.append({"objection": variant.slot, "response": variant.content})
        elif variant.kind is VariantKind.STYLE_RULE:
            extra_rules.append(variant.content)

    trial.objection_handling = objections
    if extra_rules:
        trial.system_instructions = "\n\n".join(
            part for part in [agent.system_instructions, *extra_rules] if part
        )
    return trial
