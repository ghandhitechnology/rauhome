"""Lived-time awareness: absence phrasing, persistence, session boundary."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FormatAbsenceTests(unittest.TestCase):
    def test_buckets(self) -> None:
        from rau.heartbeat.presence import format_absence

        self.assertEqual(format_absence(10), "just now")
        self.assertEqual(format_absence(60), "about a minute")
        self.assertEqual(format_absence(12 * 60), "12 minutes")
        self.assertEqual(format_absence(70 * 60), "about an hour")
        self.assertEqual(format_absence(5 * 3600), "about 5 hours")
        self.assertEqual(format_absence(24 * 3600), "about a day")
        self.assertEqual(format_absence(3 * 86400), "about 3 days")


class PresencePersistTests(unittest.TestCase):
    def test_save_load_round_trip(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau import state

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presence.json"
            with mock.patch.object(presence_mod, "PRESENCE_FILE", path):
                state.update_presence(last_user_ts=1_700_000_000.0)
                presence_mod.save_presence()
                self.assertTrue(path.exists())
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["last_user_ts"], 1_700_000_000.0)
                self.assertTrue(data["last_user_at"])

                state.update_presence(last_user_ts=0.0)
                loaded = presence_mod.load_presence()
                self.assertTrue(loaded["loaded"])
                self.assertAlmostEqual(
                    float(state.presence()["last_user_ts"]),
                    1_700_000_000.0,
                    places=0,
                )


class SessionBoundaryTests(unittest.TestCase):
    def tearDown(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau.face import brain
        from rau import state

        presence_mod.end_user_turn()
        brain.reset_history()
        state.update_presence(
            last_user_ts=0.0,
            reentry_pending=False,
            reentry_tier="none",
            gap_sec=0.0,
        )

    def test_hard_gap_clears_history_once(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau.face import brain
        from rau.providers.base import Message
        from rau import state

        brain.reset_history()
        brain._append_history(
            Message(role="user", content="old thread"),
            Message(role="assistant", content="still mid-thought"),
        )
        self.assertEqual(len(brain.snapshot_history()), 2)

        # Last contact was 3 hours ago.
        state.update_presence(last_user_ts=time.time() - 3 * 3600)
        gap, tier = presence_mod.begin_user_turn()
        self.assertEqual(tier, "hard")
        self.assertGreater(gap or 0, presence_mod.REENTRY_HARD_SEC)
        self.assertEqual(brain.snapshot_history(), [])

        # Idempotent — second begin does not re-fire.
        brain._append_history(Message(role="user", content="new"))
        gap2, tier2 = presence_mod.begin_user_turn()
        self.assertEqual(tier2, "hard")
        self.assertEqual(len(brain.snapshot_history()), 1)

    def test_system_prompt_includes_now_block(self) -> None:
        from rau.heartbeat import presence as presence_mod
        from rau.face import brain
        from rau import state

        state.update_presence(last_user_ts=time.time() - 40 * 60)
        presence_mod.begin_user_turn()
        with mock.patch.object(brain, "load_soul", return_value="# Soul\nI am Rau."):
            with mock.patch.object(brain, "recent_context", return_value=""):
                prompt = brain._system_prompt()
        self.assertIn("## Now", prompt)
        self.assertIn("Local time:", prompt)
        self.assertIn("Time since you last heard from them:", prompt)
        self.assertIn("pause", prompt.lower())


if __name__ == "__main__":
    unittest.main()
