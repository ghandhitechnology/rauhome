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
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from rau.events import BUS
from rau.face import brain, choreography
from rau.voice import reactions
from rau.voice.stt import get_stt_provider, resolve_stt
from rau.voice.tts_stream import SR, SentenceTiming, pcm_duration_ms, speak_stream
from rau import state

#: How long a new turn waits for the previous one to wind down. Long enough for
#: a cancelled worker to fall out of its stream, short enough that the user does
#: not notice the handover.
TURN_HANDOVER_SEC = 0.15
STT_FINALIZE_SEC = 20.0
CLOSE_JOIN_SEC = 0.25
MAX_MIC_FRAME_BYTES = 64 * 1024
MAX_UTTERANCE_BYTES = 16000 * 2 * 90
MAX_MIC_QUEUE_FRAMES = 256
MAX_TRANSCRIPT_CHARS = 16_000
MAX_TEXT_TURN_CHARS = 16_000
#: Don't ship more PCM than the browser can hear soon — keeps captions and
#: barge offsets honest when TTS outruns the speaker.
MAX_PLAYBACK_AHEAD_SEC = 0.8
#: Soft beat before first TTS audio — imperfect timing without filler words.
PRE_SPEECH_LAG_SEC = 0.2
#: How long a turn may be silent before a hesitation is played over the gap.
#:
#: Under this, the reply is already fast enough that a filler would be the
#: slowest part of it. Over it, the silence has started to read as lag. Tuned
#: to sit just past the point where a person would have drawn breath.
REACTION_AFTER_SEC = 0.45
#: Bound LLM→TTS so a stalled consumer backpressures the model producer.
TOKEN_PIPE_MAXSIZE = 32


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
        duration_ms = pcm_duration_ms(pcm)
        chunk = SpokenChunk(text=text, start_ms=self.total_ms, duration_ms=duration_ms)
        if text and self.chunks and self.chunks[-1].text == text:
            # Low-latency TTS can deliver many PCM fragments for one sentence.
            # They form one audible sentence, not many repeated timeline items.
            previous = self.chunks[-1]
            previous.duration_ms += chunk.duration_ms
            chunk = previous
        else:
            self.chunks.append(chunk)
        self.total_ms += duration_ms
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
                # A hesitation holds time in the timeline but is not speech: he
                # did not say "hmm", and the model must not remember saying it.
                if c.text:
                    kept.append(c.text)
            else:
                break
        return " ".join(kept).strip()


@dataclass
class _MicStream:
    queue: asyncio.Queue
    bytes_seen: int = 0
    closed: bool = False


@dataclass
class _Turn:
    ident: int
    text: str
    #: Server-generated id every body plan and chat event for this turn carries.
    turn_id: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    utterance: Utterance = field(default_factory=Utterance)
    played_ms: float = 0.0
    pending_sentence: str = ""
    announced_sentence: str = ""
    #: Where the sentence currently being synthesised starts in the timeline.
    sentence_start_ms: float = 0.0
    first_audio_at: float = 0.0
    #: Set once a hesitation has been played for this turn, so the real reply
    #: never arrives behind a second one.
    reacted: bool = False
    thread: Optional[threading.Thread] = None
    producer: Optional[threading.Thread] = None
    reply: Any = None
    interrupted_sent: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def set_played_ms(self, played_ms: float) -> None:
        with self.lock:
            self.played_ms = played_ms

    def heard_text(self) -> str:
        with self.lock:
            return self.utterance.heard_text(self.played_ms)

    def remaining_playback_sec(self) -> float:
        with self.lock:
            if not self.first_audio_at:
                return 0.0
            elapsed = time.monotonic() - self.first_audio_at
            return max(0.0, self.utterance.total_ms / 1000.0 - elapsed)

    def estimated_played_ms(self) -> float:
        with self.lock:
            if not self.first_audio_at:
                return 0.0
            elapsed_ms = (time.monotonic() - self.first_audio_at) * 1000.0
            return min(self.utterance.total_ms, max(0.0, elapsed_ms))

    def claim_reaction(self) -> bool:
        """True for exactly one caller, and only while nothing has been said."""
        with self.lock:
            if self.reacted or self.first_audio_at:
                return False
            self.reacted = True
            return True

    def mark_interrupted_sent(self) -> bool:
        with self.lock:
            if self.interrupted_sent:
                return False
            self.interrupted_sent = True
            return True


