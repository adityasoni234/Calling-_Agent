"""One pagination implementation, used by every list endpoint."""

from __future__ import annotations

from typing import Annotated, Any, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.schemas.common import Page

ModelT = TypeVar("ModelT", bound=BaseModel)

PageParam = Annotated[int, Query(ge=1)]
PageSizeParam = Annotated[int, Query(ge=1, le=200)]


async def paginate(
    db: AsyncSession,
    statement: Select[Any],
    *,
    page: int,
    page_size: int,
    schema: type[ModelT],
) -> Page[ModelT]:
    total = int(
        await db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )
    rows = await db.execute(statement.limit(page_size).offset((page - 1) * page_size))
    items = [schema.model_validate(row) for row in rows.scalars().unique()]
    return Page.build(items=items, total=total, page=page, page_size=page_size)
