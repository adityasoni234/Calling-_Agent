from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge import DocumentStatus


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class KnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str
    created_at: datetime


class KnowledgeBaseDetail(KnowledgeBaseRead):
    document_count: int
    chunk_count: int


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    source_type: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    chunk_count: int
    error: str | None
    created_at: datetime


class FaqCreate(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=1, max_length=8000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=4, ge=1, le=20)


class SearchHit(BaseModel):
    content: str


class SearchResponse(BaseModel):
    hits: list[SearchHit]
