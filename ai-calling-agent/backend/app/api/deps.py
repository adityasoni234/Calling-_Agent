"""Shared request dependencies."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.auth_service import AuthService

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth_service: AuthServiceDep,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token", code="token_missing")

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
