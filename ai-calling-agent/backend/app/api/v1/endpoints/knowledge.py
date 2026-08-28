from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.knowledge import Document, DocumentChunk, DocumentStatus, KnowledgeBase
from app.schemas.common import MessageResponse
from app.schemas.knowledge import (
    DocumentRead,
    FaqCreate,
    KnowledgeBaseCreate,
    KnowledgeBaseDetail,
    KnowledgeBaseRead,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from app.services.knowledge.extract import detect_kind
from app.services.knowledge.ingest import IngestService
from app.services.knowledge.retriever import Retriever
from app.tasks.queue import enqueue_ingest

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def _get_kb(db: DbSession, user: CurrentUser, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.organization_id != user.organization_id:
        raise NotFoundError("Knowledge base not found")
    return kb


@router.get("", response_model=list[KnowledgeBaseDetail], summary="List knowledge bases")
async def list_bases(db: DbSession, user: CurrentUser) -> list[KnowledgeBaseDetail]:
    rows = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.organization_id == user.organization_id)
        .order_by(KnowledgeBase.created_at.desc())
    )
    result: list[KnowledgeBaseDetail] = []
    for kb in rows.scalars():
        documents = int(
            await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.knowledge_base_id == kb.id)
            )
            or 0
        )
        chunks = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.knowledge_base_id == kb.id)
            )
            or 0
        )
        result.append(
            KnowledgeBaseDetail(
                **KnowledgeBaseRead.model_validate(kb).model_dump(),
                document_count=documents,
                chunk_count=chunks,
            )
        )
    return result


@router.post(
    "",
    response_model=KnowledgeBaseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge base",
)
async def create_base(
    payload: KnowledgeBaseCreate, db: DbSession, user: CurrentUser
) -> KnowledgeBaseRead:
    kb = KnowledgeBase(organization_id=user.organization_id, **payload.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseRead.model_validate(kb)


@router.delete("/{kb_id}", response_model=MessageResponse, summary="Delete a knowledge base")
async def delete_base(kb_id: uuid.UUID, db: DbSession, user: CurrentUser) -> MessageResponse:
    await db.delete(await _get_kb(db, user, kb_id))
    await db.commit()
    return MessageResponse(message="Knowledge base deleted")


@router.get("/{kb_id}/documents", response_model=list[DocumentRead], summary="List documents")
async def list_documents(kb_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[DocumentRead]:
    await _get_kb(db, user, kb_id)
    rows = await db.execute(
        select(Document)
        .where(Document.knowledge_base_id == kb_id)
        .order_by(Document.created_at.desc())
    )
    return [DocumentRead.model_validate(document) for document in rows.scalars()]


@router.post(
    "/{kb_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF, DOCX, TXT, or Markdown file",
)
async def upload_document(
    kb_id: uuid.UUID, db: DbSession, user: CurrentUser, file: UploadFile = File(...)
) -> DocumentRead:
    await _get_kb(db, user, kb_id)
    filename = file.filename or "document"
    # Rejects unsupported types before anything is written to disk.
    detect_kind(filename, file.content_type)

    content = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(content) > limit:
        raise ValidationFailedError(
            f"File is larger than {settings.max_upload_mb} MB", code="file_too_large"
        )

    document = Document(
        knowledge_base_id=kb_id,
        organization_id=user.organization_id,
        title=Path(filename).name[:300],
        source_type="upload",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Store under an id-derived name so a hostile filename cannot escape the
    # upload directory.
    upload_dir = Path(settings.upload_dir)
    await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    path = upload_dir / f"{document.id}{Path(filename).suffix.lower()[:10]}"
    await asyncio.to_thread(path.write_bytes, content)

    await enqueue_ingest(document.id, str(path), filename, document.mime_type)
    return DocumentRead.model_validate(document)


@router.post(
    "/{kb_id}/faqs",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an FAQ entry",
)
async def add_faq(
    kb_id: uuid.UUID, payload: FaqCreate, db: DbSession, user: CurrentUser
) -> DocumentRead:
    await _get_kb(db, user, kb_id)
    body = f"Q: {payload.question}\n\nA: {payload.answer}"
    document = Document(
        knowledge_base_id=kb_id,
        organization_id=user.organization_id,
        title=payload.question[:300],
        source_type="faq",
        mime_type="text/plain",
        size_bytes=len(body.encode()),
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    await IngestService(db).ingest_text(document.id, body)
    await db.refresh(document)
    return DocumentRead.model_validate(document)


@router.delete(
    "/documents/{document_id}", response_model=MessageResponse, summary="Delete a document"
)
async def delete_document(
    document_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> MessageResponse:
    document = await db.get(Document, document_id)
    if document is None or document.organization_id != user.organization_id:
        raise NotFoundError("Document not found")
    await db.delete(document)
    await db.commit()
    return MessageResponse(message="Document deleted")


@router.post("/{kb_id}/search", response_model=SearchResponse, summary="Test retrieval")
async def search(
    kb_id: uuid.UUID, payload: SearchRequest, db: DbSession, user: CurrentUser
) -> SearchResponse:
    """Runs the same retrieval the agent uses, so you can see what it will
    actually be given before putting it on a call."""
    await _get_kb(db, user, kb_id)
    passages, _usage = await Retriever(db).search(kb_id, payload.query, top_k=payload.top_k)
    return SearchResponse(hits=[SearchHit(content=passage) for passage in passages])
