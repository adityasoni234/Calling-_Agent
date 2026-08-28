from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.agents.prompt import build_greeting, build_system_prompt
from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import ConflictError, NotFoundError
from app.models.agent import Agent
from app.models.call import Call
from app.models.campaign import Campaign, CampaignStatus
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate, PromptPreview
from app.schemas.common import MessageResponse, Page

router = APIRouter(prefix="/agents", tags=["agents"])


async def _get(db: DbSession, user: CurrentUser, agent_id: uuid.UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.organization_id != user.organization_id:
        raise NotFoundError("Agent not found")
    return agent


@router.get("", response_model=Page[AgentRead], summary="List agents")
async def list_agents(
    db: DbSession,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 25,
    active_only: bool = False,
) -> Page[AgentRead]:
    statement = select(Agent).where(Agent.organization_id == user.organization_id)
    if active_only:
        statement = statement.where(Agent.is_active.is_(True))
    return await paginate(
        db,
        statement.order_by(Agent.created_at.desc()),
        page=page,
        page_size=page_size,
        schema=AgentRead,
    )


@router.post(
    "", response_model=AgentRead, status_code=status.HTTP_201_CREATED, summary="Create an agent"
)
async def create_agent(payload: AgentCreate, db: DbSession, user: CurrentUser) -> AgentRead:
    data = payload.model_dump(mode="json")
    agent = Agent(organization_id=user.organization_id, **data)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentRead.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentRead, summary="Get one agent")
async def get_agent(agent_id: uuid.UUID, db: DbSession, user: CurrentUser) -> AgentRead:
    return AgentRead.model_validate(await _get(db, user, agent_id))


@router.patch("/{agent_id}", response_model=AgentRead, summary="Update an agent")
async def update_agent(
    agent_id: uuid.UUID, payload: AgentUpdate, db: DbSession, user: CurrentUser
) -> AgentRead:
    agent = await _get(db, user, agent_id)
    for field, value in payload.model_dump(exclude_unset=True, mode="json").items():
        setattr(agent, field, value)
    await db.commit()
    await db.refresh(agent)
    return AgentRead.model_validate(agent)


@router.delete("/{agent_id}", response_model=MessageResponse, summary="Delete an agent")
async def delete_agent(agent_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    agent = await _get(db, user, agent_id)

    # Deleting an agent mid-campaign would orphan running calls.
    running = await db.scalar(
        select(Campaign.id)
        .where(Campaign.agent_id == agent_id, Campaign.status == CampaignStatus.RUNNING)
        .limit(1)
    )
    if running:
        raise ConflictError("Agent is used by a running campaign", code="agent_in_use")

    has_calls = await db.scalar(select(Call.id).where(Call.agent_id == agent_id).limit(1))
    if has_calls:
        # Keep the call history intact; retire the agent instead.
        agent.is_active = False
        await db.commit()
        return MessageResponse(message="Agent has call history, so it was deactivated instead")

    await db.delete(agent)
    await db.commit()
    return MessageResponse(message="Agent deleted")


@router.get("/{agent_id}/prompt", response_model=PromptPreview, summary="Preview the built prompt")
async def preview_prompt(agent_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PromptPreview:
    """Shows exactly what the model will be sent -- the prompt is data, so it
    should be inspectable without reading the code."""
    agent = await _get(db, user, agent_id)
    prompt = build_system_prompt(agent)
    return PromptPreview(
        system_prompt=prompt,
        greeting=build_greeting(agent),
        estimated_tokens=max(1, len(prompt) // 4),
    )
