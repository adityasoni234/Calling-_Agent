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
    assert body["imported"] == 2  # two valid, unique rows
    assert body["skipped"] == 2  # one missing phone, one duplicate
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


async def test_leads_can_be_sorted_by_score(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A pipeline view in creation order is useless — the best lead must lead."""
    created = []
    for index, score in enumerate([20, 90, 55]):
        lead = (
            await client.post(
                "/leads",
                json={"name": f"Lead {index}", "phone_number": f"98761000{index:02d}"},
                headers=auth_headers,
            )
        ).json()
        await client.patch(
            f"/leads/{lead['id']}",
            json={"lead_score": score, "status": "qualified"},
            headers=auth_headers,
        )
        created.append(score)

    ranked = await client.get("/leads?sort=score", headers=auth_headers)
    scores = [item["lead_score"] for item in ranked.json()["items"]]
    assert scores == sorted(created, reverse=True)


async def test_leads_filter_by_several_statuses(
    client: AsyncClient, auth_headers: dict[str, str], lead: dict
) -> None:
    await client.patch(f"/leads/{lead['id']}", json={"status": "qualified"}, headers=auth_headers)

    hit = await client.get("/leads?statuses=qualified,converted", headers=auth_headers)
    assert hit.json()["total"] == 1

    miss = await client.get("/leads?statuses=not_interested", headers=auth_headers)
    assert miss.json()["total"] == 0


async def test_an_upload_becomes_a_sheet_named_after_the_file(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    csv = b"name,phone\nSuresh,9876500011\nNeha,9876500012\n"
    response = await client.post(
        "/leads/import",
        files={"file": ("aditya 50.csv", csv, "text/csv")},
        headers=auth_headers,
    )
    body = response.json()
    assert body["imported"] == 2
    assert body["lead_list"]["name"] == "aditya 50"
    assert body["lead_list"]["source_filename"] == "aditya 50.csv"
    assert body["lead_list"]["lead_count"] == 2

    sheets = await client.get("/leads/lists", headers=auth_headers)
    assert [sheet["name"] for sheet in sheets.json()] == ["aditya 50"]


async def test_leads_can_be_filtered_to_one_sheet(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.post(
        "/leads/import",
        files={"file": ("batch-a.csv", b"name,phone\nA,9876500021\n", "text/csv")},
        headers=auth_headers,
    )
    await client.post(
        "/leads/import",
        files={"file": ("batch-b.csv", b"name,phone\nB,9876500022\nC,9876500023\n", "text/csv")},
        headers=auth_headers,
    )

    list_id = first.json()["lead_list"]["id"]
    only_a = await client.get(f"/leads?list_id={list_id}", headers=auth_headers)
    assert only_a.json()["total"] == 1
    assert only_a.json()["items"][0]["name"] == "A"

    everything = await client.get("/leads", headers=auth_headers)
    assert everything.json()["total"] == 3


async def test_uploading_the_same_filename_twice_makes_a_second_sheet(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Merging them silently would hide rows the user expects as their own tab."""
    for phone in ("9876500031", "9876500032"):
        await client.post(
            "/leads/import",
            files={"file": ("leads.csv", f"name,phone\nX,{phone}\n".encode(), "text/csv")},
            headers=auth_headers,
        )

    names = [
        sheet["name"] for sheet in (await client.get("/leads/lists", headers=auth_headers)).json()
    ]
    assert sorted(names) == ["leads", "leads (2)"]


async def test_a_number_on_two_sheets_appears_under_both(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """The second upload skips the duplicate lead but still files it."""
    rows = b"name,phone\nSame Person,9876500041\n"
    first = await client.post(
        "/leads/import", files={"file": ("one.csv", rows, "text/csv")}, headers=auth_headers
    )
    second = await client.post(
        "/leads/import", files={"file": ("two.csv", rows, "text/csv")}, headers=auth_headers
    )
    assert second.json()["imported"] == 0
    assert second.json()["skipped"] == 1

    for response in (first, second):
        list_id = response.json()["lead_list"]["id"]
        page = await client.get(f"/leads?list_id={list_id}", headers=auth_headers)
        assert page.json()["total"] == 1, "the lead must show under both sheets"


async def test_deleting_a_sheet_keeps_the_leads(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Losing contacts because a tab was tidied away would be indefensible."""
    created = await client.post(
        "/leads/import",
        files={"file": ("temp.csv", b"name,phone\nKeep Me,9876500051\n", "text/csv")},
        headers=auth_headers,
    )
    list_id = created.json()["lead_list"]["id"]

    removed = await client.delete(f"/leads/lists/{list_id}", headers=auth_headers)
    assert removed.status_code == 200

    assert (await client.get("/leads/lists", headers=auth_headers)).json() == []
    assert (await client.get("/leads", headers=auth_headers)).json()["total"] == 1


async def test_a_sheet_can_be_renamed(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await client.post(
        "/leads/import",
        files={"file": ("raw-export.csv", b"name,phone\nA,9876500061\n", "text/csv")},
        headers=auth_headers,
    )
    list_id = created.json()["lead_list"]["id"]

    renamed = await client.patch(
        f"/leads/lists/{list_id}", json={"name": "Diwali outreach"}, headers=auth_headers
    )
    assert renamed.json()["name"] == "Diwali outreach"
    # The original filename survives a rename.
    assert renamed.json()["source_filename"] == "raw-export.csv"
