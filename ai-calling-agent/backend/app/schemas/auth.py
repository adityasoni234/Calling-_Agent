from __future__ import annotations

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
