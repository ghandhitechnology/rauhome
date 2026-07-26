"""Regressions for bugs found in the voice layer bug sweep."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class SpeechStartTurnRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_committed_while_speech_start_waits_is_still_cancelled(self):
        """
        The STT tail commits its final transcript (and starts the reply turn)
        while holding the commit lock. A speech_start that arrives in that
        window blocks inside stop_stt, so a turn-check done before stop_stt
        misses the new turn — and the reply then talks over the user.
        """
        from rau.voice import session as voice_session
        from rau.voice.stt.base import Transcript

        sent_json = []
        final_sending = asyncio.Event()
        release_final = asyncio.Event()

        async def send_json(payload):
            sent_json.append(payload)
            if payload.get("t") == "final":
                # Freeze the STT tail inside the commit lock, just before it
                # calls begin_turn.
                final_sending.set()
                await release_final.wait()

        async def send_bytes(_payload):
            return None

        class OneShotStt:
            calls = 0

            async def stream(self, audio):
                OneShotStt.calls += 1
                first = OneShotStt.calls == 1
                async for _ in audio:
                    pass
                if first:
                    yield Transcript("the question", final=True)

            async def close(self):
                return None

        def fake_chat(text, *, on_token, cancel, **_kwargs):
            cancel.wait(1.0)
            return ""

        original_factory = voice_session.get_stt_provider
        original_chat = voice_session.brain.chat_streaming
        voice_session.get_stt_provider = OneShotStt
        voice_session.brain.chat_streaming = fake_chat  # type: ignore[assignment]
        session = voice_session.VoiceSession(send_json, send_bytes)
        try:
            await session.speech_start()
            self.assertIsNone(session.feed(b"\x00\x00" * 1600))
            await session.speech_end()
            # The tail now holds the commit lock, blocked sending the final.
            await asyncio.wait_for(final_sending.wait(), timeout=1)
            # The user starts talking again at exactly that moment.
            followup = asyncio.create_task(session.speech_start())
            await asyncio.sleep(0.05)  # let followup reach the commit lock
            release_final.set()
            await asyncio.wait_for(followup, timeout=2)

            turn = session._active_turn
            assert turn is not None
            self.assertTrue(
                turn.cancel.is_set(),
                "a turn committed during stop_stt survived speech_start and "
                "would talk over the user's new utterance",
            )
            self.assertTrue(
                any(p.get("t") == "cancelled" for p in sent_json),
                "the client was never told the committed turn was cancelled",
            )
        finally:
            release_final.set()
            await session.close()
            voice_session.get_stt_provider = original_factory
            voice_session.brain.chat_streaming = original_chat

    async def test_speech_start_still_cancels_a_normally_active_reply(self):
        """The reorder must not break the plain barge fallback."""
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

        def fake_chat(text, *, on_token, cancel, **_kwargs):
            cancel.wait(1.0)
            return ""

        original_factory = voice_session.get_stt_provider
        original_chat = voice_session.brain.chat_streaming
        voice_session.get_stt_provider = WaitingStt
        voice_session.brain.chat_streaming = fake_chat  # type: ignore[assignment]
        session = voice_session.VoiceSession(send_json, send_bytes)
        try:
            await session.begin_turn("hello there, how are you today?")
            turn = session._active_turn
            assert turn is not None
            self.assertEqual(session.phase, "thinking")
            await session.speech_start()
            self.assertTrue(turn.cancel.is_set())
            self.assertEqual(session.phase, "listening")
        finally:
            await session.close()
            voice_session.get_stt_provider = original_factory
            voice_session.brain.chat_streaming = original_chat


class ReactionFailureCacheTests(unittest.TestCase):
    def test_a_failed_synthesis_is_not_memoised_as_silence(self):
        """
        A transient failure returns silence for that turn, but caching the
        empty result would disable the hesitation for the rest of the process
        — warm() only runs once, so one network blip would be permanent.
        """
        from rau.voice import reactions
        from rau.voice.reactions import ReactionPool

        pool = ReactionPool(seed=1)
        with mock.patch.object(
            ReactionPool, "_current_voice", return_value=reactions._Voice("v", "m", "none")
        ), mock.patch.object(
            ReactionPool, "_load_from_disk", return_value=None
        ), mock.patch.object(ReactionPool, "_save_to_disk"), mock.patch.object(
            ReactionPool, "_synthesise", side_effect=[b"", b"\x01\x02"]
        ) as synth:
            self.assertEqual(pool.audio("Hmm."), b"")
            self.assertEqual(pool.audio("Hmm."), b"\x01\x02")
        self.assertEqual(synth.call_count, 2, "the transient failure was cached")

    def test_a_successful_synthesis_is_still_cached(self):
        from rau.voice import reactions
        from rau.voice.reactions import ReactionPool

        pool = ReactionPool(seed=1)
        with mock.patch.object(
            ReactionPool, "_current_voice", return_value=reactions._Voice("v", "m", "none")
        ), mock.patch.object(
            ReactionPool, "_load_from_disk", return_value=None
        ), mock.patch.object(ReactionPool, "_save_to_disk"), mock.patch.object(
            ReactionPool, "_synthesise", return_value=b"\x01\x02"
        ) as synth:
            self.assertEqual(pool.audio("Hmm."), b"\x01\x02")
            self.assertEqual(pool.audio("Hmm."), b"\x01\x02")
        self.assertEqual(synth.call_count, 1)


if __name__ == "__main__":
    unittest.main()
