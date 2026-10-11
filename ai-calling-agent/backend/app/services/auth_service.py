"""Authentication and session management.

Kept out of the route handlers so the same logic is reachable from background
tasks and tests without going through HTTP.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.security import (
    burn_password_check,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.billing import CreditEntry, CreditEntryKind
from app.models.organization import Organization
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.schemas.auth import TokenPair

log = get_logger(__name__)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_STRIP.sub("-", normalized.lower()).strip("-")
    return slug or "org"


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- lookups -------------------------------------------------------

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        return result.unique().scalar_one_or_none()

    async def organization_owner(self, organization_id: uuid.UUID) -> User | None:
        """The account an API key acts as. Oldest owner, so it is stable."""
        result = await self.db.execute(
            select(User)
            .where(
                User.organization_id == organization_id,
                User.role == UserRole.OWNER,
                User.is_active.is_(True),
            )
            .order_by(User.created_at)
            .limit(1)
        )
        return result.scalars().first()

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.unique().scalar_one_or_none()

    async def _unique_slug(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 1
        while True:
            exists = await self.db.execute(
                select(func.count()).select_from(Organization).where(Organization.slug == candidate)
            )
            if not exists.scalar_one():
                return candidate
            suffix += 1
            candidate = f"{base}-{suffix}"

    # --- registration --------------------------------------------------

    async def register(
        self, *, email: str, password: str, full_name: str, organization_name: str
    ) -> User:
        if not settings.allow_registration:
            raise PermissionDeniedError(
                "Self-registration is disabled", code="registration_disabled"
            )

        email = email.lower()
        if await self.get_user_by_email(email):
            raise ConflictError("An account with this email already exists", code="email_taken")

        organization = Organization(
            name=organization_name.strip(),
            slug=await self._unique_slug(organization_name),
            # Enough to place a few real calls. An account that cannot try the
            # product before paying will not convert.
            credit_balance=settings.trial_credits,
        )
        self.db.add(organization)
        await self.db.flush()

        # The opening ledger entry, so the balance has a provenance from row one.
        self.db.add(
            CreditEntry(
                organization_id=organization.id,
                kind=CreditEntryKind.GRANT,
                amount=settings.trial_credits,
                balance_after=settings.trial_credits,
                note="Trial credits on sign-up",
            )
        )

        user = User(
            organization_id=organization.id,
            email=email,
            full_name=full_name.strip(),
            hashed_password=hash_password(password),
            role=UserRole.OWNER,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        log.info("auth.registered", user_id=str(user.id), organization_id=str(organization.id))
        return user

    # --- login ---------------------------------------------------------

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self.get_user_by_email(email)

        # Verify against a dummy hash when the user is missing so that a wrong
        # email and a wrong password take the same amount of time.
        if user is None:
            burn_password_check(password)
            raise AuthenticationError("Incorrect email or password", code="invalid_credentials")

        if not verify_password(password, user.hashed_password):
            log.info("auth.login_failed", email=email)
            raise AuthenticationError("Incorrect email or password", code="invalid_credentials")

        if not user.is_active:
            raise PermissionDeniedError("This account is disabled", code="account_disabled")
        if not user.organization.is_active:
            raise PermissionDeniedError("This organization is disabled", code="org_disabled")

        user.last_login_at = datetime.now(UTC)
        await self.db.commit()
        return user

    # --- tokens --------------------------------------------------------

    async def issue_tokens(
        self, user: User, *, user_agent: str | None = None, ip_address: str | None = None
    ) -> TokenPair:
        access_token, expires_at = create_access_token(
            user_id=user.id, organization_id=user.organization_id, role=user.role.value
        )
        plaintext, digest = generate_refresh_token()

        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=digest,
                expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
                user_agent=(user_agent or "")[:400] or None,
                ip_address=ip_address,
            )
        )
        await self.db.commit()

        return TokenPair(
            access_token=access_token,
            refresh_token=plaintext,
            expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
        )

    async def _get_refresh_token(self, plaintext: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(plaintext))
        )
        return result.unique().scalar_one_or_none()

    async def rotate_refresh_token(
        self, plaintext: str, *, user_agent: str | None = None, ip_address: str | None = None
    ) -> TokenPair:
        stored = await self._get_refresh_token(plaintext)
        if stored is None:
            raise AuthenticationError("Invalid refresh token", code="token_invalid")

        if not stored.is_active:
            # A rotated-away or revoked token being replayed means it leaked.
            # Drop every session this user has and make them log in again.
            log.warning("auth.refresh_token_reuse", user_id=str(stored.user_id))
            await self.revoke_all_for_user(stored.user_id)
            raise AuthenticationError(
                "Refresh token is no longer valid", code="token_reuse_detected"
            )

        user = stored.user
        if not user.is_active:
            raise PermissionDeniedError("This account is disabled", code="account_disabled")

        access_token, expires_at = create_access_token(
            user_id=user.id, organization_id=user.organization_id, role=user.role.value
        )
        new_plaintext, new_digest = generate_refresh_token()
        replacement = RefreshToken(
            user_id=user.id,
            token_hash=new_digest,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
            user_agent=(user_agent or "")[:400] or None,
            ip_address=ip_address,
        )
        self.db.add(replacement)
        await self.db.flush()

        stored.revoked_at = datetime.now(UTC)
        stored.replaced_by_id = replacement.id
        await self.db.commit()

        return TokenPair(
            access_token=access_token,
            refresh_token=new_plaintext,
            expires_in=int((expires_at - datetime.now(UTC)).total_seconds()),
        )

    async def revoke_refresh_token(self, plaintext: str) -> None:
        stored = await self._get_refresh_token(plaintext)
        if stored and stored.revoked_at is None:
            stored.revoked_at = datetime.now(UTC)
            await self.db.commit()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
        )
        now = datetime.now(UTC)
        for token in result.unique().scalars():
            token.revoked_at = now
        await self.db.commit()

    # --- password ------------------------------------------------------

    async def change_password(self, user: User, *, current: str, new: str) -> None:
        if not verify_password(current, user.hashed_password):
            raise AuthenticationError("Current password is incorrect", code="invalid_credentials")
        user.hashed_password = hash_password(new)
        await self.db.commit()
        # Any session issued under the old password is no longer trustworthy.
        await self.revoke_all_for_user(user.id)
