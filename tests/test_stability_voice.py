"""Regressions for the voice-backend stability sweep (V1–V11)."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import types
import unittest
from unittest import mock


def _wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TokenPipeCancelTests(unittest.TestCase):
    def test_iter_unblocks_on_cancel_instead_of_waiting_for_the_producer(self):
        from rau.voice.session import _TokenPipe

        pipe = _TokenPipe()
        cancel = threading.Event()
        out = []

        def consume():
            out.extend(pipe.iter(cancel=cancel))

        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        time.sleep(0.1)
        cancel.set()
        worker.join(1.0)
        self.assertFalse(worker.is_alive(), "cancelled consumer stayed parked")
        self.assertEqual(out, [])


class CancelTurnPlumbingTests(unittest.IsolatedAsyncioTestCase):
    async def _session(self):
        from rau.voice import session as voice_session

        sent_json = []

        async def send_json_(payload):
            sent_json.append(payload)

        async def send_bytes(_payload):
            return None

        return voice_session.VoiceSession(send_json_, send_bytes), sent_json

    async def test_cancel_turn_closes_the_token_pipe(self):
        from rau.voice import session as voice_session

        session, _ = await self._session()
        try:
            turn = voice_session._Turn(1, "hi")
            pipe = voice_session._TokenPipe()
            self.assertTrue(pipe.put("token"))
            turn.token_pipe = pipe
            await session._cancel_turn(turn, 0.0)

            out = []

            def consume():
                out.extend(pipe.iter())

            worker = threading.Thread(target=consume, daemon=True)
            worker.start()
            worker.join(1.0)
            self.assertFalse(worker.is_alive(), "pipe was not closed on cancel")
            self.assertEqual(out, ["token"])
        finally:
            await session.close()

    async def test_cancel_turn_commits_the_interruption_to_history(self):
        from rau.voice import session as voice_session

        session, _ = await self._session()
        try:
            turn = voice_session._Turn(1, "hi")
            turn.reply = voice_session.brain.StreamingReply(
                "full reply text", None, "user question", True, "tid"
            )
            # 100 ms of PCM @ 24 kHz; played past the midpoint it is heard.
            turn.utterance.add("Hello there.", b"\x00\x00" * 2400)
            with mock.patch.object(
                voice_session.brain, "finish_interrupted_turn"
            ) as finish:
                await session._cancel_turn(turn, 60.0)
            finish.assert_called_once_with(turn.reply, "Hello there.")
        finally:
            await session.close()

    async def test_cancel_turn_ignores_a_non_streaming_reply(self):
        from rau.voice import session as voice_session

        session, _ = await self._session()
        try:
            turn = voice_session._Turn(1, "hi")
            turn.reply = "a plain string reply"
            with mock.patch.object(
                voice_session.brain, "finish_interrupted_turn"
            ) as finish:
                await session._cancel_turn(turn, 0.0)
            finish.assert_not_called()
        finally:
            await session.close()


class TurnLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from rau.voice import session as voice_session

        self.voice_session = voice_session
        self.sent_json = []
        self._chat = voice_session.brain.chat_streaming
        self._speak = voice_session.speak_stream

    def tearDown(self):
        self.voice_session.brain.chat_streaming = self._chat
        self.voice_session.speak_stream = self._speak

    async def _send_json(self, payload):
        self.sent_json.append(payload)

    async def _send_bytes(self, _payload):
        return None

    def _install(self, chat):
        def fake_speak(tokens, *, on_audio, on_sentence, cancel, **_kwargs):
            for token in tokens:
                if cancel.is_set():
                    return
                on_sentence(token)
                on_audio(b"\x01\x02" * 240)
                yield None

        self.voice_session.brain.chat_streaming = chat
        self.voice_session.speak_stream = fake_speak

    async def _run_session(self):
        session = self.voice_session.VoiceSession(self._send_json, self._send_bytes)
        return session

    async def test_a_cancelled_turn_settles_the_phase_to_idle(self):
        """V1: a stop/barge with no following speech_start must not stick."""
        def fake_chat(text, *, on_token, cancel, **_kwargs):
            cancel.wait(1.0)
            return ""

        self._install(fake_chat)
        session = await self._run_session()
        try:
            await session.begin_turn("hello there")
            turn = session._active_turn
            assert turn is not None and turn.thread is not None
            self.assertEqual(session.phase, "thinking")
            await session._cancel_turn(turn, 0.0)
            await asyncio.to_thread(turn.thread.join, 2)
            await asyncio.sleep(0.05)
            self.assertFalse(turn.thread.is_alive())
            self.assertEqual(session.phase, "idle")
            phases = [p.get("phase") for p in self.sent_json if p.get("t") == "phase"]
            self.assertEqual(phases[-1], "idle")
        finally:
            await session.close()

    async def test_a_diary_failure_still_sends_say_end_and_idle(self):
        """V3: commit_streamed_turn does disk IO; an OSError is not fatal."""
        def fake_chat(text, *, on_token, cancel, **_kwargs):
            on_token("Here is the answer.")
            return self.voice_session.brain.StreamingReply(
                "Here is the answer.", None, text, True, "tid"
            )

        self._install(fake_chat)
        session = await self._run_session()
        try:
            with mock.patch.object(
                self.voice_session.brain,
                "commit_streamed_turn",
                side_effect=OSError("disk full"),
            ):
                await session.begin_turn("what is the answer")
                turn = session._active_turn
                assert turn is not None and turn.thread is not None
                await asyncio.to_thread(turn.thread.join, 4)
                await asyncio.sleep(0.05)
            self.assertFalse(turn.thread.is_alive())
            ends = [p for p in self.sent_json if p.get("t") == "say_end"]
            self.assertTrue(ends, "say_end was skipped after the diary failure")
            self.assertFalse(ends[-1].get("interrupted"))
            self.assertEqual(session.phase, "idle")
        finally:
            await session.close()

    async def test_a_diary_failure_on_cancel_still_notifies_and_settles(self):
        """V3: finish_interrupted_turn failing must not skip say_end/idle."""
        def fake_chat(text, *, on_token, cancel, **_kwargs):
            cancel.wait(1.0)
            return self.voice_session.brain.StreamingReply(
                "partial reply", None, text, True, "tid"
            )

        self._install(fake_chat)
        session = await self._run_session()
        try:
            with mock.patch.object(
                self.voice_session.brain,
                "finish_interrupted_turn",
                side_effect=OSError("disk full"),
            ):
                await session.begin_turn("tell me something")
                turn = session._active_turn
                assert turn is not None and turn.thread is not None
                await session._cancel_turn(turn, 0.0)
                await asyncio.to_thread(turn.thread.join, 4)
                await asyncio.sleep(0.05)
            self.assertFalse(turn.thread.is_alive())
            ends = [p for p in self.sent_json if p.get("t") == "say_end"]
            self.assertTrue(ends, "interrupted say_end was skipped")
            self.assertTrue(ends[-1].get("interrupted"))
            self.assertEqual(session.phase, "idle")
        finally:
            await session.close()

    async def test_a_cancelled_model_still_closes_the_pipe_when_diary_fails(self):
        """V3: the producer's Cancelled path must always reach tokens.close()."""
        def fake_chat(text, *, on_token, cancel, **_kwargs):
            raise self.voice_session.brain.Cancelled(
                pending=None, generated="", user_text=text, turn_id=""
            )

        self._install(fake_chat)
        session = await self._run_session()
        try:
            with mock.patch.object(
                self.voice_session.brain,
                "finish_interrupted_turn",
                side_effect=OSError("disk full"),
            ):
                await session.begin_turn("hello")
                turn = session._active_turn
                assert turn is not None and turn.thread is not None
                await asyncio.to_thread(turn.thread.join, 4)
                await asyncio.sleep(0.05)
            self.assertFalse(turn.thread.is_alive())
            ends = [p for p in self.sent_json if p.get("t") == "say_end"]
            self.assertTrue(ends, "worker never settled after the diary failure")
        finally:
            await session.close()


