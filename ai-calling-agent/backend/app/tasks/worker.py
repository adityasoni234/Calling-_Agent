"""arq worker.

    arq app.tasks.worker.WorkerSettings

Runs post-call processing, document ingestion, and the campaign dispatch tick.
The dispatcher is a cron job rather than a long-lived loop, so a crashed worker
recovers on the next tick instead of stalling a campaign.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.services.campaign_service import CampaignService
from app.services.knowledge.ingest import IngestService
from app.services.postcall_service import PostCallService

configure_logging(level=settings.log_level, json_output=settings.log_json)
log = get_logger("worker")


async def run_post_call(_ctx: dict[str, Any], call_id: str) -> None:
    async with SessionLocal() as db:
        await PostCallService(db).process(uuid.UUID(call_id))


async def run_ingest(
    _ctx: dict[str, Any], document_id: str, path: str, filename: str, mime: str
) -> None:
    data = await asyncio.to_thread(Path(path).read_bytes)
    async with SessionLocal() as db:
        await IngestService(db).ingest_bytes(
            uuid.UUID(document_id), data, filename=filename, mime_type=mime
        )


async def run_campaign_dispatch(_ctx: dict[str, Any], campaign_id: str) -> None:
    async with SessionLocal() as db:
        result = await CampaignService(db).dispatch(uuid.UUID(campaign_id))
        log.info("campaign.dispatch", campaign_id=campaign_id, **result)


async def tick_campaigns(_ctx: dict[str, Any]) -> None:
    """Dispatch every running campaign. Idempotent and safe to run concurrently."""
    from sqlalchemy import select

    async with SessionLocal() as db:
        rows = await db.execute(
            select(Campaign.id).where(Campaign.status == CampaignStatus.RUNNING)
        )
        campaign_ids = list(rows.scalars())

    for campaign_id in campaign_ids:
        async with SessionLocal() as db:
            result = await CampaignService(db).dispatch(campaign_id)
            if result.get("started"):
                log.info("campaign.dispatch", campaign_id=str(campaign_id), **result)


async def reap_stale_calls(_ctx: dict[str, Any]) -> None:
    """Sweep every organization, not just ones with a running campaign.

    Manual calls count towards the concurrency cap too, so ghosts have to be
    cleared even when nothing is dialling.
    """
    from sqlalchemy import select

    from app.models.organization import Organization

    async with SessionLocal() as db:
        organization_ids = list((await db.execute(select(Organization.id))).scalars())

    for organization_id in organization_ids:
        async with SessionLocal() as db:
            await CampaignService(db).reap_stale_calls(organization_id)


async def deliver_webhooks(_ctx: dict[str, Any]) -> None:
    """Flush queued webhook deliveries to subscribed CRMs."""
    from app.services.integration_service import IntegrationService

    async with SessionLocal() as db:
        sent = await IntegrationService(db).deliver_pending()
        if sent:
            log.info("integration.webhooks_delivered", count=sent)


async def learning_tick(_ctx: dict[str, Any]) -> None:
    """Retire losing phrasings, and draft new ones from calls that went badly.

    Hourly, not per-call: proposals cost an LLM request each, and a bandit that
    gains an arm every few minutes never accumulates enough trials to judge any
    of them.
    """
    from sqlalchemy import select

    from app.models.agent import Agent
    from app.services.learning_service import LearningService

    async with SessionLocal() as db:
        agent_ids = list(
            (await db.execute(select(Agent.id).where(Agent.is_active.is_(True)))).scalars()
        )

    for agent_id in agent_ids:
        async with SessionLocal() as db:
            agent = await db.get(Agent, agent_id)
            if agent is None:
                continue
            service = LearningService(db)
            try:
                retired = await service.retire_losers(agent)
                proposed = await service.propose(agent)
                if retired or proposed:
                    log.info(
                        "learning.tick",
                        agent=agent.name,
                        retired=retired,
                        proposed=len(proposed),
                    )
            except Exception as exc:
                # One agent's experiment must not stop the others.
                log.warning("learning.tick_failed", agent=agent.name, error=str(exc))


async def expire_reservations(_ctx: dict[str, Any]) -> None:
    """Return credits held for calls that never reported a terminal state."""
    from app.services.billing_service import BillingService

    async with SessionLocal() as db:
        freed = await BillingService(db).expire_stale_reservations()
        if freed:
            log.warning("billing.reservations_expired", count=freed)


class WorkerSettings:
    functions = [run_post_call, run_ingest, run_campaign_dispatch]
    cron_jobs = [
        cron(tick_campaigns, second={0, 15, 30, 45}, run_at_startup=True),
        cron(reap_stale_calls, minute=set(range(0, 60, 5)), run_at_startup=True),
        cron(deliver_webhooks, second={5, 20, 35, 50}),
        cron(learning_tick, minute={17}),
        cron(expire_reservations, minute=set(range(0, 60, 5))),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
    job_timeout = 300
