"""Regression tests for the subsystem bug-sweep (memory, presence, identity)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DiaryRoleSafetyTests(unittest.TestCase):
    """append_diary's role can come from a tool call argument — it must stay
    a single filename component and never escape the diary day directory."""

    def test_role_cannot_traverse_out_of_diary(self) -> None:
        from rau.memory import store as memory_store

        with tempfile.TemporaryDirectory() as tmp:
            diary = Path(tmp) / "diary"
            with mock.patch.object(memory_store, "DIARY_DIR", diary):
                path = memory_store.append_diary("x/../../../evil", "payload")
                self.assertTrue(path.exists())
                self.assertEqual(path.parent.parent, diary)
                # Nothing landed outside the diary tree.
                self.assertFalse((Path(tmp) / "evil.md").exists())
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["diary"])
                # And the entry is still recallable (flat *.md layout intact).
                self.assertIn("payload", memory_store.read_diary_day())

    def test_role_with_separators_and_excess_length_is_safe(self) -> None:
        from rau.memory import store as memory_store

        with tempfile.TemporaryDirectory() as tmp:
            diary = Path(tmp) / "diary"
            with mock.patch.object(memory_store, "DIARY_DIR", diary):
                path = memory_store.append_diary("a/b\\c:d*e" + "x" * 500, "note body")
                self.assertTrue(path.exists())
                name = path.name
                self.assertNotIn("/", name)
                self.assertNotIn("\\", name)
                self.assertLessEqual(len(name), 255)
                # Normal roles are untouched.
                normal = memory_store.append_diary("task_error", "body")
                self.assertIn("-task_error.md", normal.name)


class LoadPresenceCorruptTests(unittest.TestCase):
    """load_presence runs at hub startup; valid JSON with corrupt field types
    must degrade gracefully instead of raising out of the startup hook."""

    def tearDown(self) -> None:
        from rau import state

        state.update_presence(
            last_user_ts=0.0,
            mood={"label": "idle", "intensity": 0.0, "updated_at": 0.0},
            heartbeat_events=[],
        )

    def _load(self, payload: object) -> dict:
        from rau.heartbeat import presence as presence_mod

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presence.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(presence_mod, "PRESENCE_FILE", path):
                return presence_mod.load_presence()

    def test_non_object_json_is_unreadable_not_fatal(self) -> None:
        result = self._load(["not", "a", "dict"])
        self.assertEqual(result, {"loaded": False, "error": "unreadable"})

    def test_corrupt_field_types_do_not_raise(self) -> None:
        from rau.heartbeat import presence as presence_mod

        result = self._load(
            {
                "last_user_ts": "yesterday",
                "mood": {"label": "happy", "intensity": "high", "updated_at": None},
                "heartbeat_events": [],
            }
        )
        self.assertTrue(result["loaded"])
        mood = presence_mod.get_mood()
        # Corrupt intensity/updated_at fell back to 0.0, and the normal
        # decay-on-load then idles the label. Nothing raised.
        self.assertEqual(mood["intensity"], 0.0)
        self.assertIn(mood["label"], presence_mod.MOOD_LABELS)

    def test_bad_ts_falls_back_to_last_user_at(self) -> None:
        from rau import state

        result = self._load(
            {"last_user_ts": "yesterday", "last_user_at": "2026-01-01T10:00:00"}
        )
        self.assertTrue(result["loaded"])
        self.assertGreater(float(state.presence()["last_user_ts"]), 0)


class BackupSoulTests(unittest.TestCase):
    SOUL = "# Soul\n\nI am Rau. " + "Continuous self. " * 10 + "\n\n## Voice\n"

    def _patched(self, tmp: str):
        from rau.identity import store as identity_store

        root = Path(tmp)
        return identity_store, [
            mock.patch.object(identity_store, "IDENTITY_DIR", root),
            mock.patch.object(identity_store, "SOUL_MD", root / "soul.md"),
            mock.patch.object(identity_store, "SOUL_BAK", root / "soul.bak.md"),
        ]

    def test_vanishing_backup_does_not_crash_prune(self) -> None:
        """A backup that disappears between glob and stat (two soul writes
        pruning at once) must not raise out of backup_soul."""
        with tempfile.TemporaryDirectory() as tmp:
            identity_store, patches = self._patched(tmp)
            for patch in patches:
                patch.start()
            try:
                (Path(tmp) / "soul.md").write_text(self.SOUL, encoding="utf-8")
                # A broken symlink stands in for a file that vanished mid-prune.
                (Path(tmp) / "soul.20000101T000000000000Z.bak.md").symlink_to(
                    Path(tmp) / "gone.md"
                )
                backup = identity_store.backup_soul()
                self.assertIsNotNone(backup)
                self.assertTrue(Path(backup).exists())
            finally:
                for patch in patches:
                    patch.stop()

    def test_prunes_to_thirty_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            identity_store, patches = self._patched(tmp)
            for patch in patches:
                patch.start()
            try:
                (Path(tmp) / "soul.md").write_text(self.SOUL, encoding="utf-8")
                for i in range(35):
                    stale = Path(tmp) / f"soul.20000101T0000{i:04d}Z.bak.md"
                    stale.write_text("old", encoding="utf-8")
                identity_store.backup_soul()
                remaining = list(Path(tmp).glob("soul.*.bak.md"))
                self.assertEqual(len(remaining), 30)
            finally:
                for patch in patches:
                    patch.stop()


if __name__ == "__main__":
    unittest.main()