class EstimatedPlaybackTests(unittest.TestCase):
    def test_the_estimate_is_biased_down_by_the_send_ahead_budget(self):
        from rau.voice import session as voice_session

        turn = voice_session._Turn(1, "hi")
        turn.utterance.add("Hello.", b"\x00\x00" * (24_000 * 2))  # 2s
        turn.first_audio_at = time.monotonic() - 1.0
        self.assertAlmostEqual(
            turn.estimated_played_ms(),
            1000.0 - voice_session.MAX_PLAYBACK_AHEAD_SEC * 1000.0,
            delta=150.0,
        )

    def test_the_bias_never_goes_negative(self):
        from rau.voice import session as voice_session

        turn = voice_session._Turn(1, "hi")
        turn.utterance.add("Hello.", b"\x00\x00" * (24_000 * 2))
        turn.first_audio_at = time.monotonic() - 0.1
        self.assertEqual(turn.estimated_played_ms(), 0.0)


class FinalizeWatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_timeout(self, bytes_seen: int) -> float:
        from rau.voice import session as voice_session

        async def send_json(_payload):
            return None

        async def send_bytes(_payload):
            return None

        session = voice_session.VoiceSession(send_json, send_bytes)
        captured = {}

        def fake_watch(task, timeout=0.0):
            captured["timeout"] = timeout

            async def noop():
                return None

            return noop()

        session._watch_stt_finalization = fake_watch  # type: ignore[method-assign]
        mic = voice_session._MicStream(asyncio.Queue())
        mic.bytes_seen = bytes_seen
        session._mic = mic
        session._stt_task = asyncio.create_task(asyncio.sleep(5))
        try:
            await session.speech_end()
        finally:
            await session.close()
        return captured["timeout"]

    async def test_a_long_utterance_gets_a_longer_finalize_budget(self):
        timeout = await self._capture_timeout(16000 * 2 * 60)  # 60s of PCM16
        self.assertEqual(timeout, 60.0)

    async def test_a_short_utterance_keeps_the_floor(self):
        from rau.voice import session as voice_session

        timeout = await self._capture_timeout(16000 * 2 * 3)
        self.assertEqual(timeout, voice_session.STT_FINALIZE_SEC)


