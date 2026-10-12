"""The credential cache must not forget the database when its TTL lapses."""

from __future__ import annotations

import pytest

from app.services import credentials


@pytest.fixture(autouse=True)
def _clean() -> None:
    credentials.invalidate()


async def test_a_stale_entry_serves_the_database_not_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this replaced: fifteen seconds after an admin saved a key,
    every sync reader silently reverted to the environment -- which for a
    provider configured only through the admin page is nothing at all, so the
    provider un-configured itself while the UI still showed it green."""
    from_db = {"key_id": "rzp_from_db", "key_secret": "secret_from_db"}

    async def _stored(self, slug: str) -> dict[str, str]:  # noqa: ANN001
        return from_db

    monkeypatch.setattr("app.services.provider_service.ProviderService.credentials", _stored)

    resolved = await credentials.resolve("razorpay")
    assert resolved["key_id"] == "rzp_from_db"
    assert credentials.get_sync("razorpay")["key_id"] == "rzp_from_db"

    # Age the entry past its TTL without waiting for real time.
    stamp, value = credentials._cache["razorpay"]
    credentials._cache["razorpay"] = (stamp - credentials.TTL_SECONDS - 1, value)

    assert credentials.get_sync("razorpay")["key_id"] == "rzp_from_db"


async def test_a_provider_never_resolved_still_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback must survive: a fresh install with .env and no admin
    visit has to keep working."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_from_env", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_secret", "env_secret", raising=False)

    assert credentials.get_sync("razorpay")["key_id"] == "rzp_from_env"
