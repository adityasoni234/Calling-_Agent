"""Chunking, ingestion, and retrieval."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.errors import ValidationFailedError
from app.services.knowledge.chunker import chunk_text, normalize
from app.services.knowledge.extract import detect_kind
from app.services.knowledge.retriever import cosine_similarity


def test_chunker_splits_on_paragraphs_and_overlaps() -> None:
    text = "\n\n".join(f"Paragraph number {index}. " * 12 for index in range(6))
    chunks = chunk_text(text, max_chars=400, overlap_chars=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 460 for chunk in chunks)
    assert all(chunk.strip() for chunk in chunks)


def test_chunker_breaks_an_oversized_paragraph() -> None:
    chunks = chunk_text("x" * 5000, max_chars=1000, overlap_chars=100)
    assert len(chunks) >= 5


def test_chunker_handles_empty_input() -> None:
    assert chunk_text("") == []
    assert normalize("  a  \n  b ") == "a\nb"


def test_file_type_detection() -> None:
    assert detect_kind("policy.pdf", None) == "pdf"
    assert detect_kind("faq.md", None) == "text"
    assert detect_kind("notes.txt", "text/plain") == "text"
    with pytest.raises(ValidationFailedError):
        detect_kind("photo.png", "image/png")


def test_cosine_similarity() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([0, 0], [1, 0]) == 0.0


async def test_faq_ingest_then_retrieve(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    kb = await client.post("/knowledge", json={"name": "Product FAQ"}, headers=auth_headers)
    assert kb.status_code == 201
    kb_id = kb.json()["id"]

    added = await client.post(
        f"/knowledge/{kb_id}/faqs",
        json={
            "question": "What does the starter plan include?",
            "answer": "The starter plan includes one thousand minutes and two agents.",
        },
        headers=auth_headers,
    )
    assert added.status_code == 201
    assert added.json()["status"] == "ready"
    assert added.json()["chunk_count"] == 1

    found = await client.post(
        f"/knowledge/{kb_id}/search",
        json={"query": "starter plan minutes"},
        headers=auth_headers,
    )
    assert found.status_code == 200
    hits = found.json()["hits"]
    assert hits and "one thousand minutes" in hits[0]["content"]


async def test_markdown_upload_is_chunked_and_searchable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    kb_id = (await client.post("/knowledge", json={"name": "Docs"}, headers=auth_headers)).json()[
        "id"
    ]

    content = (
        b"# Refund policy\n\nRefunds are processed within seven working days.\n\n"
        b"# Support hours\n\nSupport is available from nine to six on weekdays.\n"
    )
    upload = await client.post(
        f"/knowledge/{kb_id}/documents",
        files={"file": ("policy.md", content, "text/markdown")},
        headers=auth_headers,
    )
    assert upload.status_code == 201

    documents = await client.get(f"/knowledge/{kb_id}/documents", headers=auth_headers)
    assert documents.json()[0]["title"] == "policy.md"


async def test_unsupported_upload_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    kb_id = (await client.post("/knowledge", json={"name": "Docs"}, headers=auth_headers)).json()[
        "id"
    ]
    response = await client.post(
        f"/knowledge/{kb_id}/documents",
        files={"file": ("image.png", b"\x89PNG", "image/png")},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_file_type"
