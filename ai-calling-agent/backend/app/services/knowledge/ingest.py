"""Document ingestion: extract -> chunk -> embed -> pgvector."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.knowledge import Document, DocumentChunk, DocumentStatus
from app.services.knowledge.chunker import chunk_text, estimate_tokens
from app.services.knowledge.extract import extract_text
from app.services.registry import get_embeddings

log = get_logger(__name__)
EMBED_BATCH = 64


class IngestService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest_bytes(
        self, document_id: uuid.UUID, data: bytes, *, filename: str, mime_type: str | None
    ) -> int:
        document = await self.db.get(Document, document_id)
        if document is None:
            return 0

        document.status = DocumentStatus.PROCESSING
        await self.db.commit()

        try:
            text_content = extract_text(data, filename=filename, mime_type=mime_type)
            count = await self._store_chunks(document, chunk_text(text_content))
        except Exception as exc:
            document.status = DocumentStatus.FAILED
            document.error = str(exc)[:500]
            await self.db.commit()
            log.error("ingest.failed", document_id=str(document_id), error=str(exc))
            raise

        log.info("ingest.completed", document_id=str(document_id), chunks=count)
        return count

    async def ingest_text(self, document_id: uuid.UUID, content: str) -> int:
        document = await self.db.get(Document, document_id)
        if document is None:
            return 0
        return await self._store_chunks(document, chunk_text(content))

    async def _store_chunks(self, document: Document, chunks: list[str]) -> int:
        # Re-ingesting replaces the old chunks rather than duplicating them.
        await self.db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))

        provider = get_embeddings()
        stored = 0
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            vectors, _usage = await provider.embed(batch)
            for offset, (content, vector) in enumerate(zip(batch, vectors, strict=False)):
                self.db.add(
                    DocumentChunk(
                        document_id=document.id,
                        knowledge_base_id=document.knowledge_base_id,
                        chunk_index=start + offset,
                        content=content,
                        token_estimate=estimate_tokens(content),
                        embedding=vector,
                        meta={"title": document.title},
                    )
                )
                stored += 1

        document.chunk_count = stored
        document.status = DocumentStatus.READY
        document.error = None
        await self.db.commit()
        return stored

    async def delete_document(self, document_id: uuid.UUID) -> None:
        document = await self.db.get(Document, document_id)
        if document:
            await self.db.delete(document)
            await self.db.commit()

    async def knowledge_base_for_agent(self, knowledge_base_id: uuid.UUID | None) -> bool:
        if knowledge_base_id is None:
            return False
        result = await self.db.execute(
            select(DocumentChunk.id)
            .where(DocumentChunk.knowledge_base_id == knowledge_base_id)
            .limit(1)
        )
        return result.first() is not None
