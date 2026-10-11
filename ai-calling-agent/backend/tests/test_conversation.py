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
        self,
        text: str,
        *,
        voice_config: dict[str, Any],
        sample_rate: int = 8000,
        encoding: str = "mulaw",
    ) -> AsyncIterator[bytes]:
        for _ in range(200):
            await asyncio.sleep(0.01)
            yield b"\xff" * 160


class ScriptedSTT(STTSession):
    """Emits a fixed event sequence on a timeline, ignoring the audio."""

    def __init__(self, script: list[tuple[float, STTEvent]]) -> None:
        self.script = script
        self.closed = False
        self._closed_event = asyncio.Event()

    async def send_audio(self, chunk: bytes) -> None:
        return None

    async def events(self) -> AsyncIterator[STTEvent]:  # type: ignore[override]
        for delay, event in self.script:
            if self.closed:
                return
            await asyncio.sleep(delay)
            yield event
        await self._closed_event.wait()

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()

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
    # Long enough for the turn debounce plus a reply.
    await asyncio.sleep(1.4)
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

    # Spaced beyond the debounce so these stay two separate turns; finals that
    # arrive closer together are deliberately merged into one utterance.
    stt = ScriptedSTT(
        [
            (0.05, STTEvent(STTEventType.FINAL, text="haan ji")),
            (1.2, STTEvent(STTEventType.FINAL, text="pricing kitna hai?")),
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
    await asyncio.sleep(2.6)
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


def test_greeting_survives_a_template_without_spaces() -> None:
    """A missing space around {name} is audible in the first second of a call."""
    from app.agents.prompt import build_greeting

    agent = make_agent(greeting="Namaste{name}, main Riya bol rahi hoon.")
    assert build_greeting(agent, "Aditya Soni") == "Namaste Aditya Soni, main Riya bol rahi hoon."
    # No lead name must not strand a comma or leave a double space.
    assert build_greeting(agent, None) == "Namaste, main Riya bol rahi hoon."
    assert build_greeting(agent, "  ") == "Namaste, main Riya bol rahi hoon."


async def test_fragmented_finals_are_merged_into_one_utterance() -> None:
    """Deepgram splits a spoken sentence across several finals.

    Answering each fragment separately makes the agent interrupt itself and skip
    turns, which is exactly what happened on the first live call.
    """
    stt = ScriptedSTT(
        [
            (0.05, STTEvent(STTEventType.FINAL, text="haan boliye")),
            (0.15, STTEvent(STTEventType.FINAL, text="kaun bol raha hai?")),
        ]
    )
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(1.4)
    await manager.stop("test")
    result = await asyncio.wait_for(task, timeout=3)

    customer_turns = [turn.content for turn in result.turns if turn.role == "customer"]
    assert customer_turns == ["haan boliye kaun bol raha hai?"]


async def test_vad_alone_does_not_interrupt_the_agent() -> None:
    """A cough, room noise, or echo of our own voice fires the provider's VAD.

    Cancelling on that made the agent stop talking constantly, and with no
    transcript to follow it just sat silent — reported as the agent "hanging".
    """
    sink = RecordingSink()
    stt = ScriptedSTT(
        [
            (0.2, STTEvent(STTEventType.SPEECH_STARTED)),
            (0.2, STTEvent(STTEventType.SPEECH_STARTED)),
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
    await asyncio.sleep(0.9)
    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)

    assert sink.clears == 0, "VAD alone must not cut the agent off"


async def test_a_quiet_line_does_not_interrupt() -> None:
    """Partials produced from a silent line are echo or noise, not speech."""
    sink = RecordingSink()
    stt = ScriptedSTT([(0.7, STTEvent(STTEventType.PARTIAL, text="uh huh yeah"))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    # No audio is fed in, so the line has never been loud.
    await asyncio.sleep(1.1)
    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)

    assert sink.clears == 0


async def test_real_speech_on_a_loud_line_does_interrupt() -> None:
    """The gate must not block a genuine interruption."""
    sink = RecordingSink()
    stt = ScriptedSTT([(0.7, STTEvent(STTEventType.PARTIAL, text="ruko ek minute"))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.5)
    # Loud audio, as a real caller's line would be.
    manager.note_inbound_audio(bytes(range(120, 136)) * 20)
    await asyncio.sleep(0.6)
    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)

    assert sink.clears >= 1, "a real interruption must still cut the agent off"


async def test_a_false_interruption_resumes_instead_of_leaving_silence() -> None:
    """If nothing was actually said, finish the sentence rather than hang."""
    sink = RecordingSink()
    stt = ScriptedSTT([(0.7, STTEvent(STTEventType.PARTIAL, text="hmm okay"))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=sink,
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.5)
    manager.note_inbound_audio(bytes(range(120, 136)) * 20)
    await asyncio.sleep(0.4)
    assert sink.clears >= 1, "the noise should have interrupted"

    frames_at_interrupt = len(sink.frames)
    # No transcript follows, so the recovery window elapses and speech resumes.
    await asyncio.sleep(2.0)
    assert len(sink.frames) > frames_at_interrupt, "the agent should have resumed speaking"

    await manager.stop("test")
    await asyncio.wait_for(task, timeout=3)


async def test_end_of_speech_is_answered_without_waiting_out_the_debounce() -> None:
    """The debounce exists for mid-sentence finals only.

    When the provider's endpointing says the customer has stopped, waiting the
    full debounce on top of it is dead air the caller hears as a slow agent.
    """
    stt = ScriptedSTT([(0.05, STTEvent(STTEventType.FINAL, text="haan boliye", speech_final=True))])
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    # Comfortably under 0.05 + the 0.6s debounce, so only an immediate
    # dispatch can have produced a reply by now.
    await asyncio.sleep(0.35)
    await manager.stop("test")
    result = await asyncio.wait_for(task, timeout=3)

    assert [turn.content for turn in result.turns if turn.role == "customer"] == ["haan boliye"]
    assert any(turn.role == "agent" for turn in result.turns[1:])


async def test_a_mid_sentence_final_still_waits_for_the_rest() -> None:
    """Without the end-of-speech flag the debounce must still merge fragments."""
    stt = ScriptedSTT(
        [
            (0.05, STTEvent(STTEventType.FINAL, text="haan")),
            (0.15, STTEvent(STTEventType.FINAL, text="boliye kaun hai?")),
        ]
    )
    manager = ConversationManager(
        agent=make_agent(),
        stt=stt,
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(1.4)
    await manager.stop("test")
    result = await asyncio.wait_for(task, timeout=3)

    assert [turn.content for turn in result.turns if turn.role == "customer"] == [
        "haan boliye kaun hai?"
    ]


class BrokenTTS(SlowTTS):
    """A vendor whose account has run out of credit."""

    async def stream(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("[cartesia] 402: Insufficient credits")
        yield b""  # pragma: no cover - makes this an async generator


async def test_a_mute_agent_ends_the_call_instead_of_burning_minutes() -> None:
    """A dead TTS vendor used to leave the caller on an open, silent line.

    The call finished as "completed" with nothing recorded, so a broken vendor
    account looked exactly like a working call.
    """
    manager = ConversationManager(
        agent=make_agent(),
        stt=ScriptedSTT([(0.05, STTEvent(STTEventType.FINAL, text="hello", speech_final=True))]),
        llm=MockLLMProvider(),
        tts=BrokenTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    result = await asyncio.wait_for(task, timeout=8)

    assert result.end_reason == "tts_unavailable"
    assert result.provider_error is not None
    assert "cartesia" in result.provider_error
    assert "402" in result.provider_error


async def test_a_working_call_records_no_provider_error() -> None:
    manager = ConversationManager(
        agent=make_agent(),
        stt=ScriptedSTT([(0.05, STTEvent(STTEventType.FINAL, text="ok bye", speech_final=True))]),
        llm=MockLLMProvider(),
        tts=SlowTTS(),
        sink=RecordingSink(),
        pace_audio=False,
    )
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.6)
    await manager.stop("test")
    result = await asyncio.wait_for(task, timeout=5)

    assert result.provider_error is None
    assert result.end_reason != "tts_unavailable"
