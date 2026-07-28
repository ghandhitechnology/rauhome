from __future__ import annotations

import asyncio
import base64
import json
import threading
import unittest
from unittest.mock import patch

from rau.providers.anthropic_compat import AnthropicCompatProvider
from rau.providers.base import Message
from rau.providers.openai_compat import OpenAICompatProvider
from rau.voice.stt.base import Transcript


class _Lines:
    def __init__(self, *lines: bytes):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def __iter__(self):
        return iter(self.lines)


def _openai_payload(name: str, profile: str) -> dict:
    provider = OpenAICompatProvider(name, "https://provider.invalid/v1", "KEY")
    provider._key = lambda: "secret"  # type: ignore[method-assign]
    captured = []

    def open_request(req, timeout, **kwargs):
        captured.append((req, timeout, kwargs))
        return _Lines(b"data: [DONE]\n")

    provider._open = open_request  # type: ignore[method-assign]
    list(
        provider.stream_turn(
            [Message("system", "same prompt"), Message("user", "hi")],
            model="same-model",
            max_tokens=321,
            temperature=0.42,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "same_tool",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            effort="medium",
            latency_profile=profile,
        )
    )
    request, _timeout, kwargs = captured[0]
    payload = json.loads(request.data)
    payload["_pooled"] = bool(kwargs.get("pooled"))
    return payload


class ProviderProfileTests(unittest.TestCase):
    def test_all_openai_compatible_adapters_keep_quality_parameters(self) -> None:
        for name in ("deepseek", "kimi", "moonshot", "codex", "openai"):
            with self.subTest(provider=name):
                normal = _openai_payload(name, "normal")
                hyper = _openai_payload(name, "hyper")
                self.assertFalse(normal.pop("_pooled"))
                self.assertTrue(hyper.pop("_pooled"))
                self.assertEqual(hyper, normal)
                self.assertNotIn("provider", hyper)

    def test_openrouter_only_adds_same_model_latency_routing(self) -> None:
        normal = _openai_payload("openrouter", "normal")
        hyper = _openai_payload("openrouter", "hyper")
        self.assertFalse(normal.pop("_pooled"))
        self.assertTrue(hyper.pop("_pooled"))
        routing = hyper.pop("provider")
        self.assertEqual(hyper, normal)
        self.assertEqual(hyper["model"], "same-model")
        self.assertEqual(routing["sort"], {"by": "latency", "partition": "model"})
        self.assertTrue(routing["require_parameters"])
        self.assertTrue(routing["allow_fallbacks"])

    def test_anthropic_compatible_hyper_keeps_payload_and_uses_pool(self) -> None:
        provider = AnthropicCompatProvider(
            "kimi_code", "https://provider.invalid", "KEY"
        )
        provider._key = lambda: "secret"  # type: ignore[method-assign]
        captured = []

        def pooled(req, timeout):
            captured.append((req, timeout))
            return _Lines(b"data: {\"type\":\"message_delta\",\"delta\":{}}\n")

        provider._pooled_stream = pooled  # type: ignore[method-assign]
        kwargs = {
            "model": "same-model",
            "max_tokens": 321,
            "temperature": 0.42,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "same_tool",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            "effort": "medium",
        }
        normal_requests = []

        def normal(req, timeout):
            normal_requests.append((req, timeout))
            return _Lines(b"data: {\"type\":\"message_delta\",\"delta\":{}}\n")

        with patch(
            "rau.providers.anthropic_compat.urllib.request.urlopen",
            side_effect=normal,
        ):
            list(
                provider.stream_turn(
                    [Message("system", "same prompt"), Message("user", "hi")],
                    latency_profile="normal",
                    **kwargs,
                )
            )
        list(
            provider.stream_turn(
                [Message("system", "same prompt"), Message("user", "hi")],
                latency_profile="hyper",
                **kwargs,
            )
        )
        payload = json.loads(captured[0][0].data)
        self.assertEqual(payload, json.loads(normal_requests[0][0].data))
        self.assertEqual(payload["model"], "same-model")
        self.assertEqual(payload["max_tokens"], 321)
        # Extended thinking intentionally makes temperature unsupported for
        # this adapter; Hyper must not invent a replacement.
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["system"], "same prompt")
        self.assertEqual(payload["messages"][0]["content"][0]["text"], "hi")
        self.assertEqual(payload["tools"][0]["name"], "same_tool")
        self.assertNotIn("provider", payload)


