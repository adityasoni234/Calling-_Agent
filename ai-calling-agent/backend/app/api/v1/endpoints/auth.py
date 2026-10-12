from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import AuthServiceDep, CurrentUser, DbSession, client_ip, impersonation_of
from app.core.errors import ValidationFailedError
from app.models.impersonation import ImpersonationEndReason, ImpersonationMode
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SupportSessionBanner,
    SupportSessionExchange,
    SupportSessionResponse,
    TokenPair,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserRead, UserUpdate, UserWithOrganization
from app.services.impersonation import ImpersonationService

router = APIRouter(prefix="/auth", tags=["auth"])

ClientIp = Annotated[str | None, Depends(client_ip)]


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization and its owner account",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    auth_service: AuthServiceDep,
    ip: ClientIp,
) -> AuthResponse:
    user = await auth_service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organization_name=payload.organization_name,
    )
    tokens = await auth_service.issue_tokens(
        user, user_agent=request.headers.get("user-agent"), ip_address=ip
    )
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)


@router.post("/login", response_model=AuthResponse, summary="Exchange credentials for tokens")
async def login(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthServiceDep,
    ip: ClientIp,
) -> AuthResponse:
    user = await auth_service.authenticate(email=payload.email, password=payload.password)
    tokens = await auth_service.issue_tokens(
        user, user_agent=request.headers.get("user-agent"), ip_address=ip
    )
    return AuthResponse(user=UserRead.model_validate(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    auth_service: AuthServiceDep,
    ip: ClientIp,
) -> TokenPair:
    return await auth_service.rotate_refresh_token(
        payload.refresh_token, user_agent=request.headers.get("user-agent"), ip_address=ip
    )


@router.post("/logout", response_model=MessageResponse, summary="Revoke one refresh token")
async def logout(payload: RefreshRequest, auth_service: AuthServiceDep) -> MessageResponse:
    await auth_service.revoke_refresh_token(payload.refresh_token)
    return MessageResponse(message="Logged out")


@router.post(
    "/logout-all", response_model=MessageResponse, summary="Revoke every session for this user"
)
async def logout_all(user: CurrentUser, auth_service: AuthServiceDep) -> MessageResponse:
    await auth_service.revoke_all_for_user(user.id)
    return MessageResponse(message="All sessions revoked")


@router.get("/me", response_model=UserWithOrganization, summary="Current user and organization")
async def me(user: CurrentUser) -> UserWithOrganization:
    return UserWithOrganization.model_validate(user)


@router.patch("/me", response_model=UserRead, summary="Update the current user's profile")
async def update_me(
    payload: UserUpdate, user: CurrentUser, auth_service: AuthServiceDep
) -> UserRead:
    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
        await auth_service.db.commit()
        await auth_service.db.refresh(user)
    return UserRead.model_validate(user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password and revoke existing sessions",
)
async def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, auth_service: AuthServiceDep
) -> MessageResponse:
    await auth_service.change_password(user, current=payload.current_password, new=payload.password)
    return MessageResponse(message="Password changed; please log in again")


@router.post(
    "/impersonation/exchange",
    response_model=SupportSessionResponse,
    summary="Trade a support handoff code for a session",
)
async def exchange_support_session(
    payload: SupportSessionExchange,
    db: DbSession,
) -> SupportSessionResponse:
    """Unauthenticated by design: the code *is* the credential.

    It was minted for a platform admin who has already been authenticated on
    the console, it is single-use, and it is worth sixty seconds. Requiring a
    bearer token here would mean the customer app needed a session before it
    could get one.
    """
    session, user, token, expires_at = await ImpersonationService(db).exchange(payload.code)
    return SupportSessionResponse(
        user=UserRead.model_validate(user),
        access_token=token,
        expires_in=max(0, int((expires_at - datetime.now(UTC)).total_seconds())),
        session=SupportSessionBanner(
            session_id=session.id,
            admin_email=session.admin_email,
            target_email=session.target_email,
            organization_name=session.organization_name,
            read_only=session.mode is ImpersonationMode.READ_ONLY,
            expires_at=session.expires_at,
            reason=session.reason,
        ),
    )


@router.post(
    "/impersonation/end",
    response_model=MessageResponse,
    summary="Leave a support session",
)
async def end_support_session(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> MessageResponse:
    """Allowed even in a read-only session -- see `_IMPERSONATION_ESCAPE`."""
    session = impersonation_of(request)
    if session is None:
        raise ValidationFailedError("This is not a support session")
    await ImpersonationService(db).end(session, reason=ImpersonationEndReason.EXITED)
    return MessageResponse(message="Support session ended")


@router.get(
    "/impersonation/current",
    response_model=SupportSessionBanner | None,
    summary="The support session behind this request, if any",
)
async def current_support_session(
    request: Request,
    user: CurrentUser,
) -> SupportSessionBanner | None:
    """Lets the app render the banner after a reload without keeping its own
    copy of the session's state, which could go stale against a revocation."""
    session = impersonation_of(request)
    if session is None:
        return None
    return SupportSessionBanner(
        session_id=session.id,
        admin_email=session.admin_email,
        target_email=session.target_email,
        organization_name=session.organization_name,
        read_only=session.mode is ImpersonationMode.READ_ONLY,
        expires_at=session.expires_at,
        reason=session.reason,
    )
