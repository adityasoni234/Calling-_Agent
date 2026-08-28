"""Test harness.

The suite runs against SQLite so it needs no Docker and no network. The schema
is created from the same `Base.metadata` the Alembic migration mirrors, and the
migration itself is exercised separately against Postgres in CI.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="calling-agent-tests-"))

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DIR / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-tests"
os.environ["BCRYPT_ROUNDS"] = "4"  # keep hashing cheap in tests
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ALLOW_REGISTRATION"] = "true"
os.environ["UPLOAD_DIR"] = str(_TMP_DIR / "uploads")
# Every provider defaults to its mock, so the suite needs no network.
for _provider in ("TELEPHONY", "STT", "LLM", "TTS", "EMBEDDING"):
    os.environ[f"{_provider}_PROVIDER"] = "mock"
os.environ["EMBEDDING_DIM"] = "256"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

REGISTRATION = {
    "email": "owner@example.com",
    "password": "correct-horse-9",
    "full_name": "Priya Sharma",
    "organization_name": "Acme Sales",
}


@pytest.fixture(autouse=True)
async def _fresh_schema() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver/api/v1") as http:
        yield http


@pytest.fixture
async def db_session() -> AsyncGenerator[object, None]:
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def registered(client: AsyncClient) -> dict:
    response = await client.post("/auth/register", json=REGISTRATION)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def auth_headers(registered: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered['tokens']['access_token']}"}


AGENT_PAYLOAD = {
    "name": "Riya",
    "role_title": "Sales Executive",
    "company_name": "Acme Telecom",
    "primary_objective": "Book a product demo",
    "language": "auto",
    "qualification_questions": ["What is your monthly call volume?"],
    "objection_handling": [{"objection": "too expensive", "response": "We start from a small plan."}],
    "forbidden_rules": ["Never promise a discount"],
    "ending_rules": ["End once a demo is booked"],
    "voice_config": {"voice_id": "test-voice", "language": "en"},
}


@pytest.fixture
async def agent(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    response = await client.post("/agents", json=AGENT_PAYLOAD, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def lead(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    response = await client.post(
        "/leads",
        json={"name": "Ravi Kumar", "phone_number": "9876543210", "company_name": "Kumar Traders"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()