class SttTailTests(unittest.IsolatedAsyncioTestCase):
    async def _run_provider(self, provider, *, epoch=1, session_epoch=1, phase="listening"):
        from rau.voice import session as voice_session

        sent = []

        async def send_json(payload):
            sent.append(payload)

        async def send_bytes(_payload):
            return None

        original_factory = voice_session.get_stt_provider
        voice_session.get_stt_provider = lambda: provider
        session = voice_session.VoiceSession(send_json, send_bytes)
        turns = []

        async def capture_turn(text):
            turns.append(text)

        session.begin_turn = capture_turn  # type: ignore[method-assign]
        mic = voice_session._MicStream(asyncio.Queue())
        mic.queue.put_nowait(None)
        if session_epoch is not None:
            session._stt_epoch = session_epoch
        session.phase = phase
        try:
            await session._run_stt(mic, epoch)
        finally:
            await session.close()
            voice_session.get_stt_provider = original_factory
        return session, sent, turns

    async def test_a_failed_stream_still_commits_settled_finals(self):
        """V7: an error after settled finals must not drop the transcript."""
        from rau.voice.stt.base import Transcript

        class FlakyStt:
            async def stream(self, audio):
                async for _ in audio:
                    pass
                yield Transcript("settled words", final=True)
                raise RuntimeError("connection died")

            async def close(self):
                return None

        with self.assertLogs("rau.voice.session", level="WARNING"):
            session, sent, turns = await self._run_provider(FlakyStt())
        self.assertEqual(turns, ["settled words"])
        self.assertTrue(any(p.get("t") == "error" for p in sent))
        finals = [p for p in sent if p.get("t") == "final"]
        self.assertEqual(finals[-1]["text"], "settled words")

    async def test_a_failed_stream_without_finals_does_not_commit(self):
        class DeadStt:
            async def stream(self, audio):
                async for _ in audio:
                    pass
                yield Transcript("only a partial", final=False)
                raise RuntimeError("connection died")

            async def close(self):
                return None

        session, sent, turns = await self._run_provider(DeadStt())
        self.assertEqual(turns, [])
        self.assertFalse(any(p.get("t") == "final" for p in sent))

    async def test_an_invalidated_empty_tail_cannot_idle_a_new_utterance(self):
        """V9: the empty branch takes the same epoch guard as the commit."""
        class EmptyStt:
            async def stream(self, audio):
                async for _ in audio:
                    pass
                if False:
                    yield None

            async def close(self):
                return None

        session, sent, _ = await self._run_provider(
            EmptyStt(), epoch=1, session_epoch=2
        )
        self.assertEqual(session.phase, "listening")
        self.assertFalse(
            any(p.get("t") == "phase" and p.get("phase") == "idle" for p in sent)
        )

    async def test_a_current_empty_tail_settles_listening_to_idle(self):
        class EmptyStt:
            async def stream(self, audio):
                async for _ in audio:
                    pass
                if False:
                    yield None

            async def close(self):
                return None

        session, sent, _ = await self._run_provider(EmptyStt(), epoch=1, session_epoch=1)
        self.assertEqual(session.phase, "idle")


