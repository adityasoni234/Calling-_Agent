"""Shared request dependencies."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import Capability, can
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.auth_service import AuthService
from app.services.integration_service import IntegrationService

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth_service: AuthServiceDep,
    db: DbSession,
) -> User:
    """Authenticate a browser session or a machine caller.

    An `X-API-Key` resolves to the owner of the key's organization. The key is
    organization-scoped and everything downstream keys off `organization_id`, so
    this gives an integration exactly the access its organization has without
    every endpoint needing to know whether a human or a CRM is calling.
    """
    api_key = request.headers.get("x-api-key")
    if api_key:
        key = await IntegrationService(db).resolve_key(api_key)
        if key is None:
            raise AuthenticationError("Invalid or revoked API key", code="api_key_invalid")
        owner = await auth_service.organization_owner(key.organization_id)
        if owner is None or not owner.is_active:
            raise AuthenticationError("Organization has no active owner", code="account_disabled")
        return owner

    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token or X-API-Key header", code="token_missing")

    payload = decode_access_token(credentials.credentials)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Malformed access token", code="token_invalid") from exc

    user = await auth_service.get_user(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is no longer active", code="account_disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_platform_admin(user: CurrentUser) -> User:
    """Guard for the platform surface.

    A separate flag rather than a UserRole, so no customer self-service path --
    registration, invites, role editing -- can ever grant it. It is set in the
    database by someone with shell access, deliberately.
    """
    if not user.is_platform_admin:
        raise PermissionDeniedError("Platform administrator access required")
    return user


PlatformAdmin = Annotated[User, Depends(get_platform_admin)]


def requires(capability: Capability) -> Callable[..., User]:
    """Guard an endpoint by capability.

    Used instead of naming roles at the call site: the rules then live in one
    reviewable table, and adding a role does not mean auditing every endpoint.
    """

    def _dependency(user: CurrentUser) -> User:
        if not can(user.role, capability):
            raise PermissionDeniedError(
                f"Your role ({user.role.value}) cannot {capability.value.replace('_', ' ')}"
            )
        return user

    return _dependency


def require_role(*roles: UserRole) -> Callable[[User], User]:
    """RBAC hook. Phase 1 ships one role per account; the enforcement point exists now."""
    allowed = set(roles)

    def _dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError(
                f"Requires one of: {', '.join(sorted(r.value for r in allowed))}"
            )
        return user

    return _dependency


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None
