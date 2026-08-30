"""The media plane: one WebSocket per live call.

This is the only place in the codebase where latency is measured in
milliseconds. It holds call state in memory and writes to Postgres only at the
end, because a database round trip inside the audio loop is audible.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.conversation import ConversationManager, ConversationResult
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.agent import Agent
from app.models.call import Call, CallStatus
from app.models.lead import Lead
from app.services.base import UsageRecord
from app.services.call_service import CallService
from app.services.campaign_service import CampaignService
from app.services.cost_service import CostService
from app.services.knowledge.retriever import Retriever
from app.services.registry import get_llm, get_stt, get_telephony, get_tts
from app.services.telephony.region import region_of
from app.tasks.queue import enqueue_post_call

router = APIRouter(tags=["media"])
log = get_logger(__name__)


class WebSocketSink:
    """Adapts the conversation manager's audio output to the provider's frames."""

    def __init__(self, websocket: WebSocket, provider_name: str) -> None:
        self.websocket = websocket
        self.provider = get_telephony(provider_name)
        self.stream_id: str | None = None

    async def send(self, audio: bytes) -> None:
        await self.websocket.send_text(
            json.dumps(self.provider.encode_media(audio, self.stream_id))
        )

    async def clear(self) -> None:
        message = self.provider.clear_message(self.stream_id)
        if message:
            await self.websocket.send_text(json.dumps(message))


@router.websocket("/media/{call_id}")
async def media_stream(websocket: WebSocket, call_id: uuid.UUID) -> None:
    await websocket.accept()

    async with SessionLocal() as db:
        call = await db.get(Call, call_id)
        if call is None:
            await websocket.close(code=4404)
            return
        agent = await db.get(Agent, call.agent_id)
        if agent is None:
            await websocket.close(code=4404)
            return
        lead = await db.get(Lead, call.lead_id) if call.lead_id else None
        lead_name = lead.name if lead else None
        knowledge_base_id = agent.knowledge_base_id

        if call.answered_at is None:
            call.answered_at = datetime.now(UTC)
            call.status = CallStatus.IN_PROGRESS
            await db.commit()

    provider = get_telephony(call.provider)
    sink = WebSocketSink(websocket, call.provider)
    stt_session = await get_stt().open(
        language=settings.stt_language,
        sample_rate=provider.sample_rate,
        encoding=provider.encoding,
    )

    async def retrieve(query: str) -> tuple[list[str], list[UsageRecord]]:
        if knowledge_base_id is None:
            return [], []
        async with SessionLocal() as session:
            return await Retriever(session).search(knowledge_base_id, query)

    manager = ConversationManager(
        agent=agent,
        stt=stt_session,
        llm=get_llm(),
        tts=get_tts(),
        sink=sink,
        retrieve=retrieve if knowledge_base_id else None,
        lead_name=lead_name,
    )

    conversation = asyncio.create_task(manager.run())
    log.info("media.started", call_id=str(call_id), provider=call.provider)

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)

            stream_id = provider.stream_id_from(message)
            if stream_id:
                sink.stream_id = stream_id

            if message.get("event") in {"stop", "closed"}:
                break

            audio = provider.decode_media(message)
            if audio:
                await stt_session.send_audio(audio)

            if conversation.done():
                break
    except WebSocketDisconnect:
        log.info("media.disconnected", call_id=str(call_id))
    except Exception as exc:
        log.error("media.error", call_id=str(call_id), error=str(exc))
    finally:
        await stt_session.close()
        if not conversation.done():
            await manager.stop("carrier_hangup")
            try:
                await asyncio.wait_for(conversation, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                conversation.cancel()

        result = (
            conversation.result()
            if conversation.done() and not conversation.cancelled()
            else manager.result
        )
        await _persist(call_id, result)
        with_suppressed_close(websocket)


def with_suppressed_close(websocket: WebSocket) -> None:
    """Closing an already-closed socket is not an error worth logging."""
    try:
        asyncio.create_task(websocket.close())
    except RuntimeError:
        pass


async def _persist(call_id: uuid.UUID, result: ConversationResult) -> None:
    """Flush the call to Postgres, then hand off to post-call processing."""
    async with SessionLocal() as db:
        call = await db.get(Call, call_id)
        if call is None:
            return

        service = CallService(db)
        await service.save_turns(
            call_id,
            [
                {
                    "role": turn.role,
                    "content": turn.content,
                    "state": turn.state,
                    "latency_ms": turn.latency_ms,
                    "barge_in": turn.barge_in,
                }
                for turn in result.turns
            ],
        )

        call.ended_at = datetime.now(UTC)
        if call.answered_at:
            call.duration_seconds = max(0, int((call.ended_at - call.answered_at).total_seconds()))
        call.status = CallStatus.COMPLETED
        call.end_reason = result.end_reason

        records = list(result.usage.records)
        if call.duration_seconds > 0:
            records.append(
                get_telephony(call.provider).usage_for_call(
                    call.duration_seconds, region=region_of(call.to_number)
                )
            )
        await CostService(db).record_usage(call=call, records=records, commit=False)
        await db.commit()

        if call.campaign_id:
            await CampaignService(db).on_call_finished(call)

    await enqueue_post_call(call_id)
    log.info("media.finished", call_id=str(call_id), reason=result.end_reason)
