"""Recording what happened, so a timeline can be reconstructed later.

One helper rather than ad-hoc inserts: the shape of an event is then consistent
across the codebase, and a caller cannot accidentally omit the organization or
the actor and produce an orphan row nobody can attribute.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.activity import ActivityEvent, ActorType, EntityType
from app.models.user import User

log = get_logger(__name__)

#: Never written into before/after, however convenient it would be.
_REDACTED = {
    "hashed_password",
    "password",
    "hashed_key",
    "secret",
    "api_key",
    "auth_token",
    "token",
    "voice_config",
}


def _safe(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop secrets and truncate long values before they reach the audit trail."""
    if not data:
        return None
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _REDACTED or "secret" in key.lower() or "password" in key.lower():
            continue
        out[key] = value[:300] if isinstance(value, str) else value
    return out or None


class ActivityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        action: str,
        entity_type: EntityType,
        actor: User | None = None,
        actor_type: ActorType = ActorType.USER,
        entity_id: uuid.UUID | None = None,
        entity_label: str | None = None,
        summary: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        reason: str | None = None,
        request_id: str | None = None,
        commit: bool = True,
    ) -> ActivityEvent:
        event = ActivityEvent(
            organization_id=organization_id,
            actor_user_id=actor.id if actor else None,
            # Snapshot the label: a renamed or deleted user must not erase history.
            actor_label=(actor.email if actor else None),
            actor_type=actor_type if actor else (actor_type or ActorType.SYSTEM),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=(entity_label or "")[:200] or None,
            summary=(summary or "")[:300] or None,
            before=_safe(before),
            after=_safe(after),
            reason=reason,
            request_id=request_id,
            occurred_at=datetime.now(UTC),
        )
        self.db.add(event)
        if commit:
            await self.db.commit()
        return event

    async def timeline(
        self,
        organization_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ActivityEvent]:
        statement = select(ActivityEvent).where(ActivityEvent.organization_id == organization_id)
        if actor_user_id:
            statement = statement.where(ActivityEvent.actor_user_id == actor_user_id)
        rows = await self.db.execute(
            statement.order_by(ActivityEvent.created_at.desc()).limit(limit).offset(offset)
        )
        return list(rows.scalars())


async def safe_record(db: AsyncSession, **kwargs: Any) -> None:
    """Record, but never let an audit failure break the operation it describes.

    A missing audit row is bad; a customer unable to start a campaign because
    the audit insert failed is worse.
    """
    try:
        await ActivityService(db).record(**kwargs)
    except Exception as exc:
        log.warning("activity.record_failed", action=kwargs.get("action"), error=str(exc))