class VoiceSession:
    """Owns one browser voice connection."""

    def __init__(self, send_json, send_bytes) -> None:
        self._send_json = send_json
        self._send_bytes = send_bytes
        self.loop = asyncio.get_running_loop()
        self._send_lock = asyncio.Lock()

        #: Mic PCM for the utterance currently being spoken by the user.
        self._mic: Optional[_MicStream] = None
        self._stt_task: Optional[asyncio.Task] = None
        self._stt_watchdog: Optional[asyncio.Task] = None
        self._stt_epoch = 0
        self._stt_commit_lock = asyncio.Lock()

        self._turn_seq = 0
        self._turn_lock = asyncio.Lock()
        self._active_turn: Optional[_Turn] = None
        self.phase = "idle"  # idle | listening | thinking | speaking
        self.closed = False

    # ── plumbing ─────────────────────────────────────────────────────

    async def send(self, **payload: Any) -> None:
        if self.closed:
            return
        try:
            async with self._send_lock:
                if not self.closed:
                    await self._send_json(payload)
        except Exception:
            self.closed = True

    def _schedule(self, coroutine) -> None:
        if self.closed or self.loop.is_closed():
            coroutine.close()
            return
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        except RuntimeError:
            coroutine.close()
            return

        # Retrieve failures so a disconnected client does not produce an
        # unobserved Future exception on every remaining token.
        def consume_result(done) -> None:
            try:
                done.result()
            except Exception:
                pass

        future.add_done_callback(consume_result)

    def _is_current(self, turn: _Turn) -> bool:
        return not self.closed and self._active_turn is turn

    def send_threadsafe(self, *, turn: Optional[_Turn] = None, **payload: Any) -> None:
        """Emit from the worker thread."""
        async def go() -> None:
            if turn is not None and (
                not self._is_current(turn) or turn.cancel.is_set()
            ):
                return
            await self.send(**payload)

        self._schedule(go())

    def send_audio_threadsafe(self, pcm: bytes, *, turn: _Turn) -> None:
        async def go() -> None:
            if not self._is_current(turn) or turn.cancel.is_set():
                return
            try:
                async with self._send_lock:
                    # Re-check after backpressure from an earlier frame. This
                    # is what prevents already-queued audio leaking after barge.
                    if self._is_current(turn) and not turn.cancel.is_set():
                        await self._send_bytes(pcm)
            except Exception:
                self.closed = True

        self._schedule(go())

    async def set_phase(self, phase: str, *, turn: Optional[_Turn] = None) -> None:
        if turn is not None and (
            not self._is_current(turn) or turn.cancel.is_set()
        ):
            return
        if phase != self.phase:
            self.phase = phase
            await self.send(t="phase", phase=phase)

    def set_phase_threadsafe(self, phase: str, *, turn: _Turn) -> None:
        self._schedule(self.set_phase(phase, turn=turn))

    # ── microphone / STT ─────────────────────────────────────────────

    async def speech_start(self) -> None:
        """
        User began talking. Open an STT stream now so connection setup
        overlaps with them speaking rather than adding latency afterwards.
        """
        turn = self._active_turn
        if (
            turn is not None
            and self.phase in ("thinking", "speaking")
            and not turn.cancel.is_set()
        ):
            # A barge message normally arrives first and carries the exact
            # playback offset. This fallback also makes speech_start alone a
            # real interruption instead of letting TTS talk over the new user.
            await self._cancel_turn(turn, turn.estimated_played_ms())

        await self.stop_stt()
        mic = _MicStream(asyncio.Queue(maxsize=MAX_MIC_QUEUE_FRAMES))
        self._mic = mic
        epoch = self._stt_epoch
        self._stt_task = asyncio.create_task(
            self._run_stt(mic, epoch), name="rau-voice-stt"
        )
        await self.set_phase("listening")

    def feed(self, pcm: bytes) -> Optional[str]:
        """Queue one PCM16 frame; return a client-safe validation error."""
        mic = self._mic
        if mic is None or mic.closed:
            return None
        if not isinstance(pcm, bytes):
            return "audio frame must be bytes"
        if not pcm:
            return None
        if len(pcm) % 2:
            return "audio frame must contain complete PCM16 samples"
        if len(pcm) > MAX_MIC_FRAME_BYTES:
            return "audio frame is too large"
        if mic.bytes_seen + len(pcm) > MAX_UTTERANCE_BYTES:
            mic.closed = True
            return "utterance is too long"
        try:
            mic.queue.put_nowait(pcm)
        except asyncio.QueueFull:
            mic.closed = True
            return "audio input could not be consumed in real time"
        mic.bytes_seen += len(pcm)
        return None

    async def speech_end(self) -> None:
        """User stopped. Close the mic stream so the backend can finalise."""
        mic, self._mic = self._mic, None
        if mic is None or mic.closed:
            return
        mic.closed = True
        try:
            await asyncio.wait_for(mic.queue.put(None), timeout=0.5)
        except asyncio.TimeoutError:
            await self.send(t="error", detail="stt: audio queue stalled")
            await self.stop_stt()
            await self.set_phase("idle")
            return

        task = self._stt_task
        if task is not None:
            self._cancel_stt_watchdog()
            self._stt_watchdog = asyncio.create_task(
                self._watch_stt_finalization(task),
                name="rau-voice-stt-finalize",
            )

    def _cancel_stt_watchdog(self) -> None:
        watchdog, self._stt_watchdog = self._stt_watchdog, None
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()

    async def _watch_stt_finalization(self, task: asyncio.Task) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=STT_FINALIZE_SEC)
        except asyncio.TimeoutError:
            if task is self._stt_task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                self._stt_task = None
                await self.send(t="error", detail="stt: transcription timed out")
                await self.set_phase("idle")
        except asyncio.CancelledError:
            raise
        finally:
            if self._stt_watchdog is asyncio.current_task():
                self._stt_watchdog = None

    async def stop_stt(self) -> None:
        # Serialize invalidation with the provider's final handoff. If the tail
        # wins, stop() immediately cancels the newly-started turn; if stop wins,
        # the tail observes the new epoch and cannot start one.
        async with self._stt_commit_lock:
            self._stt_epoch += 1
            self._cancel_stt_watchdog()
            task, self._stt_task = self._stt_task, None
            self._mic = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_stt(self, mic: _MicStream, epoch: int) -> None:
        async def frames() -> AsyncIterator[bytes]:
            while True:
                frame = await mic.queue.get()
                if frame is None:
                    return
                yield frame

        provider = None
        final_parts: List[str] = []
        latest_partial = ""
        failed = False
        try:
            provider = get_stt_provider()
            async for tr in provider.stream(frames()):
                text = str(getattr(tr, "text", "") or "").strip()
                if not text:
                    continue
                text = text[:MAX_TRANSCRIPT_CHARS]
                if tr.final:
                    latest_partial = ""
                    committed = " ".join(final_parts).strip()
                    if text == committed or (final_parts and text == final_parts[-1]):
                        continue
                    if committed and text.startswith(committed):
                        final_parts = [text]
                    else:
                        final_parts.append(text)
                    await self.send(
                        t="partial", text=" ".join(final_parts)[:MAX_TRANSCRIPT_CHARS]
                    )
                else:
                    latest_partial = text
                    prefix = " ".join(final_parts).strip()
                    partial = f"{prefix} {text}".strip()[:MAX_TRANSCRIPT_CHARS]
                    await self.send(t="partial", text=partial)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failed = True
            await self.send(t="error", detail=f"stt: {str(e)[:500]}")
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass
            current = asyncio.current_task()
            if self._stt_task is current:
                self._stt_task = None
                self._cancel_stt_watchdog()

        text = " ".join(final_parts).strip()
        if latest_partial and not text.endswith(latest_partial):
            text = f"{text} {latest_partial}".strip()
        text = text[:MAX_TRANSCRIPT_CHARS]
        if text and not failed and not self.closed:
            async with self._stt_commit_lock:
                if epoch == self._stt_epoch and not self.closed:
                    await self.send(t="final", text=text)
                    if epoch == self._stt_epoch:
                        await self.begin_turn(text)
        elif not self.closed and self.phase == "listening":
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
        text = str(text or "").strip()[:MAX_TEXT_TURN_CHARS]
        if not text or self.closed:
            return

        async with self._turn_lock:
            if self.closed:
                return
            previous = self._active_turn
            if previous is not None:
                if not previous.cancel.is_set() and self.phase in ("thinking", "speaking"):
                    await self._cancel_turn(previous, previous.estimated_played_ms())
                if previous.thread is not None and previous.thread.is_alive():
                    # A cooperative provider normally exits immediately. Do not
                    # hold the follow-up behind blocked third-party HTTP I/O.
                    await asyncio.to_thread(previous.thread.join, TURN_HANDOVER_SEC)

            if previous is not None and previous.turn_id:
                # Whatever the superseded turn had planned is now about a reply
                # nobody will hear the rest of.
                choreography.cancel_turn(previous.turn_id, "superseded")

            self._turn_seq += 1
            turn = _Turn(self._turn_seq, text, turn_id=choreography.new_turn_id())
            # Construct the worker before publishing the turn, so another
            # caller can always cancel/join the active object it observes.
            turn.thread = threading.Thread(
                target=self._turn_body,
                args=(turn,),
                daemon=True,
                name=f"rau-voice-turn-{turn.ident}",
            )
            self._active_turn = turn
            state.add_log("user", text)
            await self.set_phase("thinking", turn=turn)
            turn.thread.start()

    def _turn_body(self, turn: _Turn) -> None:
        from rau.heartbeat.presence import note_user_reply

        note_user_reply()
        family = reactions.classify(turn.text)
        tokens = _TokenPipe()

        def produce() -> None:
            def on_token(token: str) -> None:
                tokens.put(token, cancel=turn.cancel)

            try:
                turn.reply = brain.chat_streaming(
                    turn.text,
                    on_token=on_token,
                    on_tool=lambda n, a, r: self.send_threadsafe(
                        turn=turn,
                        t="tool",
                        name=n,
                        args=a,
                        ok=bool(r.get("ok", True)),
                    ),
                    cancel=turn.cancel,
                    defer_diary=True,
                    turn_id=turn.turn_id,
                )
            except brain.Cancelled as cancelled:
                brain.finish_interrupted_turn(cancelled, turn.heard_text())
            except Exception as e:
                self.send_threadsafe(
                    turn=turn, t="error", detail=f"model: {str(e)[:500]}"
                )
            finally:
                # Covers the narrow race where cancellation lands after
                # chat_streaming committed a deferred reply but before its
                # return value was observed by the turn thread.
                if turn.cancel.is_set() and isinstance(turn.reply, brain.StreamingReply):
                    brain.finish_interrupted_turn(turn.reply, turn.heard_text())
                tokens.close()

        turn.producer = threading.Thread(
            target=produce,
            daemon=True,
            name=f"rau-voice-llm-{turn.ident}",
        )
        turn.producer.start()

        def on_sentence(sentence: str) -> None:
            turn.pending_sentence = sentence

        def on_audio(pcm: bytes) -> None:
            if turn.cancel.is_set() or not self._is_current(turn):
                return
            # Pace synth/send to real playback so the worklet queue (and the
            # token pipe feeding TTS) cannot run unbounded ahead of the ear.
            while turn.remaining_playback_sec() > MAX_PLAYBACK_AHEAD_SEC:
                if turn.cancel.is_set() or not self._is_current(turn):
                    return
                turn.cancel.wait(0.05)
            sentence = turn.pending_sentence
            if turn.announced_sentence != sentence:
                turn.announced_sentence = sentence
                self.set_phase_threadsafe("speaking", turn=turn)
                self.send_threadsafe(
                    turn=turn, t="say", text=sentence, turn_id=turn.turn_id
                )
            with turn.lock:
                # Claimed here as well as in `react`, so a fast reply closes
                # the window instead of arriving behind a hesitation for a gap
                # that turned out not to exist.
                turn.reacted = True
                if not turn.first_audio_at:
                    turn.first_audio_at = time.monotonic()
                chunk = turn.utterance.add(sentence, pcm)
                # Chunks of one sentence merge into a single timeline item, so
                # this stays the sentence's own start however many PCM
                # fragments the provider streamed for it.
                turn.sentence_start_ms = chunk.start_ms
            self.send_audio_threadsafe(pcm, turn=turn)

        def on_timing(timing: SentenceTiming) -> None:
            """Hand the browser where each character lands in the timeline."""
            if turn.cancel.is_set() or not self._is_current(turn):
                return
            with turn.lock:
                offset_ms = turn.sentence_start_ms
            self.send_threadsafe(
                turn=turn,
                t="say_align",
                turn_id=turn.turn_id,
                text=timing.text,
                offset_ms=round(offset_ms, 1),
                duration_ms=round(timing.duration_ms, 1),
                char_ms=[round(t, 1) for t in timing.char_ms],
            )

        audio_sent = False

        def tracked_audio(pcm: bytes) -> None:
            nonlocal audio_sent
            if pcm and not turn.cancel.is_set():
                audio_sent = True
            on_audio(pcm)

        def react() -> None:
            """
            Cover the gap before the first real word, if there is one.

            Runs on its own thread because the turn thread is about to block
            inside `speak_stream` for as long as the first sentence takes to
            synthesise — which is precisely the interval being covered.
            """
            try:
                _react()
            except Exception:
                # A hesitation is decoration in front of the thing the user
                # actually asked for. Anything that goes wrong here costs the
                # decoration and must not be visible anywhere else.
                pass

        def _react() -> None:
            # Never shorter than the pre-speech lag plus a beat. The turn
            # thread does not even enter `speak_stream` until that lag is up,
            # so a shorter wait would fire the hesitation before the pipeline
            # it exists to cover had a chance to produce anything — which is
            # every turn, which is the loading noise this is trying not to be.
            if turn.cancel.wait(max(REACTION_AFTER_SEC, PRE_SPEECH_LAG_SEC + 0.15)):
                return
            if not self._is_current(turn) or not turn.claim_reaction():
                return
            text = reactions.POOL.choose(family)
            pcm = reactions.POOL.audio(text)
            # Between choosing and synthesising, the real reply may have caught
            # up. Speaking now would put a hesitation after the first sentence.
            if not pcm or turn.cancel.is_set() or not self._is_current(turn):
                return
            with turn.lock:
                if turn.first_audio_at:
                    return
                turn.first_audio_at = time.monotonic()
                # Empty text: it holds its place in the timeline so every
                # sentence after it is aligned correctly, but it is not speech.
                turn.utterance.add("", pcm)
            self.set_phase_threadsafe("speaking", turn=turn)
            self.send_audio_threadsafe(pcm, turn=turn)

        reactor = threading.Thread(
            target=react, daemon=True, name=f"rau-voice-react-{turn.ident}"
        )
        reactor.start()

        tts_failed = False
        try:
            # Brief pre-speech lag (imperfect timing). Cancel during wait skips TTS.
            cancelled_during_lag = turn.cancel.wait(PRE_SPEECH_LAG_SEC)
            if not cancelled_during_lag:
                for _ in speak_stream(
                    tokens.iter(),
                    on_audio=tracked_audio,
                    on_sentence=on_sentence,
                    on_timing=on_timing,
                    cancel=turn.cancel,
                ):
                    pass
            else:
                for _ in tokens.iter():
                    if turn.cancel.is_set():
                        break
        except Exception as e:
            tts_failed = True
            self.send_threadsafe(
                turn=turn, t="error", detail=f"tts unavailable: {str(e)[:500]}"
            )
            # TTS can fail while the model is still generating. Keep consuming
            # the pipe so the full text reply remains available as fallback.
            for _ in tokens.iter():
                if turn.cancel.is_set():
                    break

        turn.producer.join(timeout=TURN_HANDOVER_SEC)

        if audio_sent and not turn.cancel.is_set():
            # WebSocket delivery is much faster than real playback. Keep the
            # phase interruptible until the browser should have drained the
            # PCM timeline instead of declaring idle while it is still talking.
            turn.cancel.wait(turn.remaining_playback_sec() + 0.1)

        full = "".join(tokens.seen).strip()
        if turn.cancel.is_set():
            if isinstance(turn.reply, brain.StreamingReply):
                brain.finish_interrupted_turn(turn.reply, turn.heard_text())
            self._notify_interrupted_threadsafe(turn)
        else:
            if isinstance(turn.reply, brain.StreamingReply):
                brain.commit_streamed_turn(turn.reply)
            if full:
                state.add_log("rau", full)
                if not audio_sent:
                    # Nothing was audible; hand the text over so the UI can
                    # still show what he said.
                    self.send_threadsafe(
                        turn=turn,
                        t="say",
                        text=full,
                        silent=True,
                        turn_id=turn.turn_id,
                    )
            elif tts_failed:
                self.send_threadsafe(
                    turn=turn,
                    t="error",
                    detail="model returned no text after TTS failed",
                )
            self.send_threadsafe(
                turn=turn, t="say_end", interrupted=False, turn_id=turn.turn_id
            )
            self.set_phase_threadsafe("idle", turn=turn)

    # ── barge-in ─────────────────────────────────────────────────────

    async def barge(self, played_ms: float) -> None:
        """User talked over Rau. Stop everything immediately."""
        turn = self._active_turn
        if turn is None or self.phase != "speaking":
            return
        await self._cancel_turn(turn, played_ms)

    async def _cancel_turn(self, turn: _Turn, played_ms: float) -> None:
        if turn.cancel.is_set():
            return
        played = float(played_ms or 0.0)
        if not math.isfinite(played):
            played = 0.0
        played = min(max(0.0, played), 3_600_000.0)
        turn.set_played_ms(played)
        turn.cancel.set()
        # Unfired cues belong to a sentence that will now never be spoken. Do
        # this before the browser is told anything else, so no avatar acts out
        # a gesture for text the user cut off.
        choreography.cancel_turn(turn.turn_id, "interrupted")
        await self.send(t="cancelled", turn_id=turn.turn_id)
        await self._notify_interrupted(turn)
        BUS.emit("voice_interrupted", played_ms=played)

    async def _notify_interrupted(self, turn: _Turn) -> None:
        if not turn.mark_interrupted_sent():
            return
        heard = turn.heard_text()
        if heard:
            state.add_log("rau", heard)
        await self.send(
            t="say_end", interrupted=True, heard=heard, turn_id=turn.turn_id
        )

    def _notify_interrupted_threadsafe(self, turn: _Turn) -> None:
        self._schedule(self._notify_interrupted(turn))

    async def stop(self) -> None:
        """Cancel listening or generation, regardless of the current phase."""
        await self.stop_stt()
        turn = self._active_turn
        if (
            turn is not None
            and self.phase in ("thinking", "speaking")
            and not turn.cancel.is_set()
        ):
            await self._cancel_turn(turn, turn.estimated_played_ms())
        await self.set_phase("idle")

    async def close(self) -> None:
        turn = self._active_turn
        if turn is not None:
            turn.cancel.set()
            choreography.cancel_turn(turn.turn_id, "closed")
        await self.stop_stt()
        self.closed = True
        if turn is not None:
            workers = [turn.thread, turn.producer]
            for worker in workers:
                if worker is not None and worker.is_alive():
                    await asyncio.to_thread(worker.join, CLOSE_JOIN_SEC)


