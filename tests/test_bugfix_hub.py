"""Bug-sweep regressions for rau/hub/server.py.

Covers: SPA fallback path traversal (a decoded "../" in the URL must never
resolve outside web/dist), /api/voice/preview blank-text validation, and the
/ws/voice feed-error handling (only fatal audio errors may tear down STT).

Run: python -m unittest tests.test_bugfix_hub -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.hub import server  # noqa: E402
from rau.paths import WEB_DIST  # noqa: E402


def _drive(path: str, *, method: str = "GET", body: bytes = b""):
    """Drive the real ASGI app once, the way uvicorn would after decoding.

    uvicorn percent-decodes the request target before routing, so a request
    for /..%2F..%2Frau%2Fhub%2Fserver.py arrives in the scope as the decoded
    path used here.
    """
    sent = []
    incoming = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [
            (b"host", b"localhost:8765"),
            (b"content-type", b"application/json"),
        ],
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
    }
    asyncio.run(server.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body_bytes = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in start["headers"]}
    return start["status"], headers, body_bytes


@unittest.skipUnless((WEB_DIST / "index.html").exists(), "web UI not built")
class SpaPathTraversalTests(unittest.TestCase):
    def test_traversal_to_a_repo_file_is_not_served(self):
        target = WEB_DIST.parent.parent / "rau" / "hub" / "server.py"
        self.assertTrue(target.is_file())
        status, _headers, body = _drive("/../../rau/hub/server.py")
        self.assertNotEqual(body, target.read_bytes())
        self.assertNotIn(b"Rau local hub", body)

    def test_traversal_to_the_filesystem_root_is_not_served(self):
        target = Path("/etc/passwd")
        self.assertTrue(target.is_file())
        depth = len(WEB_DIST.resolve().parts)
        status, _headers, body = _drive("/" + "../" * depth + "etc/passwd")
        self.assertNotEqual(body, target.read_bytes())
        self.assertNotIn(b"root:", body)

    def test_traversal_falls_back_to_the_spa_index(self):
        # Same contract as any unknown client-side route: index.html, 200.
        status, headers, body = _drive("/../../rau/hub/server.py")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB_DIST / "index.html").read_bytes())

    def test_legit_built_files_are_still_served(self):
        status, _headers, body = _drive("/index.html")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB_DIST / "index.html").read_bytes())

    def test_unknown_client_route_still_falls_back_to_index(self):
        status, _headers, body = _drive("/no/such/client/route")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB_DIST / "index.html").read_bytes())

    def test_unmatched_api_route_still_404s(self):
        status, _headers, body = _drive("/api/definitely-not-a-route")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})


class VoicePreviewValidationTests(unittest.TestCase):
    def test_whitespace_only_text_is_rejected_before_synthesis(self):
        payload = json.dumps({"text": "   \n  ", "voice_id": "voice123"}).encode()
        # Reach the validation past the API-key gate without touching the
        # network: the guard must fire before render_preview is ever called.
        with patch.object(server, "has_secret", return_value=True):
            status, _headers, body = _drive(
                "/api/voice/preview", method="POST", body=payload
            )
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(body)["ok"])


class VoiceFeedErrorTests(unittest.TestCase):
    """feed() distinguishes fatal stream errors (mic closed) from one bad
    frame (mic open). The hub must only tear STT down for the fatal kind."""

    def test_bad_frame_keeps_listening_fatal_frame_still_tears_down(self):
        asyncio.run(self._drive_voice())

    @staticmethod
    async def _next(outgoing, timeout=2.0):
        msg = await asyncio.wait_for(outgoing.get(), timeout)
        if msg.get("type") == "websocket.send" and msg.get("text") is not None:
            return json.loads(msg["text"])
        return msg

    async def _assert_quiet(self, outgoing):
        await asyncio.sleep(0.05)
        self.assertTrue(outgoing.empty(), "unexpected extra socket traffic")

    async def _drive_voice(self):
        import rau.voice.session as voice_session

        async def quiet_stt(self, mic, epoch):
            # Never transcribes and never consumes: leaves feed() and the
            # hub's error handling as the only moving parts under test.
            await asyncio.Future()

        scope = {
            "type": "websocket",
            "path": "/ws/voice",
            "headers": [(b"host", b"localhost:8765")],
            "query_string": b"",
            "root_path": "",
            "scheme": "ws",
            "subprotocols": [],
            "client": ("testclient", 50000),
            "server": ("localhost", 8765),
        }
        incoming: asyncio.Queue = asyncio.Queue()
        outgoing: asyncio.Queue = asyncio.Queue()

        async def receive():
            return await incoming.get()

        async def send(message):
            await outgoing.put(message)

        with patch.object(voice_session.VoiceSession, "_run_stt", quiet_stt), \
             patch.object(voice_session, "warm_reactions", lambda: None):
            task = asyncio.create_task(server.app(scope, receive, send))
            try:
                await incoming.put({"type": "websocket.connect"})
                accept = await self._next(outgoing)
                self.assertEqual(accept["type"], "websocket.accept")
                hello = await self._next(outgoing)
                self.assertEqual(hello["t"], "hello")

                await incoming.put({
                    "type": "websocket.receive",
                    "text": json.dumps({"t": "speech_start"}),
                })
                phase = await self._next(outgoing)
                self.assertEqual(phase, {"t": "phase", "phase": "listening"})

                # Non-fatal: an odd byte count is one malformed frame. The
                # error is reported but the session must keep listening —
                # no phase reset, no STT teardown.
                await incoming.put({"type": "websocket.receive", "bytes": b"\x00"})
                err = await self._next(outgoing)
                self.assertEqual(err["t"], "error")
                self.assertIn("PCM16", err["detail"])
                await self._assert_quiet(outgoing)

                # A well-formed frame is still accepted afterwards...
                await incoming.put({
                    "type": "websocket.receive", "bytes": b"\x00" * 640,
                })
                await self._assert_quiet(outgoing)
                # ...and the mic is still open: the next bad frame errors again.
                await incoming.put({"type": "websocket.receive", "bytes": b"\x00"})
                err = await self._next(outgoing)
                self.assertEqual(err["t"], "error")
                self.assertIn("PCM16", err["detail"])

                # Fatal: crossing the utterance cap closes the mic, so the hub
                # still stops STT and returns the session to idle.
                frame = b"\x00" * voice_session.MAX_MIC_FRAME_BYTES
                for _ in range(
                    voice_session.MAX_UTTERANCE_BYTES // len(frame) + 1
                ):
                    await incoming.put({"type": "websocket.receive", "bytes": frame})
                err = await self._next(outgoing)
                self.assertEqual(err["t"], "error")
                self.assertIn("utterance is too long", err["detail"])
                phase = await self._next(outgoing)
                self.assertEqual(phase, {"t": "phase", "phase": "idle"})

                # Dead for good: further frames are ignored silently.
                await incoming.put({"type": "websocket.receive", "bytes": b"\x00"})
                await self._assert_quiet(outgoing)
            finally:
                await incoming.put({"type": "websocket.disconnect", "code": 1000})
                await asyncio.wait_for(task, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
