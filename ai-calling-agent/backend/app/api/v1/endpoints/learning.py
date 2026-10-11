"""The learning engine's surface: what it tried, what won, what it proposes.

Proposals are approved by a person, never auto-applied. The agent discusses
regulated financial products; a model silently rewriting what it says to
customers is not a tradeoff worth any amount of lift.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.agent import Agent
from app.models.learning import AgentVariant, VariantStatus, VariantTrial
from app.schemas.common import MessageResponse
from app.schemas.learning import LearningSummary, VariantDecision, VariantRead
from app.services.learning_service import LearningService

router = APIRouter(prefix="/learning", tags=["learning"])


def _read(variant: AgentVariant) -> VariantRead:
    return VariantRead(
        **{
            field: getattr(variant, field)
            for field in VariantRead.model_fields
            if field != "mean_reward"
        },
        mean_reward=variant.mean_reward,
    )


@router.get("/summary", response_model=list[LearningSummary], summary="What each agent learned")
async def summary(db: DbSession, user: CurrentUser) -> list[LearningSummary]:
    agents = (
        await db.execute(select(Agent).where(Agent.organization_id == user.organization_id))
    ).scalars()

    out: list[LearningSummary] = []
    for agent in agents:
        rows = (
            await db.execute(select(AgentVariant).where(AgentVariant.agent_id == agent.id))
        ).scalars()
        variants = list(rows)
        if not variants:
            continue
        active = [v for v in variants if v.status is VariantStatus.ACTIVE]
        judged = [v for v in active if v.trials > 0]
        scored = await db.scalar(
            select(func.count())
            .select_from(VariantTrial)
            .join(AgentVariant, AgentVariant.id == VariantTrial.variant_id)
            .where(AgentVariant.agent_id == agent.id, VariantTrial.reward.is_not(None))
        )
        mean = await db.scalar(
            select(func.avg(VariantTrial.reward))
            .join(AgentVariant, AgentVariant.id == VariantTrial.variant_id)
            .where(AgentVariant.agent_id == agent.id, VariantTrial.reward.is_not(None))
        )
        best = max(judged, key=lambda v: v.mean_reward) if judged else None
        baseline = next((v for v in variants if v.is_baseline), None)
        out.append(
            LearningSummary(
                agent_id=agent.id,
                agent_name=agent.name,
                active_variants=len(active),
                candidates=sum(1 for v in variants if v.status is VariantStatus.CANDIDATE),
                retired=sum(1 for v in variants if v.status is VariantStatus.RETIRED),
                scored_calls=int(scored or 0),
                average_reward=float(mean) if mean is not None else None,
                best=_read(best) if best else None,
                baseline=_read(baseline) if baseline else None,
            )
        )
    return out


@router.get("/variants", response_model=list[VariantRead], summary="Every variant")
async def list_variants(
    db: DbSession, user: CurrentUser, agent_id: uuid.UUID | None = None
) -> list[VariantRead]:
    statement = select(AgentVariant).where(AgentVariant.organization_id == user.organization_id)
    if agent_id:
        statement = statement.where(AgentVariant.agent_id == agent_id)
    rows = await db.execute(statement.order_by(AgentVariant.created_at.desc()))
    return [_read(variant) for variant in rows.scalars()]


@router.post(
    "/variants/{variant_id}/decide",
    response_model=VariantRead,
    summary="Approve a proposal into the rotation, or reject it",
)
async def decide(
    variant_id: uuid.UUID, payload: VariantDecision, db: DbSession, user: CurrentUser
) -> VariantRead:
    variant = await db.get(AgentVariant, variant_id)
    if variant is None or variant.organization_id != user.organization_id:
        raise NotFoundError("Variant not found")
    if variant.status is not VariantStatus.CANDIDATE:
        raise ValidationFailedError(
            "Only a pending proposal can be decided", code="not_a_candidate"
        )

    if payload.decision == "approve":
        variant.status = VariantStatus.ACTIVE
    else:
        variant.status = VariantStatus.RETIRED
        variant.retired_reason = "Rejected before it was ever used"
    await db.commit()
    await db.refresh(variant)
    return _read(variant)


@router.post(
    "/agents/{agent_id}/propose",
    response_model=list[VariantRead],
    summary="Draft a new phrasing from calls that went badly",
)
async def propose(agent_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[VariantRead]:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.organization_id != user.organization_id:
        raise NotFoundError("Agent not found")
    service = LearningService(db)
    await service.ensure_baselines(agent)
    return [_read(variant) for variant in await service.propose(agent)]


@router.post(
    "/agents/{agent_id}/enable",
    response_model=MessageResponse,
    summary="Start learning for this agent",
)
async def enable(agent_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.organization_id != user.organization_id:
        raise NotFoundError("Agent not found")
    created = await LearningService(db).ensure_baselines(agent)
    return MessageResponse(
        message=(
            f"Learning on. {created} baseline variant(s) registered as the control."
            if created
            else "Learning was already on for this agent."
        )
    )
