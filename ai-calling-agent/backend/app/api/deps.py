"""Shared request dependencies."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import (
    IMPERSONATION_FORBIDDEN,
    Capability,
    can,
    can_while_impersonating,
)
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.impersonation import ImpersonationMode, ImpersonationSession
from app.models.user import User, UserRole
from app.services.auth_service import AuthService
from app.services.impersonation import ImpersonationService
from app.services.integration_service import IntegrationService

bearer_scheme = HTTPBearer(auto_error=False)

#: Methods that cannot change anything, so a read-only session may use them.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The one write a read-only session must always be able to make: leaving.
#: Trapping staff inside a session they cannot exit would teach them to close
#: the tab instead, which leaves the session open for its full half hour.
_IMPERSONATION_ESCAPE = "/auth/impersonation/end"


def _guard_impersonated_method(request: Request, session: ImpersonationSession) -> None:
    """Refuse writes in a read-only session, whatever the endpoint asked for.

    `requires()` already gates by capability, but not every mutating endpoint
    is decorated with one -- and the set that is not is exactly the set nobody
    remembers to re-audit. Checking the HTTP method instead cannot be
    forgotten when a route is added, so this is the guarantee and the
    capability check is the better error message.
    """
    if session.mode is not ImpersonationMode.READ_ONLY:
        return
    if request.method in SAFE_METHODS:
        return
    if request.url.path.endswith(_IMPERSONATION_ESCAPE):
        return
    raise PermissionDeniedError(
        "This is a read-only support session, so it cannot change anything. "
        "Start a read-write session if the customer has asked you to fix something.",
        code="impersonation_read_only",
    )


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

    # A token carrying an `imp` claim is staff wearing a customer's face. The
    # session is re-checked on every request rather than trusted from the
    # signature, so ending one takes effect at once instead of whenever the
    # token would have expired on its own.
    imp = payload.get("imp")
    if imp:
        try:
            session_id = uuid.UUID(imp)
        except ValueError as exc:
            raise AuthenticationError("Malformed access token", code="token_invalid") from exc
        service = ImpersonationService(db)
        session = await service.resolve_active(session_id)
        if session is None:
            raise AuthenticationError("This support session has ended", code="impersonation_ended")
        request.state.impersonation = session
        _guard_impersonated_method(request, session)
        if request.method not in SAFE_METHODS:
            await service.count_write(session)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def impersonation_of(request: Request) -> ImpersonationSession | None:
    """The staff session behind this request, if it is one.

    Set by `get_current_user`, so it is only populated on routes that
    authenticate. Absent means an ordinary customer request.
    """
    return getattr(request.state, "impersonation", None)


CurrentImpersonation = Annotated["ImpersonationSession | None", Depends(impersonation_of)]


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

    def _dependency(user: CurrentUser, request: Request) -> User:
        if not can(user.role, capability):
            raise PermissionDeniedError(
                f"Your role ({user.role.value}) cannot {capability.value.replace('_', ' ')}"
            )
        session = impersonation_of(request)
        if session is not None:
            read_only = session.mode is ImpersonationMode.READ_ONLY
            if not can_while_impersonating(capability, read_only=read_only):
                action = capability.value.replace("_", " ")
                if capability in IMPERSONATION_FORBIDDEN:
                    raise PermissionDeniedError(
                        f"Support sessions can never {action}. This would spend the "
                        "customer's money or reach their contacts under their name. "
                        "Use the platform console, signed as yourself.",
                        code="impersonation_forbidden",
                    )
                raise PermissionDeniedError(
                    f"This is a read-only support session, so it cannot {action}. "
                    "Start a read-write session if the customer has asked you to "
                    "change something.",
                    code="impersonation_read_only",
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
