from __future__ import annotations

import uuid

import pytest

from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.services.auth_service import slugify


def test_password_round_trip() -> None:
    hashed = hash_password("correct-horse-9")
    assert hashed != "correct-horse-9"
    assert verify_password("correct-horse-9", hashed)
    assert not verify_password("wrong-horse-9", hashed)


def test_password_longer_than_bcrypt_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("a" * 73)


def test_verify_password_survives_a_corrupt_hash() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_access_token_round_trip() -> None:
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    token, _ = create_access_token(user_id=user_id, organization_id=org_id, role="owner")

    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["org"] == str(org_id)
    assert payload["typ"] == "access"


def test_tampered_token_is_rejected() -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    with pytest.raises(AuthenticationError):
        decode_access_token(token[:-2] + "xy")


def test_refresh_tokens_are_stored_only_as_digests() -> None:
    plaintext, digest = generate_refresh_token()
    assert digest == hash_refresh_token(plaintext)
    assert plaintext not in digest
    assert len(digest) == 64


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Acme Sales", "acme-sales"), ("  Über GmbH ", "uber-gmbh"), ("!!!", "org")],
)
def test_slugify(value: str, expected: str) -> None:
    assert slugify(value) == expected


def test_cors_origins_parse_from_a_comma_separated_string() -> None:
    from app.core.config import Settings

    settings = Settings(cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
