"""Similarity search over pgvector.

Postgres does the work with the `<=>` cosine-distance operator and an ivfflat
index. SQLite (the test database) has no vector type, so the same query is done
in Python -- correctness is identical, only the scale differs.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.knowledge import DocumentChunk
from app.services.base import UsageRecord
from app.services.registry import get_embeddings

log = get_logger(__name__)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


class Retriever:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(
        self,
        knowledge_base_id: uuid.UUID,
        query: str,
        *,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> tuple[list[str], list[UsageRecord]]:
        top_k = top_k or settings.rag_top_k
        min_score = settings.rag_min_score if min_score is None else min_score

        vectors, usage = await get_embeddings().embed([query])
        if not vectors:
            return [], usage
        vector = vectors[0]

        if self.db.bind and self.db.bind.dialect.name == "postgresql":
            rows = await self.db.execute(
                text(
                    """
                    SELECT content, 1 - (embedding <=> CAST(:vec AS vector)) AS score
                    FROM document_chunks
                    WHERE knowledge_base_id = :kb AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT :k
                    """
                ),
                {
                    "vec": "[" + ",".join(str(v) for v in vector) + "]",
                    "kb": knowledge_base_id,
                    "k": top_k,
                },
            )
            hits = [(row.content, float(row.score)) for row in rows]
        else:
            result = await self.db.execute(
                select(DocumentChunk).where(DocumentChunk.knowledge_base_id == knowledge_base_id)
            )
            scored = [
                (chunk.content, cosine_similarity(vector, chunk.embedding))
                for chunk in result.scalars()
                if chunk.embedding
            ]
            hits = sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]

        passages = [content for content, score in hits if score >= min_score]
        log.info("rag.search", hits=len(hits), kept=len(passages))
        return passages, usage
