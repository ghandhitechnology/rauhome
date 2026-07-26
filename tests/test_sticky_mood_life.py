"""Sticky mood, speech buffer hesitation, heartbeat private-life events."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class MoodPersistTests(unittest.TestCase):
    def tearDown(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        presence_mod.end_user_turn()
        state.update_presence(
            mood={"label": "idle", "intensity": 0.0, "updated_at": 0.0},
            heartbeat_events=[],
            last_user_ts=0.0,
            reentry_pending=False,
            reentry_tier="none",
            gap_sec=0.0,
        )

    def test_save_load_mood_and_events(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presence.json"
            with mock.patch.object(presence_mod, "PRESENCE_FILE", path):
                now = time.time()
                state.update_presence(
                    last_user_ts=now - 60,
                    mood={
                        "label": "happy",
                        "intensity": 0.8,
                        "updated_at": now,
                    },
                    heartbeat_events=[
                        {
                            "kind": "nudge",
                            "summary": "still here",
                            "ts": now - 30,
                        }
                    ],
                )
                presence_mod.save_presence()
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["mood"]["label"], "happy")
                self.assertEqual(len(data["heartbeat_events"]), 1)

                state.update_presence(
                    mood={"label": "idle", "intensity": 0.0, "updated_at": 0.0},
                    heartbeat_events=[],
                    last_user_ts=0.0,
                )
                presence_mod.load_presence()
                mood = presence_mod.get_mood()
                self.assertEqual(mood["label"], "happy")
                self.assertEqual(len(presence_mod.get_heartbeat_events()), 1)

    def test_decay_toward_idle(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        past = time.time() - presence_mod.MOOD_HALF_LIFE_SEC
        state.update_presence(
            mood={"label": "excited", "intensity": 0.8, "updated_at": past}
        )
        mood = presence_mod.decay_mood()
        # One half-life → ~0.4; still above idle threshold.
        self.assertEqual(mood["label"], "excited")
        self.assertAlmostEqual(mood["intensity"], 0.4, places=1)

        # Far past → idle.
        state.update_presence(
            mood={
                "label": "excited",
                "intensity": 0.8,
                "updated_at": time.time() - 48 * 3600,
            }
        )
        mood = presence_mod.decay_mood()
        self.assertEqual(mood["label"], "idle")
        self.assertLess(mood["intensity"], presence_mod.MOOD_IDLE_THRESHOLD)


class HeartbeatEventsTests(unittest.TestCase):
    def tearDown(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        presence_mod.end_user_turn()
        state.update_presence(
            mood={"label": "idle", "intensity": 0.0, "updated_at": 0.0},
            heartbeat_events=[],
            last_user_ts=0.0,
            reentry_pending=False,
            reentry_tier="none",
            gap_sec=0.0,
        )

    def test_between_sessions_empty_no_invent(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        state.update_presence(last_user_ts=time.time() - 3 * 3600, heartbeat_events=[])
        presence_mod.begin_user_turn()
        block = presence_mod.between_sessions_block()
        self.assertIn("While they were away", block)
        self.assertIn("Do not invent", block)

    def test_between_sessions_lists_real_events(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        last = time.time() - 3 * 3600
        state.update_presence(
            last_user_ts=last,
            heartbeat_events=[
                {
                    "kind": "nudge",
                    "summary": "Hey — I'm still here.",
                    "ts": last + 60,
                }
            ],
        )
        presence_mod.begin_user_turn()
        block = presence_mod.between_sessions_block()
        self.assertIn("Hey — I'm still here.", block)
        self.assertIn("nudge", block)

    def test_end_turn_consumes_events(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        last = time.time() - 3 * 3600
        state.update_presence(
            last_user_ts=last,
            heartbeat_events=[
                {"kind": "nudge", "summary": "ping", "ts": last + 10}
            ],
        )
        presence_mod.begin_user_turn()
        self.assertEqual(len(presence_mod.active_heartbeat_events()), 1)
        with mock.patch.object(presence_mod, "PRESENCE_FILE", Path(tempfile.mkdtemp()) / "p.json"):
            presence_mod.end_user_turn()
        self.assertEqual(presence_mod.get_heartbeat_events(), [])

    def test_append_dedupes_identical(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        state.update_presence(heartbeat_events=[])
        with mock.patch.object(presence_mod, "save_presence"):
            presence_mod.append_heartbeat_event("nudge", "same line")
            presence_mod.append_heartbeat_event("nudge", "same line")
        self.assertEqual(len(presence_mod.get_heartbeat_events()), 1)


class SystemPromptBlocksTests(unittest.TestCase):
    def tearDown(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        presence_mod.end_user_turn()
        state.update_presence(
            last_user_ts=0.0,
            reentry_pending=False,
            reentry_tier="none",
            gap_sec=0.0,
            mood={"label": "idle", "intensity": 0.0, "updated_at": 0.0},
            heartbeat_events=[],
        )

    def test_system_prompt_includes_mood_and_speech(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau.face import brain
        from rau import state

        state.update_presence(
            last_user_ts=time.time() - 40 * 60,
            mood={
                "label": "curious",
                "intensity": 0.6,
                "updated_at": time.time(),
            },
        )
        presence_mod.begin_user_turn()
        with mock.patch.object(brain, "load_soul", return_value="# Soul\nI am Rau."):
            with mock.patch.object(brain, "recent_context", return_value=""):
                prompt = brain._system_prompt()
        self.assertIn("## Mood", prompt)
        self.assertIn("curious", prompt)
        self.assertIn("## Speech habits", prompt)
        self.assertIn("While they were away", prompt)


class SentenceBufferHesitationTests(unittest.TestCase):
    def test_short_ellipsis_flushes(self) -> None:
        from rau.voice.tts_stream import SentenceBuffer

        buf = SentenceBuffer()
        out = buf.push("음…")
        self.assertEqual(out, ["음…"])


if __name__ == "__main__":
    unittest.main()