_WARMED = threading.Event()


def warm_reactions() -> None:
    """
    Synthesise the hesitations once, in the background, on first connect.

    Otherwise the very first turn of a session — the one where the user is
    least sure anything is working, and latency is most visible — is the one
    turn with nothing to cover it, because its clip is still being fetched.
    After the first run these are all disk reads.

    Called by the socket handler rather than by `VoiceSession.__init__`, so
    that constructing a session is free of side effects. Warming is a
    connection-lifecycle concern, and a constructor that quietly makes ten
    billed API calls is a trap for every test that builds one.
    """
    if _WARMED.is_set():
        return
    _WARMED.set()

    def go() -> None:
        try:
            reactions.POOL.warm()
        except Exception:
            # A pool that cannot warm simply means turns sound like they
            # answered quickly. It must never affect the connection.
            pass

    threading.Thread(target=go, daemon=True, name="rau-voice-warm").start()


class _TokenPipe:
    """Blocking queue between the LLM thread and the TTS consumer."""

    def __init__(self, maxsize: int = TOKEN_PIPE_MAXSIZE) -> None:
        import queue

        self._q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=max(1, maxsize))
        self.seen: List[str] = []

    def put(self, token: str, cancel: Optional[threading.Event] = None) -> bool:
        """Enqueue a token; block while full unless `cancel` is set."""
        import queue

        self.seen.append(token)
        while True:
            try:
                self._q.put(token, timeout=0.05)
                return True
            except queue.Full:
                if cancel is not None and cancel.is_set():
                    return False

    def close(self) -> None:
        import queue

        # Always deliver the sentinel, even if the pipe is full of backlog
        # after a barge — otherwise the TTS consumer never exits.
        while True:
            try:
                self._q.put(None, timeout=0.05)
                return
            except queue.Full:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    pass

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
