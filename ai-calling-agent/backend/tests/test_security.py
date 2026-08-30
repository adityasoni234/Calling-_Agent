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


def test_test_settings_ignore_the_developers_env_file(tmp_path, monkeypatch) -> None:
    """A key added to a local .env must not change how the suite behaves."""
    from app.core.config import Settings

    monkeypatch.setenv("APP_ENV", "test")
    settings = Settings()
    # Nothing from the repo .env should reach a test run.
    assert settings.telephony_webhook_secret == ""
    assert settings.twilio_auth_token == ""
    assert settings.anthropic_api_key == ""


def test_production_refuses_a_localhost_public_url() -> None:
    """A carrier cannot fetch an answer document from localhost.

    Booting anyway means every call fails with no obvious cause, so this is a
    startup error rather than a runtime surprise.
    """
    import pytest

    from app.core.config import Settings

    base = {
        "app_env": "production",
        "debug": False,
        "secret_key": "x" * 40,
        "cors_origins": "https://app.example.com",
        "telephony_provider": "twilio",
    }

    with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
        Settings(**base, public_base_url="http://localhost:8000")

    # Mock telephony never calls out, so it is allowed.
    Settings(**{**base, "telephony_provider": "mock"}, public_base_url="http://localhost:8000")
    Settings(**base, public_base_url="https://api.example.com")
