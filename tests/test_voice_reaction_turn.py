"""
The hesitation inside a real turn.

A filler is decoration in front of the only thing the user asked for, so the
bar is not "does it play" — it is that it cannot damage the reply. It must not
arrive after the answer has started, must not double up, must not survive an
interruption, and must never be remembered as something Rau said.
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
        # Shorter, deterministic waits so the tests do not sit through 450 ms.
        # The pipeline lag moves with it: the two are related, and a config
        # where the hesitation can outrun the pipeline is not a real one.
        self._after = voice_session.REACTION_AFTER_SEC
        self._lag = voice_session.PRE_SPEECH_LAG_SEC
        voice_session.PRE_SPEECH_LAG_SEC = 0.02
        voice_session.REACTION_AFTER_SEC = 0.05

    def tearDown(self):
        voice_session.brain.chat_streaming = self._chat
        voice_session.speak_stream = self._speak
        voice_session.REACTION_AFTER_SEC = self._after
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

    # ── the gap ──────────────────────────────────────────────────────

    async def test_a_slow_reply_is_covered_by_a_hesitation(self):
        self.install(first_token_delay=0.4)
        with mock.patch.object(
            voice_session.reactions.POOL, "audio", return_value=b"\x09\x09" * 120
        ):
            _, turn = await self.run_turn()
        self.assertTrue(turn.reacted)
        # The hesitation reaches the browser before the answer does.
        self.assertEqual(self.sent_audio[0], b"\x09\x09" * 120)
        self.assertGreater(len(self.sent_audio), 1, "the real reply never arrived")

    async def test_a_fast_reply_is_left_alone(self):
        # Covering a gap that does not exist would make Rau slower, not faster.
        self.install(first_token_delay=0.0)
        with mock.patch.object(
            voice_session.reactions.POOL, "audio", return_value=b"\x09\x09" * 120
        ) as audio:
            _, turn = await self.run_turn()
        self.assertNotIn(b"\x09\x09" * 120, self.sent_audio)
        audio.assert_not_called()
        self.assertTrue(self.sent_audio)

    async def test_it_is_never_remembered_as_something_he_said(self):
        self.install(first_token_delay=0.4)
        with mock.patch.object(
            voice_session.reactions.POOL, "audio", return_value=b"\x09\x09" * 120
        ):
            _, turn = await self.run_turn()
        # Played to the end: everything audible should be the reply alone.
        turn.set_played_ms(turn.utterance.total_ms)
        self.assertEqual(turn.heard_text(), "Here is the answer.")

    async def test_the_answer_is_placed_after_the_hesitation_in_the_timeline(self):
        self.install(first_token_delay=0.4)
        with mock.patch.object(
            voice_session.reactions.POOL, "audio", return_value=b"\x09\x09" * 2400
        ):
            _, turn = await self.run_turn()
        spoken = [c for c in turn.utterance.chunks if c.text]
        self.assertTrue(spoken)
        # Captions and barge offsets are measured from here; if the filler did
        # not hold its place, every one of them is early by its duration.
        self.assertGreater(spoken[0].start_ms, 0)

    async def test_only_one_hesitation_per_turn(self):
        self.install(first_token_delay=0.4)
        with mock.patch.object(
            voice_session.reactions.POOL, "audio", return_value=b"\x09\x09" * 120
        ) as audio:
            await self.run_turn()
        self.assertLessEqual(audio.call_count, 1)

    # ── it must not get in the way ───────────────────────────────────

    async def test_an_interrupted_turn_does_not_speak_its_hesitation(self):
        self.install(first_token_delay=2.0)
        started = threading.Event()

        def slow_audio(_text):
            started.set()
            return b"\x09\x09" * 120

        session = voice_session.VoiceSession(self.send_json, self.send_bytes)
        try:
            with mock.patch.object(
                voice_session.reactions.POOL, "audio", side_effect=slow_audio
            ):
                await session.begin_turn("tell me about the deploy yesterday")
                turn = session._active_turn
                assert turn is not None
                # Cut in before the hesitation has had time to be chosen.
                await session.stop()
                assert turn.thread is not None
                await asyncio.to_thread(turn.thread.join, 4)
                await asyncio.sleep(0.05)
        finally:
            await session.close()
        self.assertNotIn(b"\x09\x09" * 120, self.sent_audio)

    async def test_a_failed_pool_costs_the_hesitation_and_nothing_else(self):
        self.install(first_token_delay=0.3)
        with mock.patch.object(
            voice_session.reactions.POOL, "audio", side_effect=RuntimeError("no key")
        ):
            _, turn = await self.run_turn()
        # The reply still lands; the turn simply sounds like it answered fast.
        turn.set_played_ms(turn.utterance.total_ms)
        self.assertEqual(turn.heard_text(), "Here is the answer.")
        self.assertTrue(self.sent_audio)

    async def test_silence_from_the_pool_is_not_sent_as_an_empty_frame(self):
        self.install(first_token_delay=0.3)
        with mock.patch.object(voice_session.reactions.POOL, "audio", return_value=b""):
            _, turn = await self.run_turn()
        self.assertNotIn(b"", self.sent_audio)
        self.assertTrue(all(self.sent_audio))

    async def test_the_family_follows_what_the_user_actually_said(self):
        self.install(first_token_delay=0.3)
        with mock.patch.object(
            voice_session.reactions.POOL, "choose", return_value="Mm-hm."
        ) as choose, mock.patch.object(
            voice_session.reactions.POOL, "audio", return_value=b"\x09\x09" * 120
        ):
            await self.run_turn("thanks")
        choose.assert_called_once_with("acknowledging")


if __name__ == "__main__":
    unittest.main()
