"""
One live voice conversation.

Threading: the WebSocket and STT run on the event loop; the turn itself
(`brain.chat_streaming` + `speak_stream`) is blocking, so it runs on a worker
thread and pushes audio back through a thread-safe hop onto the loop.

    ws recv ──▶ audio queue ──▶ STT ──▶ final text
                                          │
                                    worker thread
                                          │
                        chat_streaming ──▶ tokens ──▶ speak_stream
                                          │                 │
                                          └──▶ out queue ◀──┘
                                                    │
                                              ws send ──▶ browser
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from rau.events import BUS
from rau.face import brain
from rau.voice.stt import get_stt_provider, resolve_stt
from rau.voice.tts_stream import SR, pcm_duration_ms, speak_stream
from rau import state

#: How long a new turn waits for the previous one to wind down. Long enough for
#: a cancelled worker to fall out of its stream, short enough that the user does
#: not notice the handover.
TURN_HANDOVER_SEC = 1.5


@dataclass
class SpokenChunk:
    """A sentence handed to the browser, with when it lands in the timeline."""

    text: str
    start_ms: float
    duration_ms: float


@dataclass
class Utterance:
    """Bookkeeping for one Rau reply, used to truncate honestly on barge-in."""

    chunks: List[SpokenChunk] = field(default_factory=list)
    total_ms: float = 0.0

    def add(self, text: str, pcm: bytes) -> SpokenChunk:
        chunk = SpokenChunk(text=text, start_ms=self.total_ms, duration_ms=pcm_duration_ms(pcm))
        self.chunks.append(chunk)
        self.total_ms += chunk.duration_ms
        return chunk

    def heard_text(self, played_ms: float) -> str:
        """
        What the user actually heard, to the nearest sentence.

        A sentence counts as heard once playback got past its midpoint —
        cutting on exact sample offsets would leave half-words in history.
        """
        kept: List[str] = []
        for c in self.chunks:
            if played_ms >= c.start_ms + c.duration_ms * 0.5:
                kept.append(c.text)
            else:
                break
        return " ".join(kept).strip()


class VoiceSession:
    """Owns one browser voice connection."""

    def __init__(self, send_json, send_bytes) -> None:
        self._send_json = send_json
        self._send_bytes = send_bytes
        self.loop = asyncio.get_event_loop()

        #: Mic PCM for the utterance currently being spoken by the user.
        self._mic: Optional[asyncio.Queue] = None
        self._stt_task: Optional[asyncio.Task] = None

        self._turn: Optional[threading.Thread] = None
        self.cancel = threading.Event()

        self.utterance = Utterance()
        self.phase = "idle"  # idle | listening | thinking | speaking
        self.closed = False

        #: Sentence currently being synthesised, so its audio can be attributed.
        self._pending_sentence: Optional[str] = None
        #: How much of the reply the browser actually played before barging in.
        self._played_ms: float = 0.0

    # ── plumbing ─────────────────────────────────────────────────────

    async def send(self, **payload: Any) -> None:
        if self.closed:
            return
        try:
            await self._send_json(payload)
        except Exception:
            self.closed = True

    def send_threadsafe(self, **payload: Any) -> None:
        """Emit from the worker thread."""
        if self.closed:
            return
        asyncio.run_coroutine_threadsafe(self.send(**payload), self.loop)

    def send_audio_threadsafe(self, pcm: bytes) -> None:
        if self.closed or not pcm:
            return

        async def _go() -> None:
            if self.closed:
                return
            try:
                await self._send_bytes(pcm)
            except Exception:
                self.closed = True

        asyncio.run_coroutine_threadsafe(_go(), self.loop)

    async def set_phase(self, phase: str) -> None:
        if phase != self.phase:
            self.phase = phase
            await self.send(t="phase", phase=phase)

    # ── microphone / STT ─────────────────────────────────────────────

    async def speech_start(self) -> None:
        """
        User began talking. Open an STT stream now so connection setup
        overlaps with them speaking rather than adding latency afterwards.
        """
        await self.stop_stt()
        self._mic = asyncio.Queue()
        self._stt_task = asyncio.create_task(self._run_stt(self._mic))
        await self.set_phase("listening")

    def feed(self, pcm: bytes) -> None:
        if self._mic is not None:
            self._mic.put_nowait(pcm)

    async def speech_end(self) -> None:
        """User stopped. Close the mic stream so the backend can finalise."""
        if self._mic is not None:
            self._mic.put_nowait(None)

    async def stop_stt(self) -> None:
        task, self._stt_task = self._stt_task, None
        self._mic = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_stt(self, mic: asyncio.Queue) -> None:
        async def frames() -> AsyncIterator[bytes]:
            while True:
                frame = await mic.get()
                if frame is None:
                    return
                yield frame

        provider = get_stt_provider()
        final_text = ""
        try:
            async for tr in provider.stream(frames()):
                if tr.final:
                    final_text = tr.text
                    await self.send(t="final", text=tr.text)
                else:
                    await self.send(t="partial", text=tr.text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.send(t="error", detail=f"stt: {e}")
        finally:
            try:
                await provider.close()
            except Exception:
                pass

        text = final_text.strip()
        if text:
            await self.begin_turn(text)
        else:
            await self.set_phase("idle")

    # ── the turn ─────────────────────────────────────────────────────

    async def begin_turn(self, text: str) -> None:
        """
        Run one reply on a worker thread.

        The previous turn is preempted rather than refused. Right after a
        barge-in the old worker is usually still winding down inside its
        `producer.join`, and that is exactly when the user's follow-up arrives —
        dropping it there would silently swallow the sentence they interrupted
        him to say, which is the whole point of interrupting.
        """
        previous = self._turn
        if previous is not None and previous.is_alive():
            self.cancel.set()
            # Give it a moment to notice; it only ever checks between tokens.
            await asyncio.get_running_loop().run_in_executor(
                None, previous.join, TURN_HANDOVER_SEC
            )

        self.cancel = threading.Event()
        self.utterance = Utterance()
        self._played_ms = 0.0
        state.add_log("user", text)
        await self.set_phase("thinking")

        self._turn = threading.Thread(
            target=self._turn_body, args=(text,), daemon=True, name="rau-voice-turn"
        )
        self._turn.start()

    def _turn_body(self, text: str) -> None:
        from rau.heartbeat.presence import note_user_reply

        note_user_reply()
        tokens = _TokenPipe()

        def produce() -> None:
            try:
                brain.chat_streaming(
                    text,
                    on_token=tokens.put,
                    on_tool=lambda n, a, r: self.send_threadsafe(
                        t="tool", name=n, args=a, ok=bool(r.get("ok", True))
                    ),
                    cancel=self.cancel,
                )
            except brain.Cancelled:
                pass
            except Exception as e:
                self.send_threadsafe(t="error", detail=str(e))
            finally:
                tokens.close()

        producer = threading.Thread(target=produce, daemon=True, name="rau-voice-llm")
        producer.start()

        def on_sentence(sentence: str) -> None:
            # Only claim to be speaking once there is really a sentence going
            # out — otherwise the UI flips to "speaking" during model latency.
            if self.phase != "speaking":
                self.phase = "speaking"
                self.send_threadsafe(t="phase", phase="speaking")
            self.send_threadsafe(t="say", text=sentence)

        def on_audio(pcm: bytes) -> None:
            # Record before sending so a barge-in that lands mid-flight still
            # sees this sentence in the timeline.
            sentence = self._pending_sentence or ""
            self.utterance.add(sentence, pcm)
            self.send_audio_threadsafe(pcm)

        spoke = False
        try:
            for _ in speak_stream(
                tokens.iter(),
                on_audio=on_audio,
                on_sentence=self._track_sentence(on_sentence),
                cancel=self.cancel,
            ):
                pass
            spoke = True
        except Exception as e:
            # No ElevenLabs key, or TTS fell over. The reply still exists, so
            # degrade to text rather than swallowing the whole turn.
            self.send_threadsafe(t="error", detail=f"tts unavailable: {e}")

        producer.join(timeout=1.0)

        full = "".join(tokens.seen).strip()
        if self.cancel.is_set():
            self._finish_interrupted(full)
        else:
            if full:
                state.add_log("rau", full)
                if not spoke:
                    # Nothing was audible; hand the text over so the UI can
                    # still show what he said.
                    self.send_threadsafe(t="say", text=full, silent=True)
            self.send_threadsafe(t="say_end", interrupted=False)

        # After a barge the user is already talking and `speech_start` has moved
        # us to "listening". Announcing "idle" here would land after it and tell
        # the client nothing is happening while it streams their voice.
        if self.phase == "speaking":
            self.phase = "idle"
            self.send_threadsafe(t="phase", phase="idle")

    def _track_sentence(self, inner):
        def wrapper(sentence: str) -> None:
            self._pending_sentence = sentence
            inner(sentence)

        return wrapper

    def _finish_interrupted(self, full: str) -> None:
        """Trim history to what was actually heard and tell the model why."""
        heard = self.utterance.heard_text(self._played_ms)
        if heard:
            brain.truncate_last_assistant(heard)
            state.add_log("rau", heard)
        brain._append_history(
            brain.Message(
                role="system",
                content=(
                    "(You were interrupted here — the user began speaking before you "
                    "finished. Do not repeat what you already said. Acknowledge them "
                    "naturally and respond to what they actually asked.)"
                ),
            )
        )
        self.send_threadsafe(t="say_end", interrupted=True, heard=heard)

    # ── barge-in ─────────────────────────────────────────────────────

    async def barge(self, played_ms: float) -> None:
        """User talked over Rau. Stop everything immediately."""
        if self.phase != "speaking":
            return
        self._played_ms = max(0.0, float(played_ms or 0.0))
        self.cancel.set()
        await self.send(t="cancelled")
        BUS.emit("voice_interrupted", played_ms=self._played_ms)

    async def close(self) -> None:
        self.closed = True
        self.cancel.set()
        await self.stop_stt()


class _TokenPipe:
    """Blocking queue between the LLM thread and the TTS consumer."""

    def __init__(self) -> None:
        import queue

        self._q: "queue.Queue[Optional[str]]" = queue.Queue()
        self.seen: List[str] = []

    def put(self, token: str) -> None:
        self.seen.append(token)
        self._q.put(token)

    def close(self) -> None:
        self._q.put(None)

    def iter(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            yield item


def session_info() -> Dict[str, Any]:
    provider, slot = resolve_stt()
    return {
        "stt": provider,
        "model": slot.get("model") or "",
        "sample_rate_in": 16000,
        "sample_rate_out": SR,
        "started": time.time(),
    }
