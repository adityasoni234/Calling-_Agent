from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import BCRYPT_MAX_BYTES
from app.schemas.user import UserRead


class PasswordMixin(BaseModel):
    password: str = Field(min_length=10, max_length=BCRYPT_MAX_BYTES)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        # bcrypt operates on bytes; a 60-character password can still exceed 72 bytes.
        if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
        if value.isdigit() or value.isalpha():
            raise ValueError("Password must mix letters with digits or symbols")
        return value


class RegisterRequest(PasswordMixin):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires


class AuthResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class ChangePasswordRequest(PasswordMixin):
    current_password: str = Field(min_length=1, max_length=256)


class SupportSessionExchange(BaseModel):
    """Trading a one-time handoff code for a support session."""

    code: str = Field(min_length=16, max_length=200)


class SupportSessionBanner(BaseModel):
    """What the customer app shows across the top of every page.

    Everything here is about making the session impossible to forget: who is
    really signed in, whose account this is, whether it can change anything,
    and how long is left. A support tool that looks like an ordinary session
    is one somebody will eventually mistake for their own.
    """

    session_id: uuid.UUID
    admin_email: str
    target_email: str
    organization_name: str
    read_only: bool
    expires_at: datetime
    reason: str


class SupportSessionResponse(BaseModel):
    """The exchange result.

    Deliberately not an `AuthResponse`: there is no refresh token, because a
    support session must end when the clock says so rather than renewing
    itself behind whoever opened it.
    """

    user: UserRead
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    session: SupportSessionBanner
