from __future__ import annotations

from httpx import AsyncClient

from app.services.lead_service import normalize_phone

CSV = b"""Name,Phone,Email,Company
Amit Shah,9876500001,amit@example.com,Shah Industries
Neha Gupta,+91 98765 00002,,Gupta Exports
Broken Row,,no-phone@example.com,Nothing
Amit Shah,9876500001,dupe@example.com,Duplicate Row
"""


def test_phone_normalization() -> None:
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("00919876543210") == "+919876543210"
    assert normalize_phone("") == ""


async def test_create_lead_normalizes_the_number(
    client: AsyncClient, auth_headers: dict[str, str], lead: dict
) -> None:
    assert lead["phone_number"] == "+919876543210"
    assert lead["status"] == "new"
    assert lead["lead_score"] == 0


async def test_duplicate_phone_number_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str], lead: dict
) -> None:
    response = await client.post(
        "/leads",
        json={"name": "Someone Else", "phone_number": "+91 9876543210"},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_lead"


async def test_csv_import_deduplicates_and_reports_errors(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/leads/import",
        files={"file": ("leads.csv", CSV, "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["imported"] == 2          # two valid, unique rows
    assert body["skipped"] == 2           # one missing phone, one duplicate
    assert any("Row 4" in error for error in body["errors"])

    listing = await client.get("/leads", headers=auth_headers)
    assert listing.json()["total"] == 2


async def test_lead_search_and_filter(
    client: AsyncClient, auth_headers: dict[str, str], lead: dict
) -> None:
    found = await client.get("/leads", params={"search": "kumar"}, headers=auth_headers)
    assert found.json()["total"] == 1

    missing = await client.get("/leads", params={"search": "zzzz"}, headers=auth_headers)
    assert missing.json()["total"] == 0

    by_status = await client.get("/leads", params={"status": "qualified"}, headers=auth_headers)
    assert by_status.json()["total"] == 0


async def test_import_rejects_a_non_csv_upload(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/leads/import",
        files={"file": ("leads.txt", b"nope", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 422
