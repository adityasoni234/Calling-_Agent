"""Background work.

Uses arq (asyncio-native, one dependency) when Redis is reachable, and falls
back to an in-process task otherwise -- so a developer without a worker running
still gets summaries, and production still gets durability.
"""

from __future__ import annotations

import asyncio
import uuid

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
_pool = None
_pool_lock = asyncio.Lock()


async def get_pool():  # noqa: ANN201 - arq's pool type
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            try:
                from arq import create_pool
                from arq.connections import RedisSettings

                _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            except Exception as exc:
                log.warning("queue.unavailable", error=str(exc))
                return None
    return _pool


async def _enqueue(function: str, *args: object) -> bool:
    pool = await get_pool()
    if pool is None:
        return False
    try:
        await pool.enqueue_job(function, *args)
        return True
    except Exception as exc:
        log.warning("queue.enqueue_failed", function=function, error=str(exc))
        return False


async def enqueue_post_call(call_id: uuid.UUID) -> None:
    if await _enqueue("run_post_call", str(call_id)):
        return
    # No worker: do it here rather than silently dropping the summary.
    asyncio.create_task(run_post_call_inline(call_id))


async def enqueue_ingest(document_id: uuid.UUID, path: str, filename: str, mime: str) -> None:
    if await _enqueue("run_ingest", str(document_id), path, filename, mime):
        return
    asyncio.create_task(run_ingest_inline(document_id, path, filename, mime))


async def enqueue_campaign_dispatch(campaign_id: uuid.UUID) -> None:
    await _enqueue("run_campaign_dispatch", str(campaign_id))


async def run_post_call_inline(call_id: uuid.UUID) -> None:
    from app.db.session import SessionLocal
    from app.services.postcall_service import PostCallService

    try:
        async with SessionLocal() as db:
            await PostCallService(db).process(call_id)
    except Exception as exc:
        log.error("postcall.inline_failed", call_id=str(call_id), error=str(exc))


async def run_ingest_inline(document_id: uuid.UUID, path: str, filename: str, mime: str) -> None:
    from pathlib import Path

    from app.db.session import SessionLocal
    from app.services.knowledge.ingest import IngestService

    try:
        data = await asyncio.to_thread(Path(path).read_bytes)
        async with SessionLocal() as db:
            await IngestService(db).ingest_bytes(
                document_id, data, filename=filename, mime_type=mime
            )
    except Exception as exc:
        log.error("ingest.inline_failed", document_id=str(document_id), error=str(exc))