class SessionDiagnosticsTests(unittest.TestCase):
    def test_hello_advertises_optional_voice_commands(self) -> None:
        from rau.voice.session import session_info

        with patch("rau.voice.session.resolve_stt", return_value=("deepgram", {})):
            hello = session_info("hyper")
        self.assertEqual(hello["profile"], "hyper")
        self.assertIn("latency_profile", hello["capabilities"])
        self.assertIn("latency_metrics", hello["capabilities"])


class ProfileAndEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _run_segments(self, profile: str):
        from rau.voice import session as voice_session

        sent = []
        turns = []

        async def send_json(payload):
            sent.append(payload)

        async def send_bytes(_payload):
            return None

        class Segments:
            closed = False

            async def stream(self, _audio):
                yield Transcript("hello", final=True, speech_final=True)
                yield Transcript("hello", final=True)
                yield Transcript("world", final=True)
                yield Transcript("hello", final=True)  # stale prefix replay

            async def close(self):
                self.closed = True

        provider = Segments()
        session = voice_session.VoiceSession(
            send_json, send_bytes, profile=profile
        )
        session.phase = "listening"

        async def capture(text):
            turns.append(text)

        session.begin_turn = capture  # type: ignore[method-assign]
        mic = voice_session._MicStream(asyncio.Queue())
        original = voice_session.get_stt_provider
        voice_session.get_stt_provider = lambda: provider
        try:
            await session._run_stt(mic, session._stt_epoch)
        finally:
            voice_session.get_stt_provider = original
            await session.close()
        return sent, turns, provider

    async def test_hyper_commits_deepgram_speech_final_immediately(self) -> None:
        sent, turns, provider = await self._run_segments("hyper")
        self.assertTrue(provider.closed)
        self.assertEqual(turns, ["hello"])
        self.assertEqual(
            len([item for item in sent if item.get("t") == "endpoint"]), 1
        )

    async def test_normal_ignores_early_signal_and_keeps_existing_fallback(self) -> None:
        sent, turns, _provider = await self._run_segments("normal")
        self.assertEqual(turns, ["hello world"])
        self.assertFalse(any(item.get("t") == "endpoint" for item in sent))

    async def test_profile_is_idle_only_and_invalid_values_fall_back(self) -> None:
        from rau.voice.session import VoiceSession

        async def noop(_payload):
            return None

        session = VoiceSession(noop, noop, profile="invalid")
        self.assertEqual(session.profile, "normal")
        session.set_profile("hyper")
        self.assertEqual(session.profile, "hyper")
        session.phase = "listening"
        with self.assertRaisesRegex(ValueError, "idle"):
            session.set_profile("normal")
        await session.close()

    async def test_hyper_turn_routes_model_tokens_to_realtime_tts(self) -> None:
        from rau.voice import session as voice_session

        sent_audio = []
        spoken_tokens = []
        called_with = {}

        async def send_json(_payload):
            return None

        async def send_bytes(payload):
            sent_audio.append(payload)

        def fake_chat(_text, *, on_token, cancel, **_kwargs):
            self.assertFalse(cancel.is_set())
            on_token("The Hyper reply is audible.")
            return "The Hyper reply is audible."

        def fake_realtime(tokens, *, on_audio, on_sentence, **kwargs):
            called_with.update(kwargs)
            for token in tokens:
                spoken_tokens.append(token)
                on_sentence(token)
                on_audio(b"\x01\x00" * 48)
                yield None

        with (
            patch.object(voice_session.brain, "chat_streaming", side_effect=fake_chat),
            patch.object(
                voice_session,
                "speak_realtime_stream",
                side_effect=fake_realtime,
            ) as realtime,
            patch.object(voice_session, "HESITATIONS_ENABLED", False),
        ):
            session = voice_session.VoiceSession(
                send_json, send_bytes, profile="hyper"
            )
            try:
                await session.begin_turn("Say something")
                turn = session._active_turn
                assert turn is not None and turn.thread is not None
                await asyncio.to_thread(turn.thread.join, 2)
                await asyncio.sleep(0.02)
            finally:
                await session.close()

        realtime.assert_called_once()
        self.assertEqual(spoken_tokens, ["The Hyper reply is audible."])
        self.assertTrue(sent_audio)
        self.assertIn("session", called_with)
        self.assertIn("context_id", called_with)


