"""The conversation engine: turn-taking, barge-in, silence, and cost accounting."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agents.conversation import ConversationManager
from app.agents.state import ConversationState
from app.models.agent import Agent, AgentLanguage
from app.models.call import UsageComponent
from app.services.llm.mock import MockLLMProvider
from app.services.stt.base import STTEvent, STTEventType, STTSession
from app.services.stt.mock import MockSTTSession
from app.services.tts.base import TTSProvider


class RecordingSink:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.clears = 0

    async def send(self, audio: bytes) -> None:
        self.frames.append(audio)

    async def clear(self) -> None:
        self.clears += 1


class SlowTTS(TTSProvider):
    """Long enough to still be talking when the customer interrupts."""

    name = "slow"

    async def stream(  # type: ignore[override]
        self, text: str, *, voice_config: dict[str, Any], sample_rate: int = 8000, encoding: str = "mulaw"
    ) -> AsyncIterator[bytes]:
        for _ in range(200):
            await asyncio.sleep(0.01)
            yield b"\xff" * 160


class ScriptedSTT(STTSession):
    """Emits a fixed event sequence on a timeline, ignoring the audio."""

    def __init__(self, script: list[tuple[float, STTEvent]]) -> None:
        self.script = script
        self.closed = False

    async def send_audio(self, chunk: bytes) -> None:
        return None

    async def events(self) -> AsyncIterator[STTEvent]:  # type: ignore[override]
        for delay, event in self.script:
            if self.closed:
                return
            await asyncio.sleep(delay)
            yield event
        while not self.closed:
            await asyncio.sleep(0.05)

    async def close(self) -> None:
        self.closed = True

    @property
    def usage(self) -> list:
        return []


def make_agent(**overrides: Any) -> Agent:
    defaults = dict(
        name="Riya",
        role_title="Sales Executive",
        company_name="Acme",
        personality="Warm",
        primary_objective="Book a demo",
        secondary_objectives=[],
        language=AgentLanguage.AUTO,
        greeting="Hello, this is Riya from Acme.",
        system_instructions="",
        forbidden_rules=[],
        qualification_questions=[],
        ending_rules=[],
        objection_handling=[],
        transfer_rules={},
        voice_config={},
        llm_model=None,
        temperature=0.5,
        max_call_seconds=60,
        silence_prompt_ms=600,
        silence_hangup_ms=1500,
        interruptible=True,
    )
    return Agent(**{**defaults, **overrides})


async def test_greeting_is_spoken_first_and_recorded() -> None:
    sink = RecordingSink()
    stt = ScriptedSTT([(0.05, STTEvent(STTEventType.FINAL, text="Haan boliye"))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.4)
    await manager.stop("test")
    result = await asyncio.wait_for(task, timeout=3)

    assert result.turns[0].role == "agent"
    assert result.turns[0].content == "Hello, this is Riya from Acme."
    assert sink.frames, "no audio was sent to the carrier"


async def test_barge_in_stops_the_agent_and_flushes_carrier_audio() -> None:
    sink = RecordingSink()
    stt = ScriptedSTT(
        [
            (0.15, STTEvent(STTEventType.SPEECH_STARTED)),
            (0.05, STTEvent(STTEventType.FINAL, text="ruko ruko")),
        ]
    )
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.6)
    frames_at_interrupt = len(sink.frames)
    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)

    # The clear message is what stops audio the carrier has already buffered.
    assert sink.clears >= 1
    # The greeting would have run to 200 frames without the interruption.
    assert frames_at_interrupt < 200


async def test_barge_in_is_ignored_when_the_agent_is_not_interruptible() -> None:
    sink = RecordingSink()
    stt = ScriptedSTT([(0.15, STTEvent(STTEventType.SPEECH_STARTED))])
    manager = ConversationManager(
        agent=make_agent(interruptible=False),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.4)
    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)

    assert sink.clears == 0


async def test_silence_prompts_then_ends_the_call() -> None:
    sink = RecordingSink()
    stt = ScriptedSTT([])
    manager = ConversationManager(
        agent=make_agent(silence_prompt_ms=300, silence_hangup_ms=900),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    result = await asyncio.wait_for(manager.run(), timeout=8)

    spoken = [turn.content for turn in result.turns if turn.role == "agent"]
    assert any("still there" in line for line in spoken)
    assert result.end_reason == "silence"
    assert stt.closed


async def test_customer_saying_goodbye_completes_the_call() -> None:
    stt = ScriptedSTT([(0.05, STTEvent(STTEventType.FINAL, text="ok thank you, bye"))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    result = await asyncio.wait_for(manager.run(), timeout=8)

    assert result.state is ConversationState.COMPLETE
    assert result.end_reason in {"completed", "agent_ended"}


async def test_usage_is_recorded_for_every_component() -> None:
    stt = ScriptedSTT([(0.05, STTEvent(STTEventType.FINAL, text="kitna price hai?"))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.5)
    await manager.stop("test")
    result = await asyncio.wait_for(task, timeout=3)

    components = {record.component for record in result.usage.records}
    assert UsageComponent.TTS in components
    assert UsageComponent.LLM in components
    # Every line must carry a positive quantity or it cannot be costed.
    assert all(record.quantity > 0 for record in result.usage.records)


async def test_retrieval_runs_only_when_the_turn_needs_facts() -> None:
    calls: list[str] = []

    async def retrieve(query: str):
        calls.append(query)
        return ["Our starter plan covers one thousand minutes."], []

    stt = ScriptedSTT(
        [
            (0.05, STTEvent(STTEventType.FINAL, text="haan ji")),
            (0.35, STTEvent(STTEventType.FINAL, text="pricing kitna hai?")),
        ]
    )
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        retrieve=retrieve,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(1.2)
    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)

    # "haan ji" is chit-chat; only the pricing question should hit the index.
    assert calls == ["pricing kitna hai?"]


async def test_mock_stt_session_scripts_turns_from_audio() -> None:
    session = MockSTTSession(["first", "second"], audio_ms_per_turn=100)
    collected: list[STTEvent] = []

    async def collect() -> None:
        async for event in session.events():
            collected.append(event)

    task = asyncio.create_task(collect())
    for _ in range(10):
        await session.send_audio(b"\xff" * 160)  # 20 ms per frame
    await asyncio.sleep(0.05)
    await session.close()
    await asyncio.wait_for(task, timeout=2)

    finals = [event.text for event in collected if event.type is STTEventType.FINAL]
    assert finals == ["first", "second"]
    assert session.usage[0].component is UsageComponent.STT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kitna price hai?", True),
        ("what is the warranty", True),
        ("haan theek hai", False),
        ("hmm", False),
    ],
)
def test_knowledge_gate(text: str, expected: bool) -> None:
    assert ConversationManager._needs_knowledge(text) is expected
