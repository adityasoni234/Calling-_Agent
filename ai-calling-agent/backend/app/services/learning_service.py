"""The learning engine: a contextual bandit over what the agent says.

Three pieces, each deliberately simple enough to audit:

1. A **reward** derived from the call's own outcome -- no separate labelling
   step, because anything that needs a human to label it will not get done.
2. A **policy** (Thompson sampling) that picks which phrasing to use, trading
   off trying new wording against using what already works.
3. A **proposal loop** that reads losing transcripts and drafts new phrasings
   for a human to approve.

What this is not: gradient-based RL. No model weights change. That matters
because the alternative -- claiming a self-training LLM on an API that has no
fine-tuning -- would be a lie, and the bandit is the correct algorithm here
anyway: the action space is small, the reward is sparse and delayed, and the
cost of a bad action is a wasted phone call.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent import Agent
from app.models.call import Call, CallStatus, CallTurn
from app.models.lead import Lead, LeadStatus
from app.models.learning import AgentVariant, VariantKind, VariantStatus, VariantTrial
from app.services.registry import get_llm

log = get_logger(__name__)

#: Below this many trials an arm's mean is noise, so it is never retired.
MIN_TRIALS_TO_JUDGE = 25
#: How far behind the leader an arm must be before it is retired.
RETIRE_MARGIN = 0.15
#: Transcripts fed to the proposal step. More context, better proposals, but
#: the cost and latency grow with it.
TRANSCRIPTS_PER_PROPOSAL = 6


def reward_for(call: Call, lead: Lead | None) -> float:
    """What this call was worth, in [0, 1].

    Graded rather than binary: a call that held someone for ninety seconds and
    ended politely taught us something real, even without a qualification. A
    purely binary reward would rate it identically to an instant hang-up and
    the bandit would never learn what keeps people on the phone.
    """
    if call.status is not CallStatus.COMPLETED:
        return 0.0

    score = 0.0
    # Did they stay? Conversations that die in ten seconds are the failure mode
    # we most want to learn away from.
    seconds = call.duration_seconds or 0
    score += 0.20 * min(seconds / 90.0, 1.0)

    # Did they engage? Turn count separates a real exchange from a monologue.
    turns = call.extracted_data.get("_turns", 0) if call.extracted_data else 0
    score += 0.15 * min(float(turns) / 8.0, 1.0)

    data = call.extracted_data or {}
    if data.get("followup_opt_in"):
        score += 0.35  # They said yes out loud. This is the thing we optimise for.
    interest = str(data.get("interest_level", "")).lower()
    score += {"high": 0.20, "medium": 0.12, "low": 0.0}.get(interest, 0.0)

    if lead is not None:
        if lead.status in {LeadStatus.QUALIFIED, LeadStatus.CONVERTED}:
            score += 0.10
        # A call that got someone to opt out is actively negative, whatever
        # else it achieved -- it cost us a lead permanently.
        if lead.status is LeadStatus.DO_NOT_CALL:
            score -= 0.40

    return max(0.0, min(1.0, score))


class LearningService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- the policy ----------------------------------------------------

    async def choose(self, agent: Agent, call_id: uuid.UUID) -> dict[str, AgentVariant]:
        """Pick one active variant per slot and record the trials.

        Thompson sampling: draw from each arm's Beta posterior and take the
        highest draw. An arm with few trials has a wide posterior, so it still
        gets picked sometimes -- that is the exploration, and it costs nothing
        to implement correctly.
        """
        rows = await self.db.execute(
            select(AgentVariant).where(
                AgentVariant.agent_id == agent.id,
                AgentVariant.status == VariantStatus.ACTIVE,
            )
        )
        by_slot: dict[str, list[AgentVariant]] = {}
        for variant in rows.scalars():
            key = f"{variant.kind}:{variant.slot or ''}"
            by_slot.setdefault(key, []).append(variant)

        chosen: dict[str, AgentVariant] = {}
        for key, arms in by_slot.items():
            if len(arms) == 1:
                winner = arms[0]
            else:
                winner = max(
                    arms,
                    key=lambda a: random.betavariate(
                        max(a.successes, 0.0) + 1.0, max(a.trials - a.successes, 0.0) + 1.0
                    ),
                )
            chosen[key] = winner
            winner.trials += 1
            winner.last_used_at = datetime.now(UTC)
            self.db.add(VariantTrial(call_id=call_id, variant_id=winner.id))

        if chosen:
            await self.db.commit()
            log.info(
                "learning.variants_chosen",
                call_id=str(call_id),
                chosen={k: str(v.id)[:8] for k, v in chosen.items()},
            )
        return chosen

    async def record_outcome(self, call: Call, lead: Lead | None) -> float | None:
        """Score the call and credit whichever variants it used."""
        rows = await self.db.execute(
            select(VariantTrial).where(
                VariantTrial.call_id == call.id, VariantTrial.reward.is_(None)
            )
        )
        trials = list(rows.scalars())
        if not trials:
            return None

        reward = reward_for(call, lead)
        for trial in trials:
            trial.reward = reward
            variant = await self.db.get(AgentVariant, trial.variant_id)
            if variant is not None:
                variant.successes += reward
        await self.db.commit()
        log.info("learning.outcome_recorded", call_id=str(call.id), reward=round(reward, 3))
        return reward

    # --- housekeeping --------------------------------------------------

    async def ensure_baselines(self, agent: Agent) -> int:
        """Make the agent's own wording an arm, so it is what new ideas beat.

        Without a control arm there is nothing to compare against, and the
        engine would happily report that its own first guess is the best known
        phrasing.
        """
        existing = await self.db.scalar(
            select(func.count())
            .select_from(AgentVariant)
            .where(AgentVariant.agent_id == agent.id, AgentVariant.is_baseline.is_(True))
        )
        if existing:
            return 0

        created = 0
        if agent.greeting:
            self.db.add(
                AgentVariant(
                    organization_id=agent.organization_id,
                    agent_id=agent.id,
                    kind=VariantKind.GREETING,
                    content=agent.greeting,
                    status=VariantStatus.ACTIVE,
                    is_baseline=True,
                    rationale="The agent's configured greeting. This is the control.",
                )
            )
            created += 1
        for item in agent.objection_handling or []:
            objection = str(item.get("objection", "")).strip()
            response = str(item.get("response", "")).strip()
            if objection and response:
                self.db.add(
                    AgentVariant(
                        organization_id=agent.organization_id,
                        agent_id=agent.id,
                        kind=VariantKind.OBJECTION,
                        slot=objection[:160],
                        content=response,
                        status=VariantStatus.ACTIVE,
                        is_baseline=True,
                        rationale="The agent's configured response. This is the control.",
                    )
                )
                created += 1
        if created:
            await self.db.commit()
            log.info("learning.baselines_created", agent_id=str(agent.id), count=created)
        return created

    async def retire_losers(self, agent: Agent) -> int:
        """Stop spending calls on arms that have clearly lost.

        Only against arms with enough trials to mean anything, and a baseline is
        never retired -- losing the control would leave nothing to measure
        against, and would silently make an unreviewed proposal the new default.
        """
        rows = await self.db.execute(
            select(AgentVariant).where(
                AgentVariant.agent_id == agent.id,
                AgentVariant.status == VariantStatus.ACTIVE,
            )
        )
        arms = list(rows.scalars())
        retired = 0
        by_slot: dict[str, list[AgentVariant]] = {}
        for arm in arms:
            by_slot.setdefault(f"{arm.kind}:{arm.slot or ''}", []).append(arm)

        for group in by_slot.values():
            judged = [a for a in group if a.trials >= MIN_TRIALS_TO_JUDGE]
            if len(judged) < 2:
                continue
            best = max(judged, key=lambda a: a.mean_reward)
            for arm in judged:
                if arm is best or arm.is_baseline:
                    continue
                if best.mean_reward - arm.mean_reward >= RETIRE_MARGIN:
                    arm.status = VariantStatus.RETIRED
                    arm.retired_reason = (
                        f"{arm.mean_reward:.0%} over {arm.trials} calls vs "
                        f"{best.mean_reward:.0%} for the leader"
                    )
                    retired += 1
        if retired:
            await self.db.commit()
            log.info("learning.retired", agent_id=str(agent.id), count=retired)
        return retired

    # --- the proposal loop ---------------------------------------------

    async def propose(self, agent: Agent, limit: int = 2) -> list[AgentVariant]:
        """Draft new phrasings from calls that went badly.

        Proposals land as CANDIDATE and are never spoken to a customer until a
        person approves them. This agent discusses regulated financial products
        -- letting a model silently rewrite what it says would be indefensible
        however good the metrics looked.
        """
        transcripts = await self._weak_transcripts(agent)
        if len(transcripts) < 2:
            return []

        current = await self.db.execute(
            select(AgentVariant).where(
                AgentVariant.agent_id == agent.id,
                AgentVariant.status == VariantStatus.ACTIVE,
                AgentVariant.kind == VariantKind.GREETING,
            )
        )
        greetings = [v.content for v in current.scalars()]

        prompt = (
            "These are transcripts of sales calls that went poorly -- the person "
            "disengaged, hung up early, or declined.\n\n"
            + "\n\n---\n\n".join(transcripts)
            + "\n\nOpenings currently in use:\n"
            + "\n".join(f"- {g}" for g in greetings)
            + "\n\nPropose ONE different opening line that might hold these people "
            "longer. Keep the same language mix, under 25 words, and spoken plainly. "
            "Do not promise anything, do not mention returns or profit, and do not "
            "claim any regulatory approval."
        )
        schema = {
            "type": "object",
            "properties": {
                "greeting": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["greeting", "rationale"],
        }
        try:
            data, _ = await get_llm().complete_json(
                system=(
                    "You improve what a phone agent says, based on evidence from real "
                    "calls. Report only what the transcripts support."
                ),
                prompt=prompt,
                schema=schema,
            )
        except Exception as exc:
            log.warning("learning.propose_failed", agent_id=str(agent.id), error=str(exc))
            return []

        text = str(data.get("greeting", "")).strip()
        if not text or len(text) > 300:
            return []

        variant = AgentVariant(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            kind=VariantKind.GREETING,
            content=text,
            status=VariantStatus.CANDIDATE,
            rationale=str(data.get("rationale", ""))[:600],
        )
        self.db.add(variant)
        await self.db.commit()
        await self.db.refresh(variant)
        log.info("learning.proposed", agent_id=str(agent.id), variant_id=str(variant.id))
        return [variant][:limit]

    async def _weak_transcripts(self, agent: Agent) -> list[str]:
        """Recent calls that earned little, as plain text."""
        cutoff = datetime.now(UTC) - timedelta(days=30)
        rows = await self.db.execute(
            select(Call)
            .join(VariantTrial, VariantTrial.call_id == Call.id)
            .where(
                Call.agent_id == agent.id,
                Call.created_at >= cutoff,
                VariantTrial.reward.is_not(None),
                VariantTrial.reward < 0.3,
            )
            .order_by(Call.created_at.desc())
            .limit(TRANSCRIPTS_PER_PROPOSAL)
        )
        transcripts: list[str] = []
        for call in rows.scalars().unique():
            turn_rows = await self.db.execute(
                select(CallTurn)
                .where(CallTurn.call_id == call.id)
                .order_by(CallTurn.turn_index)
                .limit(14)
            )
            lines = [f"{t.role}: {t.content}" for t in turn_rows.scalars()]
            if len(lines) >= 2:
                transcripts.append("\n".join(lines))
        return transcripts