class RealtimeTtsTests(unittest.TestCase):
    def _slot(self):
        return {
            "voice_id": "voice",
            "model": "eleven_flash_v2_5",
            "voice_settings": {"stability": 0.5},
            "effect": "none",
        }

    def test_connect_failure_falls_back_without_losing_tokens(self) -> None:
        from rau.voice import tts_stream

        replayed = []

        def fallback(tokens, **_kwargs):
            replayed.extend(tokens)
            yield None

        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "get_secret", return_value="key"),
            patch.object(tts_stream, "speak_stream", side_effect=fallback),
            patch("websockets.sync.client.connect", side_effect=OSError("down")),
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Hello ", "there."]), on_audio=lambda _pcm: None
                )
            )
        self.assertEqual(replayed, ["Hello ", "there."])

    def test_session_reuses_one_multi_context_socket(self) -> None:
        from rau.voice import tts_stream

        class Socket:
            def __init__(self):
                self.sent = []
                self.closed = threading.Event()

            def send(self, message):
                self.sent.append(json.loads(message))

            def recv(self):
                self.closed.wait(1)
                return None

            def close(self):
                self.closed.set()

        socket = Socket()
        with (
            patch.object(tts_stream, "get_secret", return_value="key"),
            patch(
                "websockets.sync.client.connect", return_value=socket
            ) as connect,
        ):
            session = tts_stream.RealtimeTtsSession()
            first = session.open_context(
                "turn-1",
                voice_id="voice",
                model="eleven_flash_v2_5",
                voice_settings={"stability": 0.5},
            )
            second = session.open_context(
                "turn-2",
                voice_id="voice",
                model="eleven_flash_v2_5",
                voice_settings={"stability": 0.5},
            )
            self.assertIsNot(first, second)
            session.close_context("turn-1")
            session.close()

        connect.assert_called_once()
        url = connect.call_args.args[0]
        self.assertIn("/multi-stream-input?", url)
        self.assertIn("inactivity_timeout=180", url)
        self.assertIn("sync_alignment=true", url)
        self.assertEqual(socket.sent[0]["context_id"], "turn-1")
        self.assertEqual(socket.sent[1]["context_id"], "turn-2")
        self.assertTrue(
            any(
                item.get("context_id") == "turn-1"
                and item.get("close_context") is True
                for item in socket.sent
            )
        )
        self.assertEqual(socket.sent[-1], {"close_socket": True})

    def test_context_flush_uses_the_documented_control_frame(self) -> None:
        from rau.voice import tts_stream

        sent = []
        session = tts_stream.RealtimeTtsSession()
        socket = object()
        session._contexts["turn"] = (socket, __import__("queue").Queue())
        session._send = lambda payload, **_kwargs: sent.append(payload)  # type: ignore[method-assign]

        session.flush_context("turn")

        self.assertEqual(sent, [{"context_id": "turn", "flush": True}])

    def test_finished_context_keeps_receiving_until_terminal_frame(self) -> None:
        from rau.voice import tts_stream

        sent = []
        session = tts_stream.RealtimeTtsSession()
        socket = object()
        messages = __import__("queue").Queue()
        session._contexts["turn"] = (socket, messages)
        session._send = lambda payload, **_kwargs: sent.append(payload)  # type: ignore[method-assign]

        session.finish_context("turn")
        self.assertIs(session._contexts["turn"][1], messages)
        session.close_context("turn")

        self.assertNotIn("turn", session._contexts)
        self.assertEqual(
            sent, [{"context_id": "turn", "close_context": True}]
        )

    def test_pre_audio_receive_failure_falls_back_once(self) -> None:
        from rau.voice import tts_stream

        replayed = []

        class Socket:
            ready = threading.Event()

            def send(self, message):
                if "context_id" in message:
                    self.ready.set()
                return None

            def recv(self, **_kwargs):
                self.ready.wait(1)
                raise OSError("socket failed")

            def close(self):
                return None

        def fallback(tokens, **_kwargs):
            replayed.extend(tokens)
            yield None

        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "get_secret", return_value="key"),
            patch.object(tts_stream, "speak_stream", side_effect=fallback) as http,
            patch("websockets.sync.client.connect", return_value=Socket()),
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Hello ", "there."]), on_audio=lambda _pcm: None
                )
            )
        self.assertEqual(http.call_count, 1)
        self.assertEqual(replayed, ["Hello ", "there."])

    def test_socket_level_provider_error_is_not_silently_discarded(self) -> None:
        from rau.voice import tts_stream

        replayed = []

        class Socket:
            ready = threading.Event()

            def send(self, message):
                if "context_id" in message:
                    self.ready.set()

            def recv(self, **_kwargs):
                self.ready.wait(1)
                return json.dumps(
                    {"type": "error", "code": "invalid_message", "detail": "secret"}
                )

            def close(self):
                return None

        def fallback(tokens, **_kwargs):
            replayed.extend(tokens)
            yield None

        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "get_secret", return_value="key"),
            patch.object(tts_stream, "speak_stream", side_effect=fallback) as http,
            patch("websockets.sync.client.connect", return_value=Socket()),
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Hello there."]), on_audio=lambda _pcm: None
                )
            )

        http.assert_called_once()
        self.assertEqual(replayed, ["Hello there."])

    def test_audio_less_final_falls_back_instead_of_finishing_silently(self) -> None:
        from rau.voice import tts_stream

        replayed = []

        class Session:
            def __init__(self):
                self.messages = __import__("queue").Queue()

            def open_context(self, *_args, **_kwargs):
                return self.messages

            def text(self, context_id, text, *, flush=False):
                self.messages.put({"context_id": context_id, "is_final": True})

            def flush_context(self, _context_id):
                return None

            def finish_context(self, _context_id):
                return None

            def close_context(self, _context_id):
                return None

        def fallback(tokens, **_kwargs):
            replayed.extend(tokens)
            yield None

        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "speak_stream", side_effect=fallback) as http,
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Hello there."]),
                    on_audio=lambda _pcm: None,
                    session=Session(),
                )
            )

        http.assert_called_once()
        self.assertEqual(replayed, ["Hello there."])

    def test_silent_context_deadline_falls_back_once(self) -> None:
        from rau.voice import tts_stream

        replayed = []

        class Session:
            def __init__(self):
                self.messages = __import__("queue").Queue()

            def open_context(self, *_args, **_kwargs):
                return self.messages

            def text(self, *_args, **_kwargs):
                return None

            def flush_context(self, _context_id):
                return None

            def finish_context(self, _context_id):
                return None

            def close_context(self, _context_id):
                return None

        def fallback(tokens, **_kwargs):
            replayed.extend(tokens)
            yield None

        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(
                tts_stream, "REALTIME_FIRST_AUDIO_TIMEOUT_SEC", 0.01
            ),
            patch.object(tts_stream, "speak_stream", side_effect=fallback) as http,
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Hello there."]),
                    on_audio=lambda _pcm: None,
                    session=Session(),
                )
            )

        http.assert_called_once()
        self.assertEqual(replayed, ["Hello there."])

    def test_healthy_realtime_context_emits_audio_without_http_fallback(self) -> None:
        from rau.voice import tts_stream

        pcm = b"\x02\x00" * 32

        class Session:
            def __init__(self):
                self.messages = __import__("queue").Queue()

            def open_context(self, *_args, **_kwargs):
                return self.messages

            def text(self, context_id, text, *, flush=False):
                self.messages.put(
                    {
                        "context_id": context_id,
                        "audio": base64.b64encode(pcm).decode(),
                        "is_final": True,
                    }
                )

            def flush_context(self, _context_id):
                return None

            def finish_context(self, _context_id):
                return None

            def close_context(self, _context_id):
                return None

        heard = []
        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "speak_stream") as http,
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Hello there."]),
                    on_audio=heard.append,
                    session=Session(),
                )
            )

        self.assertEqual(heard, [pcm])
        http.assert_not_called()

    def test_effect_timing_precedes_pcm_for_streaming_captions(self) -> None:
        from rau.voice import tts_stream

        text = "Hello there."
        pcm = b"\x02\x00" * 32

        class Session:
            def __init__(self):
                self.messages = __import__("queue").Queue()

            def open_context(self, *_args, **_kwargs):
                return self.messages

            def text(self, context_id, value, *, flush=False):
                chars = list(value)
                self.messages.put(
                    {
                        "context_id": context_id,
                        "audio": base64.b64encode(pcm).decode(),
                        "normalizedAlignment": {
                            "chars": chars,
                            # Match the actual multi-context WebSocket wire
                            # format, which differs from the HTTP timestamp
                            # response's snake_case fields.
                            "charStartTimesMs": list(range(len(chars))),
                        },
                        "is_final": True,
                    }
                )

            def flush_context(self, _context_id):
                return None

            def finish_context(self, _context_id):
                return None

            def close_context(self, _context_id):
                return None

        class Voice:
            def __init__(self, _effect):
                return None

            def process_pcm(self, value):
                return value

        events = []
        slot = {**self._slot(), "effect": "robot"}
        with (
            patch.object(tts_stream, "get_slot", return_value=slot),
            patch.object(tts_stream, "RobotVoice", Voice),
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter([text]),
                    on_audio=lambda _pcm: events.append("audio"),
                    on_timing=lambda _timing: events.append("timing"),
                    session=Session(),
                )
            )

        self.assertEqual(events, ["timing", "audio"])

    def test_cancellation_closes_only_the_turn_context_without_fallback(self) -> None:
        from rau.voice import tts_stream

        cancel = threading.Event()
        cancel.set()

        class Session:
            def __init__(self):
                self.messages = __import__("queue").Queue()
                self.closed = []

            def open_context(self, *_args, **_kwargs):
                return self.messages

            def text(self, *_args, **_kwargs):
                raise AssertionError("cancelled tokens must not be submitted")

            def flush_context(self, _context_id):
                return None

            def finish_context(self, _context_id):
                return None

            def close_context(self, context_id):
                self.closed.append(context_id)

        session = Session()
        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "speak_stream") as http,
        ):
            list(
                tts_stream.speak_realtime_stream(
                    iter(["Do not say this."]),
                    on_audio=lambda _pcm: None,
                    cancel=cancel,
                    session=session,
                    context_id="cancelled-turn",
                )
            )

        self.assertIn("cancelled-turn", session.closed)
        http.assert_not_called()

    def test_failure_after_audio_never_replays_speech(self) -> None:
        from rau.voice import tts_stream

        pcm = b"\x01\x00" * 16

        class Socket:
            calls = 0
            ready = threading.Event()

            def send(self, message):
                if "context_id" in message:
                    self.ready.set()
                return None

            def recv(self, **_kwargs):
                self.ready.wait(1)
                self.calls += 1
                if self.calls == 1:
                    return json.dumps(
                        {
                            "contextId": "turn",
                            "audio": base64.b64encode(pcm).decode(),
                        }
                    )
                raise OSError("socket failed")

            def close(self):
                return None

        heard = []
        with (
            patch.object(tts_stream, "get_slot", return_value=self._slot()),
            patch.object(tts_stream, "get_secret", return_value="key"),
            patch.object(tts_stream, "speak_stream") as http,
            patch("websockets.sync.client.connect", return_value=Socket()),
        ):
            with self.assertRaises(OSError):
                list(
                    tts_stream.speak_realtime_stream(
                        iter(["Hello there."]), on_audio=heard.append
                    )
                )
        self.assertEqual(heard, [pcm])
        http.assert_not_called()

    def test_pitch_effect_degrades_to_quality_preserving_phrase_processing(self) -> None:
        from rau.voice import tts_stream

        processed = []

        class Voice:
            def __init__(self, _effect):
                return None

            def process_pcm(self, value):
                processed.append(value)
                return value

        pcm = b"\x10\x00" * 100
        with patch.object(tts_stream, "RobotVoice", Voice):
            effect = tts_stream.StreamingRobotVoice("robot")
            self.assertEqual(effect.push(pcm[:100]), [])
            self.assertEqual(effect.push(pcm[100:]), [])
            output = effect.flush()
        self.assertEqual(processed, [pcm])
        self.assertEqual(len(output), 1)
        self.assertEqual(len(output[0]), len(pcm))


class BenchmarkTests(unittest.TestCase):
    def test_acceptance_requires_target_and_no_p95_regression(self) -> None:
        from scripts.benchmark_voice_latency import summarize

        records = []
        for _ in range(30):
            records.extend((("normal", 1700.0), ("hyper", 1200.0)))
        result = summarize(records, 30)
        self.assertTrue(result["passed"])
        self.assertEqual(result["hyper"]["median_ms"], 1200.0)

    def test_acceptance_rejects_non_alternating_runs(self) -> None:
        from scripts.benchmark_voice_latency import summarize

        with self.assertRaisesRegex(ValueError, "alternate"):
            summarize([("normal", 1000.0), ("normal", 900.0)], 1)


if __name__ == "__main__":
    unittest.main()
