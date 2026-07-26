"""
Hesitation fillers are disabled — slow turns wait in silence for the real reply.

These tests pin that fillers never play, and that the reply path still works
when the model is slow or when a turn is interrupted.
"""
import asyncio
import threading
import unittest
from unittest import mock

from rau.voice import session as voice_session


class ReactionTurnTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sent_json = []
        self.sent_audio = []
        self._chat = voice_session.brain.chat_streaming
        self._speak = voice_session.speak_stream
        self._hesitations = voice_session.HESITATIONS_ENABLED
        self._lag = voice_session.PRE_SPEECH_LAG_SEC
        voice_session.PRE_SPEECH_LAG_SEC = 0.02
        # Force the production default so a local toggle cannot soft-pass these.
        voice_session.HESITATIONS_ENABLED = False

    def tearDown(self):
        voice_session.brain.chat_streaming = self._chat
        voice_session.speak_stream = self._speak
        voice_session.HESITATIONS_ENABLED = self._hesitations
        voice_session.PRE_SPEECH_LAG_SEC = self._lag

    async def send_json(self, payload):
        self.sent_json.append(payload)

    async def send_bytes(self, payload):
        self.sent_audio.append(payload)

    def install(self, *, first_token_delay: float):
        """A model that takes `first_token_delay` seconds to say anything."""

        def fake_chat(text, *, on_token, cancel, **_kwargs):
            if cancel.wait(first_token_delay):
                raise voice_session.brain.Cancelled()
            on_token("Here is the answer.")
            return "Here is the answer."

        def fake_speak(tokens, *, on_audio, on_sentence, cancel, **_kwargs):
            for token in tokens:
                if cancel.is_set():
                    return
                on_sentence(token)
                on_audio(b"\x01\x02" * 240)
                yield None

        voice_session.brain.chat_streaming = fake_chat  # type: ignore[assignment]
        voice_session.speak_stream = fake_speak  # type: ignore[assignment]

    async def run_turn(self, text="tell me how the deploy went yesterday"):
        session = voice_session.VoiceSession(self.send_json, self.send_bytes)
        try:
            await session.begin_turn(text)
            turn = session._active_turn
            assert turn is not None and turn.thread is not None
            await asyncio.to_thread(turn.thread.join, 4)
            await asyncio.sleep(0.05)
            return session, turn
        finally:
            await session.close()

    async def test_hesitations_are_disabled(self):
        self.assertFalse(voice_session.HESITATIONS_ENABLED)

    async def test_a_slow_reply_does_not_play_a_filler(self):
        self.install(first_token_delay=0.4)
        with mock.patch(
            "rau.voice.reactions.POOL.audio", return_value=b"\x09\x09" * 120
        ) as audio:
            _, turn = await self.run_turn()
        audio.assert_not_called()
        self.assertNotIn(b"\x09\x09" * 120, self.sent_audio)
        self.assertTrue(self.sent_audio)
        turn.set_played_ms(turn.utterance.total_ms)
        self.assertEqual(turn.heard_text(), "Here is the answer.")

    async def test_a_fast_reply_still_speaks(self):
        self.install(first_token_delay=0.0)
        _, turn = await self.run_turn()
        self.assertTrue(self.sent_audio)
        turn.set_played_ms(turn.utterance.total_ms)
        self.assertEqual(turn.heard_text(), "Here is the answer.")

    async def test_an_interrupted_turn_does_not_speak(self):
        self.install(first_token_delay=2.0)
        session = voice_session.VoiceSession(self.send_json, self.send_bytes)
        try:
            await session.begin_turn("tell me about the deploy yesterday")
            turn = session._active_turn
            assert turn is not None
            await session.stop()
            assert turn.thread is not None
            await asyncio.to_thread(turn.thread.join, 4)
            await asyncio.sleep(0.05)
        finally:
            await session.close()
        self.assertFalse(self.sent_audio)

    async def test_pre_speech_lag_is_short(self):
        self.assertLessEqual(voice_session.PRE_SPEECH_LAG_SEC, 0.05)


if __name__ == "__main__":
    unittest.main()
