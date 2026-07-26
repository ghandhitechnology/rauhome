"""
Deepgram streaming STT.

The strongest option for live conversation: a real duplex WebSocket with
interim results every ~100-200ms and server-side endpointing, so we learn the
user has stopped talking without waiting on our own VAD hangover.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from typing import AsyncIterator, Optional
from urllib.parse import urlencode

from rau.env import get_secret
from rau.voice.stt.base import SAMPLE_RATE, SttProvider, Transcript

WS_URL = "wss://api.deepgram.com/v1/listen"


class DeepgramStt(SttProvider):
    name = "deepgram"
    supports_partials = True

    def __init__(self, model: str = "nova-3", language: str = "en"):
        self.model = model or "nova-3"
        self.language = language or "en"
        self._ws = None

    def _url(self) -> str:
        return f"{WS_URL}?" + urlencode(
            {
                "model": self.model,
                "language": self.language,
                "encoding": "linear16",
                "sample_rate": str(SAMPLE_RATE),
                "channels": "1",
                "interim_results": "true",
                "punctuate": "true",
                "smart_format": "true",
                # Deepgram tells us when the speaker paused, which is more
                # reliable than inferring it from our own energy VAD.
                "endpointing": "300",
            }
        )

    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[Transcript]:
        import websockets

        key = get_secret("DEEPGRAM_API_KEY")
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY not set")

        connect_params = inspect.signature(websockets.connect).parameters
        header_arg = (
            "additional_headers"
            if "additional_headers" in connect_params
            else "extra_headers"
        )
        connect_options = {
            header_arg: {"Authorization": f"Token {key}"},
            "open_timeout": 10,
            "close_timeout": 5,
            "ping_interval": 20,
            "ping_timeout": 20,
            "max_size": 1_000_000,
            "max_queue": 32,
        }
        async with websockets.connect(self._url(), **connect_options) as ws:
            self._ws = ws

            async def pump() -> None:
                try:
                    async for frame in audio:
                        await ws.send(frame)
                    # Tell Deepgram to flush rather than just dropping the socket,
                    # otherwise the tail of the last word is lost.
                    await ws.send(json.dumps({"type": "CloseStream"}))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Wake the receive loop so the sender failure is observed
                    # instead of leaving transcription hung forever.
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    raise

            sender = asyncio.create_task(pump())
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if msg.get("type") not in (None, "Results"):
                        continue
                    alt = (
                        ((msg.get("channel") or {}).get("alternatives") or [{}])[0]
                    )
                    text = (alt.get("transcript") or "").strip()
                    if not text:
                        continue
                    yield Transcript(
                        text=text,
                        final=bool(msg.get("is_final")),
                        confidence=alt.get("confidence"),
                    )
            finally:
                if not sender.done():
                    sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass
                self._ws = None

    async def close(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass


def probe_key(key: Optional[str] = None) -> dict:
    """Cheap credential check used by /api/auth/deepgram/verify."""
    import urllib.error
    import urllib.request

    secret = (key or "").strip() or get_secret("DEEPGRAM_API_KEY")
    if not secret:
        return {"ok": False, "detail": "No key saved yet."}
    req = urllib.request.Request(
        "https://api.deepgram.com/v1/projects",
        headers={"Authorization": f"Token {secret}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        n = len(body.get("projects") or [])
        return {"ok": True, "detail": f"{n} project(s) reachable" if n else "authenticated"}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "detail": "Key rejected — check that you pasted the whole key."}
        return {"ok": False, "detail": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"ok": False, "detail": f"Could not reach Deepgram: {e.reason}"}
