"""The conversation manager: the hot path of the whole product.

Responsibilities, in the order they matter:

* turn-taking that never talks over the customer (barge-in),
* first audio out fast (stream LLM tokens into TTS at sentence boundaries),
* silence handling that recovers instead of hanging in dead air,
* accounting for every unit consumed, so the call can be costed.

Nothing here touches the database. State lives in memory for the duration of
the call and is flushed at turn boundaries by the caller, because a database
round trip inside the audio loop is audible.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.agents.prompt import build_greeting, build_system_prompt, build_turn_context
from app.agents.state import ConversationState, customer_is_closing, next_state
from app.core.audio import frame_duration_ms, rms_dbfs
from app.core.config import settings
from app.core.logging import get_logger
from app.models.agent import Agent
from app.services.base import UsageBag, UsageRecord
from app.services.llm.base import LLMMessage, LLMProvider
from app.services.stt.base import STTEventType, STTSession
from app.services.tts.base import TTSProvider

log = get_logger(__name__)

END_MARKER = "[END_CALL]"
TRANSFER_MARKER = "[TRANSFER]"
# Split on sentence enders so the first clause reaches TTS while the model is
# still generating the rest. This is most of the perceived latency win.
_SENTENCE = re.compile(r"(?<=[.!?।])\s+")
#: Clause breaks, used only to get the *first* audio out sooner.
_CLAUSE = re.compile(r"(?<=[,;:])\s+")
#: Below this a clause is too short to sound natural on its own.
FIRST_CLAUSE_MIN_CHARS = 45
# How long to wait for the customer to finish a sentence before replying.
# Measured against live Deepgram output: a single spoken sentence often
# arrives as two or three finals, and 0.3s was too tight to reassemble them.
# An explicit UtteranceEnd still dispatches immediately, so this only costs
# latency when the provider gives us no endpointing signal.


class AudioSink(Protocol):
    """Where synthesised audio goes -- the telephony websocket, or a test double."""

    async def send(self, audio: bytes) -> None: ...
    async def clear(self) -> None: ...


@dataclass
class Turn:
    role: str
    content: str
    state: str | None = None
    latency_ms: int | None = None
    barge_in: bool = False


@dataclass
class ConversationResult:
    turns: list[Turn] = field(default_factory=list)
    usage: UsageBag = field(default_factory=UsageBag)
    state: ConversationState = ConversationState.GREETING
    end_reason: str = "completed"
    transfer_requested: bool = False


RetrieveFn = Callable[[str], Awaitable[tuple[list[str], list[UsageRecord]]]]


class ConversationManager:
    def __init__(
        self,
        *,
        agent: Agent,
        stt: STTSession,
        llm: LLMProvider,
        tts: TTSProvider,
        sink: AudioSink,
        retrieve: RetrieveFn | None = None,
        lead_name: str | None = None,
        on_turn: Callable[[Turn], Awaitable[None]] | None = None,
        pace_audio: bool = True,
    ) -> None:
        self.agent = agent
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.sink = sink
        self.retrieve = retrieve
        self.lead_name = lead_name
        self.on_turn = on_turn
        self.pace_audio = pace_audio

        self.result = ConversationResult()
        self._system_prompt = build_system_prompt(agent)
        self._history: list[LLMMessage] = []
        self._state = ConversationState.GREETING
        self._speaking = False
        self._speak_task: asyncio.Task[None] | None = None
        self._pending_barge_in = False
        self._last_activity = time.monotonic()
        self._silence_prompted = False
        self._finished = asyncio.Event()
        self._started_at = time.monotonic()
        self._turn_index = 0
        self._pending_text = ""
        self._turn_timer: asyncio.Task[None] | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._speech_queue: asyncio.Queue[str] = asyncio.Queue()
        self._speaking_since = 0.0
        self._loud_since = 0.0
        self._interrupted_text = ""
        self._recover_task: asyncio.Task[None] | None = None
        self._current_utterance = ""
        self._wrapping_up = False

    # --- public -------------------------------------------------------

    async def run(self) -> ConversationResult:
        """Drive the call until it ends. Returns the transcript and usage."""
        watchdog = asyncio.create_task(self._watchdog())
        speaker = asyncio.create_task(self._speech_worker())
        # Transcription runs concurrently with speech from the first
        # millisecond. If it only started after the greeting, the customer
        # could not interrupt the greeting -- which is exactly when they do.
        consumer = asyncio.create_task(self._consume_stt())
        try:
            await self._say(
                build_greeting(self.agent, self.lead_name), state=ConversationState.GREETING
            )
            if self._state is ConversationState.GREETING:
                self._state = ConversationState.INTRODUCTION
            await self._finished.wait()
        except asyncio.CancelledError:
            self.result.end_reason = "canceled"
            raise
        finally:
            for task in (
                watchdog,
                consumer,
                speaker,
                self._turn_task,
                self._turn_timer,
                self._recover_task,
            ):
                if task is not None and not task.done():
                    task.cancel()
            await self._stop_speaking()
            self.result.usage.extend(self.stt.usage)
            self.result.state = self._state
        return self.result

    async def stop(self, reason: str = "hangup") -> None:
        self.result.end_reason = reason
        self._finished.set()
        await self._stop_speaking()

    # --- inbound speech ------------------------------------------------

    async def _consume_stt(self) -> None:
        """Read transcription events and dispatch turns.

        This loop must never block on synthesis. Turn handling runs in its own
        task so the customer can interrupt while the agent is mid-sentence.
        """
        async for event in self.stt.events():
            if self._finished.is_set():
                break
            self._last_activity = time.monotonic()

            if event.type is STTEventType.SPEECH_STARTED:
                # Deliberately not an interruption on its own: this fires on a
                # cough, room noise, or echo of the agent's own voice.
                pass

            elif event.type is STTEventType.PARTIAL:
                # Real words are the only reliable evidence that a person is
                # talking over us.
                if len(event.text.split()) >= settings.barge_in_min_words:
                    await self._handle_barge_in()

            elif event.type is STTEventType.FINAL and event.text.strip():
                # A final transcript is proof, whatever its length.
                await self._handle_barge_in(force=True)
                # A real transcript arrived, so the interruption was genuine.
                self._interrupted_text = ""
                if self._recover_task is not None and not self._recover_task.done():
                    self._recover_task.cancel()
                self._pending_text = f"{self._pending_text} {event.text}".strip()
                # Deepgram's endpointing has already decided the customer stopped,
                # so waiting out the debounce on top of it is dead air.
                self._schedule_turn(immediate=event.speech_final)

            elif event.type is STTEventType.UTTERANCE_END and self._pending_text:
                # The provider says the customer has stopped; no need to wait.
                self._schedule_turn(immediate=True)

        await self._finish("stream_ended")

    def _schedule_turn(self, *, immediate: bool = False) -> None:
        """Debounce before replying.

        People pause mid-sentence. Answering the fragment is worse than waiting
        a fraction of a second for the rest of it.
        """
        if self._turn_timer is not None and not self._turn_timer.done():
            self._turn_timer.cancel()
        delay = 0.0 if immediate else settings.turn_debounce_seconds
        self._turn_timer = asyncio.create_task(self._run_turn(delay))

    async def _run_turn(self, delay: float) -> None:
        if delay:
            await asyncio.sleep(delay)
        text, self._pending_text = self._pending_text, ""
        if not text or self._finished.is_set():
            return

        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
        self._turn_task = asyncio.create_task(self._handle_customer_turn(text))
        with contextlib.suppress(asyncio.CancelledError):
            await self._turn_task

    def note_inbound_audio(self, chunk: bytes) -> None:
        """Record how loud the caller's line is.

        Used as a gate on barge-in: a transcript produced from a quiet line is
        far more likely to be echo or noise than someone speaking.
        """
        if rms_dbfs(chunk) >= settings.barge_in_min_dbfs:
            self._loud_since = time.monotonic()

    def _may_interrupt(self) -> bool:
        if not (self._speaking and self.agent.interruptible and settings.barge_in_enabled):
            return False
        # Give each utterance a moment before it can be cut off, so the tail of
        # our own audio coming back does not interrupt us.
        started = time.monotonic() - self._speaking_since
        if started * 1000 < settings.barge_in_grace_ms:
            return False
        # Something must actually have been loud on the line recently.
        return (time.monotonic() - self._loud_since) < 1.0

    async def _handle_barge_in(self, *, force: bool = False) -> None:
        if not force and not self._may_interrupt():
            return
        if not self._speaking:
            return

        log.info("conversation.barge_in", forced=force)
        self._pending_barge_in = True
        # Keep what we were saying: if no transcript follows, this was noise and
        # we finish the sentence rather than leaving the caller in silence.
        self._interrupted_text = self._current_utterance
        await self._stop_speaking()
        # Drop whatever the carrier still has buffered, or the agent keeps
        # talking for another second after we stopped generating.
        await self.sink.clear()
        self._arm_recovery()

    def _arm_recovery(self) -> None:
        """Resume if the interruption turns out to have been nothing."""
        if self._recover_task is not None and not self._recover_task.done():
            self._recover_task.cancel()
        self._recover_task = asyncio.create_task(self._recover_after_false_barge_in())

    async def _recover_after_false_barge_in(self) -> None:
        await asyncio.sleep(settings.barge_in_recover_ms / 1000)
        # A real interruption produces a transcript, which clears this.
        if self._finished.is_set() or self._pending_text or not self._interrupted_text:
            return
        if self._turn_task is not None and not self._turn_task.done():
            return
        log.info("conversation.barge_in_recovered")
        text, self._interrupted_text = self._interrupted_text, ""
        self._pending_barge_in = False
        await self._enqueue_speech(text)

    async def _handle_customer_turn(self, text: str) -> None:
        # The customer has spoken, so stop talking even if no VAD event fired.
        await self._stop_speaking()
        # The flag has done its job (it stopped the previous utterance). Clear
        # it here or it suppresses the reply we are about to generate.
        interrupted, self._pending_barge_in = self._pending_barge_in, False
        started = time.monotonic()
        self._record(
            Turn(role="customer", content=text, state=self._state.value, barge_in=interrupted)
        )
        self._history.append(LLMMessage(role="user", content=text))

        self._state = next_state(self._state, text, turn_count=self._turn_index)
        self._turn_index += 1

        retrieved: list[str] = []
        if self.retrieve and self._needs_knowledge(text):
            try:
                retrieved, usage = await self.retrieve(text)
                self.result.usage.extend(usage)
            except Exception as exc:  # retrieval must never kill a live call
                log.warning("conversation.retrieval_failed", error=str(exc))

        context = build_turn_context(
            self._state,
            retrieved=retrieved,
            digest=self._digest(),
            wrapping_up=self._wrapping_up,
        )
        messages = self._compact_history()
        messages.append(LLMMessage(role="user", content=context))

        await self._speak_reply(messages, latency_from=started)

        if self._state is ConversationState.COMPLETE or customer_is_closing(text):
            # Let the closing line actually reach the caller. Finishing here
            # without draining the queue cuts the goodbye off mid-word, which
            # is what made the agent seem to hang up on people.
            await self._drain_speech()
            await self._finish("completed")

    @staticmethod
    def _needs_knowledge(text: str) -> bool:
        """Gate RAG on questions and fact words.

        Retrieving on every turn is the easiest way to make a call slower and
        more expensive for no benefit -- most turns are not factual.
        """
        lowered = text.lower()
        if "?" in text:
            return True
        triggers = (
            "price",
            "pricing",
            "cost",
            "charge",
            "fee",
            "plan",
            "feature",
            "support",
            "warranty",
            "refund",
            "policy",
            "how does",
            "what is",
            "delivery",
            "emi",
            "kitna",
            "kaise",
            "kya hai",
            "offer",
            "discount",
            "documents",
            "process",
        )
        return any(trigger in lowered for trigger in triggers)

    # --- outbound speech -----------------------------------------------

    async def _speech_worker(self) -> None:
        """Plays queued utterances one at a time.

        Decoupled from generation so the LLM stream can finish (and its usage be
        recorded, and its connection released) while audio is still playing.
        """
        while True:
            text = await self._speech_queue.get()
            try:
                await self._play(text)
            finally:
                self._speech_queue.task_done()

    async def _play(self, text: str) -> None:
        self._current_utterance = text
        self._speaking_since = time.monotonic()
        task = asyncio.create_task(self._pump_audio(text))
        self._speak_task = task
        try:
            # `asyncio.wait` rather than `await task`: a deliberate barge-in
            # cancellation of the child must not unwind this worker, while real
            # outer cancellation still propagates.
            await asyncio.wait({task})
        finally:
            self._speak_task = None

    async def _enqueue_speech(self, text: str) -> None:
        self.result.usage.add(self.tts.usage_for(text, self.agent.voice_config or {}))
        await self._speech_queue.put(text)

    async def _speak_reply(self, messages: list[LLMMessage], *, latency_from: float) -> None:
        buffer = ""
        spoken = ""
        first_audio_logged = False
        transfer = False
        end_call = False

        try:
            async for delta in self.llm.stream_chat(
                system=self._system_prompt,
                messages=messages,
                model=self.agent.llm_model,
                temperature=self.agent.temperature,
                max_tokens=settings.llm_max_tokens,
            ):
                if delta.usage:
                    self.result.usage.extend(delta.usage)
                if delta.done:
                    break
                buffer += delta.text

                # Flush complete sentences to TTS as they appear, so the first
                # clause is already playing while the rest is still generating.
                while True:
                    parts = _SENTENCE.split(buffer, maxsplit=1)
                    # Until something has been said, the caller is sitting in
                    # silence waiting for a whole sentence to finish generating.
                    # Break at the first clause instead; the rest queues in
                    # behind it and plays without a seam.
                    if len(parts) < 2 and not spoken and len(buffer) >= FIRST_CLAUSE_MIN_CHARS:
                        parts = _CLAUSE.split(buffer, maxsplit=1)
                    if len(parts) < 2:
                        break
                    sentence, buffer = parts[0].strip(), parts[1]
                    clean, end_call, transfer = self._strip_markers(sentence, end_call, transfer)
                    if clean:
                        if not first_audio_logged:
                            first_audio_logged = True
                            log.info(
                                "conversation.first_audio",
                                latency_ms=int((time.monotonic() - latency_from) * 1000),
                            )
                        spoken += clean + " "
                        await self._enqueue_speech(clean)
                    if self._pending_barge_in:
                        break
                if self._pending_barge_in:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("conversation.llm_failed", error=str(exc))
            buffer = buffer or "Sorry, I did not catch that. Could you repeat?"

        if buffer.strip() and not self._pending_barge_in:
            clean, end_call, transfer = self._strip_markers(buffer, end_call, transfer)
            if clean:
                spoken += clean
                await self._enqueue_speech(clean)

        barge_in, self._pending_barge_in = self._pending_barge_in, False
        reply = spoken.strip()
        if reply:
            self._history.append(LLMMessage(role="assistant", content=reply))
            self._record(
                Turn(
                    role="agent",
                    content=reply,
                    state=self._state.value,
                    latency_ms=int((time.monotonic() - latency_from) * 1000),
                    barge_in=barge_in,
                )
            )

        if transfer:
            self.result.transfer_requested = True
            await self._drain_speech()
            await self._finish("transfer_requested")
        elif end_call:
            await self._drain_speech()
            await self._finish("agent_ended")

    #: Longest we will hold a call open waiting for queued audio to finish.
    _DRAIN_TIMEOUT = 20.0

    async def _drain_speech(self) -> None:
        """Wait for queued audio to finish playing, but never hang on it."""
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            async with asyncio.timeout(self._DRAIN_TIMEOUT):
                await self._speech_queue.join()

    @staticmethod
    def _strip_markers(text: str, end_call: bool, transfer: bool) -> tuple[str, bool, bool]:
        if END_MARKER in text:
            end_call = True
            text = text.replace(END_MARKER, "")
        if TRANSFER_MARKER in text:
            transfer = True
            text = text.replace(TRANSFER_MARKER, "")
        return text.strip(), end_call, transfer

    async def _pump_audio(self, text: str) -> None:
        self._speaking = True
        try:
            async for frame in self.tts.stream(
                text,
                voice_config=self.agent.voice_config or {},
                sample_rate=settings.audio_sample_rate,
                encoding=settings.audio_encoding,
            ):
                await self.sink.send(frame)
                # Send at roughly real time. Dumping a whole utterance into the
                # carrier's buffer makes barge-in feel broken, because the audio
                # is already gone by the time we stop generating.
                if self.pace_audio:
                    await asyncio.sleep(frame_duration_ms(frame) / 1000 * 0.9)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("conversation.tts_failed", error=str(exc))
        finally:
            self._speaking = False

    async def _stop_speaking(self) -> None:
        """Silence the agent now: drop queued utterances and cancel the current one."""
        while not self._speech_queue.empty():
            self._speech_queue.get_nowait()
            self._speech_queue.task_done()

        task = self._speak_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})
        self._speaking = False

    async def _say(self, text: str, *, state: ConversationState) -> None:
        """Speak a fixed line (greeting, silence prompt) and wait for it."""
        self._history.append(LLMMessage(role="assistant", content=text))
        self._record(Turn(role="agent", content=text, state=state.value))
        await self._enqueue_speech(text)
        with contextlib.suppress(asyncio.CancelledError):
            await self._speech_queue.join()

    # --- silence and limits --------------------------------------------

    async def _watchdog(self) -> None:
        """Recover from dead air, and enforce the maximum call length."""
        while not self._finished.is_set():
            await asyncio.sleep(0.25)
            if self._speaking:
                self._last_activity = time.monotonic()
                continue

            idle_ms = (time.monotonic() - self._last_activity) * 1000
            elapsed = time.monotonic() - self._started_at

            # Warn the model before the cap so it can land the conversation
            # rather than being cut off mid-sentence.
            if not self._wrapping_up and elapsed > self.agent.max_call_seconds * 0.75:
                self._wrapping_up = True
                log.info("conversation.wrapping_up", elapsed=int(elapsed))

            if elapsed > self.agent.max_call_seconds:
                # Never drop the line silently: say goodbye first. Hanging up
                # mid-conversation with no word is the rudest thing an agent
                # can do, and it reads as a broken system.
                await self._say(
                    "I have taken enough of your time for now. Thank you so much, "
                    "and I will follow up. Have a good day.",
                    state=ConversationState.COMPLETE,
                )
                await self._finish("max_duration")
                return

            if idle_ms >= self.agent.silence_hangup_ms:
                await self._say(
                    "I could not hear you, so I will let you go. Thank you for your time.",
                    state=self._state,
                )
                await self._finish("silence")
                return

            if idle_ms >= self.agent.silence_prompt_ms and not self._silence_prompted:
                self._silence_prompted = True
                self._last_activity = time.monotonic()
                await self._say("Hello, are you still there?", state=self._state)

    async def _finish(self, reason: str) -> None:
        if self._finished.is_set():
            return
        self.result.end_reason = reason
        self._finished.set()
        await self.stt.close()

    # --- context management ---------------------------------------------

    def _compact_history(self) -> list[LLMMessage]:
        """Keep the tail verbatim; everything older becomes a short digest.

        Resending the full history makes turn N cost O(N) tokens. The digest is
        built locally, so trimming context costs nothing.
        """
        limit = settings.context_max_turns
        if len(self._history) <= limit:
            return list(self._history)
        return list(self._history[-limit:])

    def _digest(self) -> str | None:
        limit = settings.context_max_turns
        if len(self._history) <= limit:
            return None
        older = self._history[:-limit]
        customer_lines = [message.content for message in older if message.role == "user"][-4:]
        if not customer_lines:
            return None
        return "The customer already said: " + " | ".join(customer_lines)

    def _record(self, turn: Turn) -> None:
        self.result.turns.append(turn)
        if self.on_turn:
            asyncio.create_task(self.on_turn(turn))
