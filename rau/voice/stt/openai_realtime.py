"""
OpenAI Realtime transcription (gpt-live-transcribe).

Streams PCM over the Realtime WebSocket transcription session and yields
interim deltas as the speaker talks — the OpenAI counterpart to Deepgram's
live partials. The browser mic is 16 kHz; Realtime only accepts 24 kHz PCM,
so frames are upsampled on the wire.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
from array import array
from typing import AsyncIterator, Optional

from rau.env import get_secret
from rau.voice.stt.base import SttProvider, Transcript

WS_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
REALTIME_RATE = 24000

#: Same connect-buffer rationale as Deepgram — absorb a slow handshake.
_CONNECT_BUFFER_FRAMES = 512

#: Models that must use this Realtime path (not POST /audio/transcriptions).
LIVE_MODELS = frozenset({"gpt-live-transcribe"})

#: New transcription models take `languages` instead of singular `language`.
USES_LANGUAGES = frozenset({"gpt-live-transcribe", "gpt-transcribe"})


def upsample_pcm16_16k_to_24k(pcm: bytes, carry: bytes = b"") -> tuple[bytes, bytes]:
    """
    Linear upsample PCM16 mono from 16 kHz to 24 kHz (3/2 ratio).

    Returns (upsampled_bytes, leftover_input_bytes). Leftover is at most one
    sample so a later frame can finish the pair — streaming frames are not
    guaranteed to land on even sample counts.
    """
    raw = carry + pcm
    if len(raw) < 2:
        return b"", raw
    if len(raw) % 2:
        raw = raw[:-1]
    if not raw:
        return b"", b""

    samples = array("h")
    samples.frombytes(raw)
    n = len(samples)
    # Keep the last input sample when n is odd so the next chunk can
    # interpolate from it.
    use = n if n % 2 == 0 else n - 1
    if use <= 0:
        return b"", raw

    out = array("h")
    # 2 input samples → 3 output: s0, (s0+s1)/2, s1
    for i in range(0, use, 2):
        s0 = samples[i]
        s1 = samples[i + 1]
        out.append(s0)
        out.append(int((s0 + s1) / 2))
        out.append(s1)

    leftover = raw[use * 2 :]
    return out.tobytes(), leftover


class OpenAiRealtimeStt(SttProvider):
    name = "openai"
    supports_partials = True

    def __init__(self, model: str = "gpt-live-transcribe", language: str = ""):
        self.model = model or "gpt-live-transcribe"
        self.language = (language or "").strip().lower()
        self._ws = None

    def _session_update(self) -> dict:
        transcription: dict = {
            "model": self.model,
            # Prefer earlier partials for conversation; accuracy can be tuned later.
            "delay": "low",
        }
        if self.language and self.language not in ("", "multi", "auto"):
            if self.model in USES_LANGUAGES:
                transcription["languages"] = [self.language]
            else:
                transcription["language"] = self.language
        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": REALTIME_RATE},
                        "transcription": transcription,
                        # Client VAD decides when the utterance ends; we commit
                        # when the mic stream closes.
                        "turn_detection": None,
                    }
                },
            },
        }

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[Transcript]:
        import websockets

        key = get_secret("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")

        connect_params = inspect.signature(websockets.connect).parameters
        header_arg = (
            "additional_headers"
            if "additional_headers" in connect_params
            else "extra_headers"
        )
        connect_options = {
            header_arg: {"Authorization": f"Bearer {key}"},
            "open_timeout": 10,
            "close_timeout": 5,
            "ping_interval": 20,
            "ping_timeout": 20,
            "max_size": 1_000_000,
            "max_queue": 32,
        }

        frames: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue(
            maxsize=_CONNECT_BUFFER_FRAMES
        )

        async def feed() -> None:
            try:
                async for frame in audio:
                    await frames.put(frame)
            finally:
                await frames.put(None)

        feeder = asyncio.create_task(feed())
        try:
            async with websockets.connect(WS_URL, **connect_options) as ws:
                self._ws = ws
                await ws.send(json.dumps(self._session_update()))

                # Wait until the session accepts our config before appending
                # audio — early frames are otherwise silently dropped.
                async def _wait_ready() -> None:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        kind = msg.get("type") or ""
                        if kind == "error":
                            err = msg.get("error") or {}
                            detail = (
                                err.get("message") or err.get("code") or str(err)
                            )
                            raise RuntimeError(f"OpenAI Realtime STT: {detail}")
                        if kind == "session.updated":
                            return

                try:
                    await asyncio.wait_for(_wait_ready(), timeout=10)
                except asyncio.TimeoutError as exc:
                    raise RuntimeError(
                        "OpenAI Realtime STT: session did not update"
                    ) from exc

                async def pump() -> None:
                    carry = b""
                    sent_any = False
                    try:
                        while True:
                            frame = await frames.get()
                            if frame is None:
                                break
                            pcm24, carry = upsample_pcm16_16k_to_24k(frame, carry)
                            if not pcm24:
                                continue
                            sent_any = True
                            await ws.send(
                                json.dumps(
                                    {
                                        "type": "input_audio_buffer.append",
                                        "audio": base64.b64encode(pcm24).decode(
                                            "ascii"
                                        ),
                                    }
                                )
                            )
                        if carry:
                            # Pad a dangling sample with silence so the ratio
                            # closes cleanly rather than dropping the tail.
                            pcm24, _ = upsample_pcm16_16k_to_24k(carry + b"\x00\x00")
                            if pcm24:
                                sent_any = True
                                await ws.send(
                                    json.dumps(
                                        {
                                            "type": "input_audio_buffer.append",
                                            "audio": base64.b64encode(pcm24).decode(
                                                "ascii"
                                            ),
                                        }
                                    )
                                )
                        if sent_any:
                            await ws.send(
                                json.dumps({"type": "input_audio_buffer.commit"})
                            )
                        else:
                            # Nothing to transcribe — close so the receive loop
                            # exits instead of hanging on an empty session.
                            await ws.close()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        raise

                sender = asyncio.create_task(pump())
                accumulated = ""
                saw_final = False
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        kind = msg.get("type") or ""
                        if kind == "error":
                            err = msg.get("error") or {}
                            detail = (
                                err.get("message") or err.get("code") or str(err)
                            )
                            raise RuntimeError(f"OpenAI Realtime STT: {detail}")
                        if kind == "conversation.item.input_audio_transcription.delta":
                            delta = str(msg.get("delta") or "")
                            if not delta:
                                continue
                            accumulated += delta
                            text = accumulated.strip()
                            if text:
                                yield Transcript(text=text, final=False)
                        elif (
                            kind
                            == "conversation.item.input_audio_transcription.completed"
                        ):
                            text = str(msg.get("transcript") or "").strip()
                            if not text:
                                text = accumulated.strip()
                            saw_final = True
                            if text:
                                yield Transcript(
                                    text=text, final=True, speech_final=True
                                )
                            break
                finally:
                    if not sender.done():
                        sender.cancel()
                    try:
                        await sender
                    except asyncio.CancelledError:
                        pass
                    self._ws = None

                if not saw_final and accumulated.strip():
                    yield Transcript(
                        text=accumulated.strip(), final=True, speech_final=True
                    )

                if feeder.done() and not feeder.cancelled():
                    feeder.result()
        finally:
            if not feeder.done():
                feeder.cancel()
            try:
                await feeder
            except (asyncio.CancelledError, Exception):
                pass

    async def close(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
