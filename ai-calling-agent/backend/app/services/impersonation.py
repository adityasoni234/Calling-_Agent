"""Starting, exchanging and ending staff sessions on customer accounts.

Every refusal in here is deliberate and most of them are refusals of a thing
that would otherwise look reasonable. See `app.models.impersonation` for why
the session is a row rather than only a claim.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError, ValidationFailedError
from app.core.security import ImpersonationClaim, create_access_token
from app.core.times import as_utc
from app.models.activity import ActivityEvent, ActorType, EntityType
from app.models.billing import PlatformEvent
from app.models.impersonation import (
    HANDOFF_SECONDS,
    MIN_REASON_LENGTH,
    SESSION_MINUTES,
    ImpersonationEndReason,
    ImpersonationMode,
    ImpersonationSession,
)
from app.models.organization import Organization
from app.models.user import User


def _utc(value: datetime) -> datetime:
    """`as_utc` where the column is not nullable, so the None case cannot arise."""
    return as_utc(value) or value


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class ImpersonationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def start(
        self,
        *,
        admin: User,
        target: User,
        reason: str,
        mode: ImpersonationMode,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[ImpersonationSession, str]:
        """Open a session and return it with the one-time handoff code.

        The code is returned once, here, and never readable again -- only its
        digest is stored.
        """
        reason = (reason or "").strip()
        if len(reason) < MIN_REASON_LENGTH:
            raise ValidationFailedError(
                f"Give a reason of at least {MIN_REASON_LENGTH} characters. "
                "It is what the customer will be shown if they ask why we were in their account."
            )

        if target.id == admin.id:
            raise ValidationFailedError("You are already signed in as yourself")

        # Impersonating another staff account would turn a support tool into a
        # privilege-escalation path: a support admin could borrow an owner's
        # platform rights and the audit trail would show the owner acting.
        if target.is_platform_admin:
            raise PermissionDeniedError(
                "Platform administrators cannot be impersonated. "
                "Ask them to reproduce the problem on their own account."
            )

        if not target.is_active:
            raise ValidationFailedError(
                "That account is deactivated. Reactivate it first if you need to look inside it."
            )

        organization = await self.db.get(Organization, target.organization_id)
        if organization is None:
            raise ValidationFailedError("That user's organization no longer exists")

        now = datetime.now(UTC)
        code = secrets.token_urlsafe(32)
        session = ImpersonationSession(
            admin_user_id=admin.id,
            admin_email=admin.email,
            target_user_id=target.id,
            target_email=target.email,
            organization_id=organization.id,
            organization_name=organization.name,
            mode=mode,
            reason=reason,
            expires_at=now + timedelta(minutes=SESSION_MINUTES),
            handoff_digest=_digest(code),
            handoff_expires_at=now + timedelta(seconds=HANDOFF_SECONDS),
            started_ip=ip,
            started_user_agent=(user_agent or "")[:400] or None,
        )
        self.db.add(session)

        self.db.add(
            PlatformEvent(
                actor_user_id=admin.id,
                actor_email=admin.email,
                action="impersonation.started",
                organization_id=organization.id,
                target=target.email,
                detail=f"[{mode.value}] {reason}",
                occurred_at=now,
            )
        )
        # The customer's own timeline, not just ours. A customer who cannot
        # see that staff entered their account has not been told, and "we have
        # an internal log of it" is not the same as telling them.
        self.db.add(
            ActivityEvent(
                organization_id=organization.id,
                actor_user_id=admin.id,
                actor_label=admin.email,
                actor_type=ActorType.PLATFORM_ADMIN,
                action="account.accessed_by_support",
                entity_type=EntityType.ORGANIZATION,
                entity_id=organization.id,
                summary=(
                    f"Stockvala support opened this account as {target.email} "
                    f"({'read-only' if mode is ImpersonationMode.READ_ONLY else 'read and write'})"
                ),
                reason=reason,
                occurred_at=now,
            )
        )
        await self.db.commit()
        await self.db.refresh(session)
        return session, code

    async def exchange(self, code: str) -> tuple[ImpersonationSession, User, str, datetime]:
        """Trade a handoff code for an access token.

        Returns the session, the user being impersonated, the token and its
        expiry. No refresh token is issued, by design: a session that can be
        renewed without anyone deciding to renew it is a standing back door.
        """
        if not code:
            raise AuthenticationError("Missing handoff code", code="handoff_invalid")

        now = datetime.now(UTC)
        session = (
            await self.db.execute(
                select(ImpersonationSession).where(
                    ImpersonationSession.handoff_digest == _digest(code)
                )
            )
        ).scalar_one_or_none()
        # One message for every failure below. Distinguishing "no such code"
        # from "already used" would tell someone holding a stolen code whether
        # it was ever real.
        invalid = AuthenticationError(
            "This link is no longer valid. Start the session again from the admin console.",
            code="handoff_invalid",
        )
        if session is None or session.handoff_used_at is not None:
            raise invalid
        if session.ended_at is not None or session.is_revoked:
            raise invalid
        if session.handoff_expires_at is None or _utc(session.handoff_expires_at) < now:
            raise invalid
        if _utc(session.expires_at) < now:
            raise invalid

        target = await self.db.get(User, session.target_user_id) if session.target_user_id else None
        if target is None or not target.is_active:
            session.ended_at = now
            session.end_reason = ImpersonationEndReason.TARGET_DISABLED
            await self.db.commit()
            raise invalid

        session.handoff_used_at = now
        # The code is spent; clearing the digest means a replay cannot even
        # find the row to be refused on.
        session.handoff_digest = None

        token, expires_at = create_access_token(
            user_id=target.id,
            organization_id=target.organization_id,
            role=target.role.value,
            # The token must not outlive the session, and must not be
            # extended by the ordinary access-token setting either way.
            expires_delta=_utc(session.expires_at) - now,
            impersonation=ImpersonationClaim(
                session_id=session.id,
                admin_user_id=session.admin_user_id or target.id,
                admin_email=session.admin_email,
            ),
        )
        await self.db.commit()
        await self.db.refresh(session)
        return session, target, token, expires_at

    async def count_write(self, session: ImpersonationSession) -> None:
        """Record that a write request was admitted in this session.

        Counted on admission rather than on success: a handler that then
        failed still had the chance to change something, and an audit trail
        that only records the writes that worked is the wrong way round.
        """
        session.writes_performed += 1
        await self.db.commit()

    async def resolve_active(self, session_id: uuid.UUID) -> ImpersonationSession | None:
        """The live session behind a token, or None if it may no longer be used.

        Called on every authenticated request carrying an `imp` claim, which is
        what makes ending a session take effect immediately rather than
        whenever the token happens to expire.
        """
        session = await self.db.get(ImpersonationSession, session_id)
        if session is None or session.is_revoked or session.ended_at is not None:
            return None
        if _utc(session.expires_at) < datetime.now(UTC):
            # Close it out lazily rather than running a sweeper: the first
            # request after expiry is the cheapest place to notice.
            session.ended_at = _utc(session.expires_at)
            session.end_reason = ImpersonationEndReason.EXPIRED
            await self.db.commit()
            return None
        return session

    async def end(
        self,
        session: ImpersonationSession,
        *,
        reason: ImpersonationEndReason,
        actor_email: str | None = None,
    ) -> ImpersonationSession:
        if session.ended_at is not None:
            return session
        now = datetime.now(UTC)
        session.ended_at = now
        session.end_reason = reason
        session.handoff_digest = None
        if reason is ImpersonationEndReason.REVOKED:
            session.is_revoked = True

        minutes = max(0, int((now - _utc(session.created_at)).total_seconds() // 60))
        self.db.add(
            PlatformEvent(
                actor_user_id=session.admin_user_id,
                actor_email=actor_email or session.admin_email,
                action=f"impersonation.{reason.value}",
                organization_id=session.organization_id,
                target=session.target_email,
                detail=(
                    f"{minutes} min, {session.writes_performed} write(s) made"
                    if session.writes_performed
                    else f"{minutes} min, read only"
                ),
                occurred_at=now,
            )
        )
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def active_sessions(self) -> list[ImpersonationSession]:
        now = datetime.now(UTC)
        rows = (
            await self.db.execute(
                select(ImpersonationSession)
                .where(
                    ImpersonationSession.ended_at.is_(None),
                    ImpersonationSession.expires_at > now,
                )
                .order_by(ImpersonationSession.created_at.desc())
            )
        ).scalars()
        return list(rows)

    async def recent_sessions(self, limit: int = 50) -> list[ImpersonationSession]:
        rows = (
            await self.db.execute(
                select(ImpersonationSession)
                .order_by(ImpersonationSession.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        return list(rows)
