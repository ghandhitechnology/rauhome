"""Voice-path TTFT helpers: slim tools, voice prompt, first-chunk threshold."""
import unittest

from rau.face import brain
from rau.voice import session as voice_session
from rau.voice.tts_stream import FIRST_MIN_CHARS, MIN_CHARS


class VoiceTtftHelpersTests(unittest.TestCase):
    def test_voice_round_zero_uses_slim_tools(self) -> None:
        names = {
            t["function"]["name"]
            for t in brain._tools_for_turn(
                voice=True, round_idx=0, user_text="how was your day"
            )
        }
        self.assertIn("memory_read", names)
        self.assertIn("browse_web", names)
        self.assertIn("body_choreography", names)
        self.assertNotIn("run_shell", names)
        self.assertNotIn("start_hard_task", names)
        self.assertNotIn("read_file", names)

    def test_voice_deep_work_gets_full_tools(self) -> None:
        names = {
            t["function"]["name"]
            for t in brain._tools_for_turn(
                voice=True, round_idx=0, user_text="please fix this and run a shell check"
            )
        }
        self.assertIn("run_shell", names)
        self.assertIn("start_hard_task", names)

    def test_voice_round_two_expands_tools(self) -> None:
        names = {
            t["function"]["name"]
            for t in brain._tools_for_turn(
                voice=True, round_idx=1, user_text="how was your day"
            )
        }
        self.assertIn("run_shell", names)

    def test_voice_prompt_asks_for_spoken_opener(self) -> None:
        brain.clear_prompt_caches()
        prompt = brain._system_prompt(voice=True)
        self.assertIn("## Voice turn", prompt)
        self.assertIn("Before any tool call", prompt)

    def test_chat_prompt_omits_voice_opener(self) -> None:
        brain.clear_prompt_caches()
        prompt = brain._system_prompt(voice=False)
        self.assertNotIn("## Voice turn", prompt)

    def test_first_chunk_threshold_is_aggressive(self) -> None:
        self.assertLessEqual(FIRST_MIN_CHARS, 8)
        self.assertLess(FIRST_MIN_CHARS, MIN_CHARS)

    def test_pre_speech_lag_and_hesitations(self) -> None:
        self.assertLessEqual(voice_session.PRE_SPEECH_LAG_SEC, 0.05)
        self.assertFalse(voice_session.HESITATIONS_ENABLED)


if __name__ == "__main__":
    unittest.main()
