from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import AuthServiceDep, CurrentUser, client_ip
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserRead, UserUpdate, UserWithOrganization

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
