"""Focused regressions for voice/audio and hub concurrency hardening."""
from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class EventAndStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_emit_from_worker_wakes_async_subscriber(self) -> None:
        from rau.events import EventBus

        bus = EventBus()
        queue = bus.subscribe_async()
        worker = threading.Thread(target=lambda: bus.emit("ready", value=7))
        worker.start()
        worker.join()

        event = await asyncio.wait_for(queue.get(), timeout=1)
        self.assertEqual(event["kind"], "ready")
        self.assertEqual(event["value"], 7)
        bus.unsubscribe_async(queue)

    async def test_event_queue_is_bounded_and_keeps_recent_events(self) -> None:
        from rau.events import ASYNC_QUEUE_SIZE, EventBus

        bus = EventBus(history=500)
        queue = bus.subscribe_async()
        for index in range(ASYNC_QUEUE_SIZE + 20):
            bus.emit("tick", index=index)
        await asyncio.sleep(0)

        self.assertEqual(queue.qsize(), ASYNC_QUEUE_SIZE)
        newest = None
        while not queue.empty():
            newest = queue.get_nowait()
        assert newest is not None
        self.assertEqual(newest["index"], ASYNC_QUEUE_SIZE + 19)
        bus.unsubscribe_async(queue)

    async def test_browser_voice_lease_restores_only_after_last_socket(self) -> None:
        from rau import state

        state.set_listening(True)
        state.acquire_browser_voice()
        state.acquire_browser_voice()
        self.assertFalse(state.status_snapshot()["listening"])

        state.release_browser_voice()
        self.assertFalse(state.status_snapshot()["listening"])
        state.release_browser_voice()
        self.assertTrue(state.status_snapshot()["listening"])


class HistoryIsolationTests(unittest.TestCase):
    def test_interruption_rewrites_its_exact_turn_not_the_newest_reply(self) -> None:
        from rau.face import brain

        original_diary = brain.append_diary
        brain.append_diary = lambda *args, **kwargs: None
        try:
            brain.reset_history()
            first, _ = brain._reserve_stream_turn("first question")
            second, _ = brain._reserve_stream_turn("follow-up")
            brain._finish_stream_turn(second, "newest answer")

            cancelled = brain.Cancelled(first, "generated words", "first question")
            brain.finish_interrupted_turn(cancelled, "heard words")
            messages = brain.snapshot_history()
        finally:
            brain.append_diary = original_diary
            brain.reset_history()

        content = [(message.role, message.content) for message in messages]
        self.assertIn(("assistant", "heard words"), content)
        self.assertIn(("assistant", "newest answer"), content)
        self.assertLess(
            content.index(("assistant", "heard words")),
            content.index(("assistant", "newest answer")),
        )

    def test_immediate_voice_reply_defers_diary_until_playback_outcome(self) -> None:
        from rau.face import brain

        diary = []
        original_diary = brain.append_diary
        brain.append_diary = lambda role, text: diary.append((role, text))
        try:
            reply = brain.chat_streaming(
                "/skills",
                on_token=lambda _token: None,
                defer_diary=True,
            )
            self.assertIsInstance(reply, brain.StreamingReply)
            assert isinstance(reply, brain.StreamingReply)
            self.assertEqual(diary, [])
            brain.finish_interrupted_turn(reply, "audible part")
        finally:
            brain.append_diary = original_diary

        self.assertEqual(
            diary,
            [("user", "/skills"), ("rau", "audible part")],
        )


class BufferedSttTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_incomplete_pcm_samples(self) -> None:
        from rau.voice.stt.buffered import BufferedStt

        class FakeBuffered(BufferedStt):
            def transcribe(self, pcm: bytes) -> str:
                return "unused"

        async def frames():
            yield b"\x00"

        with self.assertRaisesRegex(ValueError, "PCM16"):
            async for _ in FakeBuffered().stream(frames()):
                pass


class VoiceSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_turn_starts_cancel_the_orphan_and_publish_one_active_turn(self) -> None:
        from rau.voice import session as voice_session

        async def send_json(_payload):
            return None

        async def send_bytes(_payload):
            return None

        session = voice_session.VoiceSession(send_json, send_bytes)
        observed = []

        def hold(turn):
            observed.append(turn)
            turn.cancel.wait(0.5)

        session._turn_body = hold  # type: ignore[method-assign]
        try:
            await asyncio.gather(session.begin_turn("first"), session.begin_turn("second"))
            await asyncio.sleep(0.02)
            active = session._active_turn
            self.assertIsNotNone(active)
            assert active is not None
            self.assertEqual(active.text, "second")
            first = next(turn for turn in observed if turn.text == "first")
            self.assertTrue(first.cancel.is_set())
        finally:
            await session.close()

    async def test_invalidated_stt_epoch_cannot_start_a_turn(self) -> None:
        from rau.voice import session as voice_session
        from rau.voice.stt.base import Transcript

        async def send_json(_payload):
            return None

        async def send_bytes(_payload):
            return None

        class FinalStt:
            async def stream(self, audio):
                async for _ in audio:
                    pass
                yield Transcript("too late", final=True)

            async def close(self):
                return None

        original_factory = voice_session.get_stt_provider
        voice_session.get_stt_provider = FinalStt
        session = voice_session.VoiceSession(send_json, send_bytes)
        turns = []
        session.begin_turn = lambda text: turns.append(text)  # type: ignore[method-assign]
        mic = voice_session._MicStream(asyncio.Queue())
        mic.queue.put_nowait(None)
        session._stt_epoch = 2
        try:
            await session._run_stt(mic, 1)
        finally:
            await session.close()
            voice_session.get_stt_provider = original_factory
        self.assertEqual(turns, [])

    async def test_stt_accumulates_final_segments_and_closes_provider(self) -> None:
        from rau.voice import session as voice_session
        from rau.voice.stt.base import Transcript

        sent = []

        async def send_json(payload):
            sent.append(payload)

        async def send_bytes(_payload):
            return None

        class SegmentedStt:
            closed = False

            async def stream(self, audio):
                async for _ in audio:
                    pass
                yield Transcript("hello", final=True)
                yield Transcript("world", final=True)

            async def close(self):
                self.closed = True

        provider = SegmentedStt()
        original_factory = voice_session.get_stt_provider
        voice_session.get_stt_provider = lambda: provider
        session = voice_session.VoiceSession(send_json, send_bytes)
        turns = []

        async def capture_turn(text):
            turns.append(text)

        session.begin_turn = capture_turn  # type: ignore[method-assign]
        try:
            await session.speech_start()
            task = session._stt_task
            assert task is not None
            self.assertIsNone(session.feed(b"\x00\x00" * 1600))
            await session.speech_end()
            await asyncio.wait_for(task, timeout=1)
        finally:
            await session.close()
            voice_session.get_stt_provider = original_factory

        self.assertTrue(provider.closed)
        self.assertEqual(turns, ["hello world"])
        finals = [message for message in sent if message.get("t") == "final"]
        self.assertEqual(finals[-1]["text"], "hello world")

    async def test_preempted_turn_cannot_emit_stale_audio_or_text(self) -> None:
        from rau.voice import session as voice_session

        sent_json = []
        sent_audio = []

        async def send_json(payload):
            sent_json.append(payload)

        async def send_bytes(payload):
            sent_audio.append(payload)

        first_started = threading.Event()
        original_chat = voice_session.brain.chat_streaming
        original_speak = voice_session.speak_stream

        def fake_chat(text, *, on_token, cancel, **_kwargs):
            if text == "first":
                first_started.set()
                cancel.wait(1)
                # Simulate a provider delivering one late chunk after cancel.
                on_token("stale.")
                raise voice_session.brain.Cancelled()
            on_token("fresh.")
            return "fresh."

        def fake_speak(tokens, *, on_audio, on_sentence, cancel, **_kwargs):
            for token in tokens:
                if cancel.is_set():
                    return
                on_sentence(token)
                on_audio(b"\x00\x00" * 24)
                yield None

        voice_session.brain.chat_streaming = fake_chat  # type: ignore[assignment]
        voice_session.speak_stream = fake_speak  # type: ignore[assignment]
        session = voice_session.VoiceSession(send_json, send_bytes)
        try:
            await session.begin_turn("first")
            self.assertTrue(await asyncio.to_thread(first_started.wait, 1))
            await session.begin_turn("second")
            turn = session._active_turn
            assert turn is not None and turn.thread is not None
            await asyncio.to_thread(turn.thread.join, 2)
            await asyncio.sleep(0.05)
        finally:
            await session.close()
            voice_session.brain.chat_streaming = original_chat
            voice_session.speak_stream = original_speak

        spoken = [item.get("text") for item in sent_json if item.get("t") == "say"]
        self.assertNotIn("stale.", spoken)
        self.assertIn("fresh.", spoken)
        self.assertEqual(len(sent_audio), 1)

    async def test_stop_while_idle_does_not_reclassify_completed_turn(self) -> None:
        from rau.voice import session as voice_session

        async def send_json(_payload):
            return None

        async def send_bytes(_payload):
            return None

        session = voice_session.VoiceSession(send_json, send_bytes)
        completed = voice_session._Turn(1, "done")
        session._active_turn = completed
        session.phase = "idle"
        await session.stop()
        self.assertFalse(completed.cancel.is_set())
        await session.close()

    async def test_malformed_and_oversized_audio_is_rejected(self) -> None:
        from rau.voice import session as voice_session

        async def send_json(_payload):
            return None

        async def send_bytes(_payload):
            return None

        class WaitingStt:
            async def stream(self, audio):
                async for _ in audio:
                    pass
                if False:
                    yield None

            async def close(self):
                return None

        original_factory = voice_session.get_stt_provider
        voice_session.get_stt_provider = WaitingStt
        session = voice_session.VoiceSession(send_json, send_bytes)
        try:
            await session.speech_start()
            malformed = session.feed(b"\x00")
            assert malformed is not None
            self.assertIn("PCM16", malformed)
            oversized = session.feed(
                b"\x00\x00" * (voice_session.MAX_MIC_FRAME_BYTES // 2 + 1)
            )
            assert oversized is not None
            self.assertIn(
                "too large",
                oversized,
            )
        finally:
            await session.close()
            voice_session.get_stt_provider = original_factory


class TtsCleanupTests(unittest.TestCase):
    def test_cancel_closes_provider_stream(self) -> None:
        from rau.voice.tts_stream import synth_sentence

        class Stream:
            def __init__(self):
                self.closed = False

            def __iter__(self):
                yield b"\x00\x00"
                yield b"\x00\x00"

            def close(self):
                self.closed = True

        stream = Stream()

        class TextToSpeech:
            def stream(self, **_kwargs):
                return stream

        class Client:
            text_to_speech = TextToSpeech()

        cancel = threading.Event()
        audio = synth_sentence(
            "hello",
            client=Client(),
            voice_id="voice",
            model="model",
            cancel=cancel,
        )
        self.assertEqual(next(audio), b"\x00\x00")
        cancel.set()
        self.assertEqual(list(audio), [])
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
