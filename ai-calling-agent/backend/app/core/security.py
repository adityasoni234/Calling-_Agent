"""Password hashing and token issuance.

Access tokens are short-lived JWTs (stateless, cheap to verify on every request).
Refresh tokens are opaque random strings stored as SHA-256 digests in Postgres --
they are long-lived, so they must be revocable, and a JWT is not.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import AuthenticationError

ACCESS_TOKEN_TYPE = "access"
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """bcrypt silently truncates past 72 bytes, so reject rather than truncate."""
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database -- treat as a failed login, never a 500.
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("password-that-never-matches")


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check when the account does not exist.

    Without this, a missing email returns measurably faster than a wrong
    password and the login endpoint becomes a user-enumeration oracle.
    """
    verify_password(password, _dummy_hash())


def create_access_token(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id),
        "role": role,
        "typ": ACCESS_TOKEN_TYPE,
        "jti": secrets.token_urlsafe(8),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token", code="token_invalid") from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise AuthenticationError("Wrong token type", code="token_invalid")
    return payload


def generate_refresh_token() -> tuple[str, str]:
    """Return `(plaintext, digest)`. Only the digest is ever persisted."""
    plaintext = secrets.token_urlsafe(48)
    return plaintext, hash_refresh_token(plaintext)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