class SentenceBufferStabilityTests(unittest.TestCase):
    def test_a_terminator_at_the_buffer_edge_is_not_a_sentence_end(self):
        from rau.voice.tts_stream import SentenceBuffer

        buf = SentenceBuffer()
        out = []
        for token in ["…roughly 3", ".", "5 today"]:
            out += buf.push(token)
        self.assertEqual(out, [])
        self.assertEqual(buf.flush(), "…roughly 3.5 today")

    def test_a_short_sentence_merges_instead_of_shipping_alone(self):
        from rau.voice.tts_stream import SentenceBuffer

        buf = SentenceBuffer()
        out = buf.push("Hi. ")
        out += buf.push("How are you? ")
        # Corrected contract: a short head no longer waits for flush() — it
        # releases merged with what follows as soon as a later boundary makes
        # the accumulated span long enough to speak.
        self.assertEqual(out, ["Hi. How are you?"])
        self.assertIsNone(buf.flush())

    def test_a_short_sentence_no_longer_stalls_the_rest_of_the_reply(self):
        from rau.voice.tts_stream import SentenceBuffer

        buf = SentenceBuffer()
        out = buf.push("The first sentence here is long enough to open. ")
        self.assertEqual(out, ["The first sentence here is long enough to open."])
        out += buf.push("Yes. ")
        out += buf.push("And now a second long sentence that should stream. ")
        # A third sentence is mid-flight: the stream is not over, so nothing
        # here may depend on flush() to be heard.
        out += buf.push("And a third one is still being written")
        self.assertIn("Yes. And now a second long sentence that should stream.", out)
        self.assertEqual(buf.flush(), "And a third one is still being written")

    def test_a_hesitation_still_releases_at_the_buffer_edge(self):
        from rau.voice.tts_stream import SentenceBuffer

        buf = SentenceBuffer()
        self.assertEqual(buf.push("음…"), ["음…"])

    def test_a_leading_emotion_tag_is_dropped(self):
        from rau.voice.tts_stream import _without_leading_emotion_tag

        tokens = iter(["[HAP", "PY] Yes", ", that is", " right."])
        joined = "".join(_without_leading_emotion_tag(tokens))
        self.assertEqual(joined.strip(), "Yes, that is right.")

    def test_text_that_only_looks_taggy_is_kept_verbatim(self):
        from rau.voice.tts_stream import _without_leading_emotion_tag

        joined = "".join(_without_leading_emotion_tag(iter(["[NOTE]", " keep me."])))
        self.assertIn("[NOTE]", joined)

    def test_a_bracket_stub_at_stream_end_is_kept(self):
        from rau.voice.tts_stream import _without_leading_emotion_tag

        joined = "".join(_without_leading_emotion_tag(iter(["[HAP"])))
        self.assertEqual(joined, "[HAP")

    def test_speak_stream_never_sends_the_tag_to_the_provider(self):
        from rau.voice import tts_stream

        requests = []

        class FakeTts:
            def stream(self, **kwargs):
                requests.append(kwargs["text"])
                return iter([b"\x00\x00" * 240])

        class FakeClient:
            text_to_speech = FakeTts()

        original_client = tts_stream._client
        original_slot = tts_stream.get_slot
        tts_stream._client = lambda: FakeClient()
        tts_stream.get_slot = lambda _name: {
            "voice_id": "v",
            "model": "m",
            "effect": "none",
        }
        try:
            audio = []
            for _ in tts_stream.speak_stream(
                iter(["[HAPPY] ", "Yes, that is right."]),
                on_audio=audio.append,
            ):
                pass
        finally:
            tts_stream._client = original_client
            tts_stream.get_slot = original_slot
        self.assertTrue(requests)
        self.assertTrue(all("HAPPY" not in text for text in requests))
        self.assertIn("Yes, that is right.", " ".join(requests))
        self.assertTrue(audio)


class DeepgramConnectBufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_handshake_still_receives_the_whole_utterance(self):
        """V6: frames are buffered locally while the socket connects."""
        from rau.voice.stt import deepgram

        events = []

        class FakeWs:
            def __init__(self):
                self.sent = []

            async def send(self, data):
                self.sent.append(data)

            async def close(self):
                return None

            def __aiter__(self):
                async def messages():
                    # Deepgram answers after it has audio: hold the result
                    # until the frames (and then the flush) have arrived.
                    for _ in range(200):
                        if len(fake_ws.sent) >= 5:
                            break
                        await asyncio.sleep(0.01)
                    yield json.dumps(
                        {
                            "type": "Results",
                            "is_final": True,
                            "channel": {
                                "alternatives": [
                                    {"transcript": "hello world", "confidence": 0.9}
                                ]
                            },
                        }
                    )
                    for _ in range(200):
                        if len(fake_ws.sent) >= 6:
                            break
                        await asyncio.sleep(0.01)

                return messages()

        class FakeConnect:
            def __init__(self, ws):
                self._ws = ws

            async def __aenter__(self):
                await asyncio.sleep(0.3)  # a slow handshake
                events.append("connected")
                return self._ws

            async def __aexit__(self, *exc):
                return False

        fake_ws = FakeWs()
        fake_module = types.SimpleNamespace(
            connect=lambda url, **kwargs: FakeConnect(fake_ws)
        )

        async def audio():
            for index in range(5):
                events.append(f"pull{index}")
                yield b"\x00\x00" * 320

        original_module = sys.modules.get("websockets")
        original_secret = deepgram.get_secret
        sys.modules["websockets"] = fake_module
        deepgram.get_secret = lambda name: "key"
        try:
            transcripts = []
            async for tr in deepgram.DeepgramStt().stream(audio()):
                transcripts.append(tr)
        finally:
            if original_module is None:
                sys.modules.pop("websockets", None)
            else:
                sys.modules["websockets"] = original_module
            deepgram.get_secret = original_secret

        # The source was drained even though the handshake took 300ms.
        self.assertLess(events.index("pull4"), events.index("connected"))
        self.assertEqual(fake_ws.sent[:5], [b"\x00\x00" * 320] * 5)
        self.assertEqual(json.loads(fake_ws.sent[5])["type"], "CloseStream")
        self.assertEqual([t.text for t in transcripts], ["hello world"])
        self.assertTrue(transcripts[0].final)


class WarmVoiceTests(unittest.TestCase):
    def setUp(self):
        from rau.voice import session as voice_session

        self.voice_session = voice_session
        self._was_warmed = voice_session._WARMED.is_set()
        voice_session._WARMED.clear()

    def tearDown(self):
        if self._was_warmed:
            self.voice_session._WARMED.set()
        else:
            self.voice_session._WARMED.clear()

    def test_a_failed_warm_leaves_the_attempt_unburned(self):
        with mock.patch(
            "rau.voice.tts_stream.warmup", return_value=False
        ) as warmup, mock.patch(
            "rau.providers.registry.chat_for_slot", side_effect=Exception("no key")
        ):
            self.voice_session.warm_voice()
            self.assertTrue(
                _wait_for(lambda: not self.voice_session._WARMED.is_set()),
                "a failed warm kept the only attempt burned",
            )
            self.voice_session.warm_voice()
            self.assertTrue(_wait_for(lambda: warmup.call_count >= 2))

    def test_a_successful_warm_runs_only_once(self):
        provider = types.SimpleNamespace(warm=lambda: None)
        with mock.patch(
            "rau.voice.tts_stream.warmup", return_value=True
        ) as warmup, mock.patch(
            "rau.providers.registry.chat_for_slot", return_value=(provider, "face")
        ):
            self.voice_session.warm_voice()
            self.assertTrue(_wait_for(lambda: warmup.call_count >= 1))
            self.assertTrue(_wait_for(self.voice_session._WARMED.is_set))
            self.voice_session.warm_voice()
            time.sleep(0.05)
            self.assertEqual(warmup.call_count, 1)


if __name__ == "__main__":
    unittest.main()
