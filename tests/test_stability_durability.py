"""Regression tests for the durability sweep (memory, dream, heartbeat,
scheduler): dream day selection + mutual exclusion, scheduler retry wakeup
and timer-pool shutdown, atomic-write directory fsync, and cron skip-ahead.

Run: python -m unittest tests.test_stability_durability -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ==========================================================================
# rau/dream/dreamer.py — right day, retention, mutual exclusion
# ==========================================================================

class DreamDurabilityTests(unittest.TestCase):
    def setUp(self):
        from rau.dream import dreamer

        self.dreamer = dreamer
        dreamer._stop.clear()
        dreamer._timer_state.update(
            last_day="", failure_day="", failures=0, next_retry=0.0
        )

    def tearDown(self):
        self.dreamer._stop.clear()
        self.dreamer._timer_state.update(
            last_day="", failure_day="", failures=0, next_retry=0.0
        )

    def _patched_run(self, diary):
        d = self.dreamer
        provider = mock.Mock()
        provider.chat.return_value = mock.Mock(
            content="daily log\n<<<SOUL>>>\n# Soul\n\nbody\n"
        )
        return (
            mock.patch.object(d, "read_diary_day", return_value=diary),
            mock.patch.object(d, "load_settings", return_value={"trace_ttl_days": 7}),
            mock.patch.object(d, "purge_old_traces"),
            mock.patch.object(d, "chat_for_slot", return_value=(provider, {})),
            mock.patch.object(d, "write_daily_log"),
            mock.patch.object(d.identity_store, "write_soul"),
            mock.patch.object(d.identity_store, "read_text", return_value=""),
            mock.patch.object(d.identity_store, "load_soul", return_value=""),
            mock.patch.object(d.BUS, "emit"),
        )

    def test_scheduled_tick_compacts_yesterday_not_today(self):
        # The 02:00-05:00 window opens just after midnight: the dream must
        # compact the day that ended, not the near-empty diary of the day
        # that just started.
        d = self.dreamer
        ran = []

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 27, 3, 0)

        with mock.patch.object(d, "datetime", FakeDatetime), \
             mock.patch.object(d, "load_settings",
                               return_value={"dream_window_start": "02:00",
                                             "dream_window_end": "05:00"}), \
             mock.patch.object(d, "should_defer", return_value=False), \
             mock.patch.object(d, "run_dream",
                               side_effect=lambda day=None: ran.append(day) or {"ok": True}):
            d._dream_tick()

        self.assertEqual(ran, ["2026-07-26"])
        # The latch keys on the COMPACTED day, not the fire-day: keying on
        # the fire-day let a manual run at 23:00 and the 02:00 tick compact
        # the same day twice.
        self.assertEqual(d._timer_state["last_day"], "2026-07-26")

    def test_empty_diary_still_purges_old_traces(self):
        # BUG: the empty-diary early return skipped purge_old_traces, so
        # traces grew without bound on quiet days.
        d = self.dreamer
        with mock.patch.object(d, "read_diary_day", return_value=""), \
             mock.patch.object(d, "load_settings", return_value={"trace_ttl_days": 9}), \
             mock.patch.object(d, "purge_old_traces") as purge, \
             mock.patch.object(d, "chat_for_slot") as chat:
            result = d.run_dream("2026-07-26")
        self.assertTrue(result["skipped"])
        purge.assert_called_once_with(9)
        chat.assert_not_called()

    def test_run_dream_is_mutually_exclusive(self):
        # A manual /api/dream/run racing the scheduler tick must not double
        # the paid provider call or the soul rewrite.
        d = self.dreamer
        d._run_lock.acquire()
        try:
            self.assertEqual(d.run_dream(), {"status": "already_running"})
        finally:
            d._run_lock.release()

    def test_successful_manual_run_satisfies_tonights_scheduled_dream(self):
        # Corrected contract: the latch keys on the COMPACTED day. A manual
        # run compacts today, so the post-midnight tick — which compacts
        # that same day as "yesterday" — must not spend a second paid call.
        d = self.dreamer
        today = datetime.now().strftime("%Y-%m-%d")
        patches = self._patched_run("dear diary")
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8]:
            result = d.run_dream()
        self.assertTrue(result["ok"])
        self.assertEqual(result["day"], today)
        self.assertEqual(d._timer_state["last_day"], today)

        tomorrow = datetime.now() + timedelta(days=1)

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(tomorrow.year, tomorrow.month, tomorrow.day, 3, 0)

        with mock.patch.object(d, "datetime", FakeDatetime), \
             mock.patch.object(d, "load_settings", return_value={}), \
             mock.patch.object(d, "should_defer", return_value=False), \
             mock.patch.object(d, "run_dream") as tick_run:
            d._dream_tick()
        tick_run.assert_not_called()

    def test_manual_run_after_midnight_does_not_suppress_tick_for_yesterday(self):
        # Regression (b): a manual run at 00:30 compacts the day that just
        # started. Keyed on the fire-day, that suppressed the 02:00 tick and
        # yesterday's daily log was never written. Keyed on the compacted
        # day, the tick still compacts yesterday.
        d = self.dreamer

        class AfterMidnight(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 27, 0, 30)

        patches = self._patched_run("dear diary")
        with mock.patch.object(d, "datetime", AfterMidnight), \
             patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8]:
            result = d.run_dream()
        self.assertTrue(result["ok"])
        self.assertEqual(result["day"], "2026-07-27")
        self.assertEqual(d._timer_state["last_day"], "2026-07-27")

        ran = []

        class TickTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 27, 3, 0)

        with mock.patch.object(d, "datetime", TickTime), \
             mock.patch.object(d, "load_settings",
                               return_value={"dream_window_start": "02:00",
                                             "dream_window_end": "05:00"}), \
             mock.patch.object(d, "should_defer", return_value=False), \
             mock.patch.object(d, "run_dream",
                               side_effect=lambda day=None: ran.append(day) or {"ok": True}):
            d._dream_tick()

        self.assertEqual(ran, ["2026-07-26"])
        self.assertEqual(d._timer_state["last_day"], "2026-07-26")

    def test_tick_does_not_latch_on_already_running_or_stopped(self):
        # Regression (c): the tick used to set last_day unconditionally, so
        # an already_running/stopped result latched a compaction that never
        # happened. The latch must only move when the dream actually ran.
        d = self.dreamer

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 27, 3, 0)

        for refused in ({"status": "already_running"},
                        {"ok": False, "status": "stopped"}):
            with mock.patch.object(d, "datetime", FakeDatetime), \
                 mock.patch.object(d, "load_settings",
                                   return_value={"dream_window_start": "02:00",
                                                 "dream_window_end": "05:00"}), \
                 mock.patch.object(d, "should_defer", return_value=False), \
                 mock.patch.object(d, "run_dream", return_value=refused):
                d._dream_tick()
            self.assertEqual(d._timer_state["last_day"], "")
            self.assertEqual(d._timer_state["failures"], 0)

        # Once the contention clears, the same tick runs and latches.
        with mock.patch.object(d, "datetime", FakeDatetime), \
             mock.patch.object(d, "load_settings",
                               return_value={"dream_window_start": "02:00",
                                             "dream_window_end": "05:00"}), \
             mock.patch.object(d, "should_defer", return_value=False), \
             mock.patch.object(d, "run_dream", return_value={"ok": True}):
            d._dream_tick()
        self.assertEqual(d._timer_state["last_day"], "2026-07-26")

    def test_scheduled_run_marks_no_last_day_inside_run_dream(self):
        # The tick owns the once-per-night latch; run_dream only marks it
        # for the manual path.
        d = self.dreamer
        patches = self._patched_run("dear diary")
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], patches[8]:
            result = d.run_dream("2026-07-26")
        self.assertTrue(result["ok"])
        self.assertEqual(d._timer_state["last_day"], "")

    def test_stopped_dreamer_refuses_to_start_a_dream(self):
        d = self.dreamer
        d._stop.set()
        self.assertEqual(d.run_dream(), {"ok": False, "status": "stopped"})


# ==========================================================================
# rau/scheduler/service.py — retry wakeup, pool shutdown, retention prune
# ==========================================================================

class SchedulerDurabilityTests(unittest.TestCase):
    def setUp(self):
        from rau.control.store import ControlStore
        from rau.scheduler.service import SchedulerService

        self.tmp = tempfile.TemporaryDirectory(prefix="rau-durability-")
        self.store = ControlStore(Path(self.tmp.name) / "control.db")
        self.store.initialize()
        self.scheduler = SchedulerService(self.store)
        # Inspect durable semantics without starting a real provider worker.
        self.scheduler._dispatch_queued = lambda: None

    def tearDown(self):
        self.scheduler.stop()
        self.tmp.cleanup()

    def _schedule_and_run(self, name):
        schedule = self.scheduler.create(
            {
                "name": name,
                "goal": "do a thing",
                "trigger": {
                    "kind": "interval",
                    "seconds": 3600,
                    "anchor": time.time() + 3600,
                },
            }
        )
        return self.scheduler.run_now(schedule["id"])

    def test_loop_wakeup_honors_earliest_queued_retry_at(self):
        # BUG: after a 30s backoff requeue the loop could sleep the full 60s
        # cap — queued retry_at was never part of the timeout computation.
        later = time.time() + 120
        sooner = time.time() + 30
        first = self._schedule_and_run("first")
        self.assertIsNone(self.scheduler._next_queued_retry_at())
        self.store.update_schedule_run(first["id"], state="queued", retry_at=later)
        self.assertEqual(self.scheduler._next_queued_retry_at(), later)
        second = self._schedule_and_run("second")
        self.store.update_schedule_run(second["id"], state="queued", retry_at=sooner)
        self.assertEqual(self.scheduler._next_queued_retry_at(), sooner)

    def test_stop_shuts_down_timer_pool_and_start_recreates_it(self):
        fired = threading.Event()
        self.scheduler.register_timer(
            "probe", fired.set, interval_sec=1.0, initial_delay_sec=0.0
        )
        self.scheduler.stop()
        self.assertTrue(self.scheduler._timer_pool_stopped)
        with self.assertRaises(RuntimeError):
            self.scheduler._timer_pool.submit(lambda: None)

        self.scheduler.start()
        self.assertFalse(self.scheduler._timer_pool_stopped)
        self.scheduler.tick(now=time.time() + 2)
        self.assertTrue(fired.wait(timeout=5))
        self.scheduler.stop()

    def test_activity_retention_also_prunes_control_store_when_available(self):
        calls = []
        self.store.prune = lambda cutoff: calls.append(cutoff)
        with mock.patch("rau.activity.ACTIVITY") as activity:
            self.scheduler._run_activity_retention()
        activity.purge.assert_called_once_with(retention_days=7)
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0], time.time() - 7 * 86_400, delta=5)


# ==========================================================================
# atomic writes — directory fsync + stale tmp reclaim
# ==========================================================================

class AtomicWriteTests(unittest.TestCase):
    def _counting_fsync(self):
        fsyncs = []
        real_fsync = os.fsync

        def counting(fd):
            fsyncs.append(fd)
            return real_fsync(fd)

        return fsyncs, counting

    def _stale_tmp(self, target, name, age_sec):
        stale = target.parent / f".{target.name}.{name}.tmp"
        stale.write_text("orphan", encoding="utf-8")
        old = time.time() - age_sec
        os.utime(stale, (old, old))
        return stale

    def test_memory_atomic_text_fsyncs_directory_and_sweeps_stale_tmp(self):
        from rau.memory import store as memory_store

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            stale = self._stale_tmp(target, "deadbeef", 3600)
            fresh = self._stale_tmp(target, "inflight", 0)
            fsyncs, counting = self._counting_fsync()
            with mock.patch.object(memory_store.os, "fsync", counting):
                memory_store._atomic_text(target, "hello")

            self.assertEqual(target.read_text(encoding="utf-8"), "hello")
            # One fsync for the file, one for the parent directory.
            self.assertGreaterEqual(len(fsyncs), 2)
            self.assertFalse(stale.exists())  # crash orphan reclaimed
            self.assertTrue(fresh.exists())   # in-flight tmp untouched

    def test_identity_write_text_fsyncs_directory_and_sweeps_stale_tmp(self):
        from rau.identity import store as identity_store

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "soul.md"
            stale = self._stale_tmp(target, "deadbeef", 3600)
            fsyncs, counting = self._counting_fsync()
            with mock.patch.object(identity_store.os, "fsync", counting):
                identity_store.write_text(target, "# Soul\n\nbody")

            self.assertEqual(target.read_text(encoding="utf-8"), "# Soul\n\nbody\n")
            self.assertGreaterEqual(len(fsyncs), 2)
            self.assertFalse(stale.exists())

    def test_save_presence_fsyncs_directory_and_sweeps_stale_tmp(self):
        from rau.heartbeat import presence as presence_mod

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presence.json"
            stale = self._stale_tmp(path, "deadbeef", 3600)
            fsyncs, counting = self._counting_fsync()
            with mock.patch.object(presence_mod, "PRESENCE_FILE", path), \
                 mock.patch.object(presence_mod.os, "fsync", counting):
                presence_mod.save_presence()

            self.assertTrue(path.exists())
            self.assertGreaterEqual(len(fsyncs), 2)
            self.assertFalse(stale.exists())


# ==========================================================================
# rau/scheduler/cron.py — skip-ahead next_after
# ==========================================================================

class CronSkipAheadTests(unittest.TestCase):
    def test_sparse_feb29_cron_does_not_minute_step(self):
        from rau.scheduler.cron import CronSpec

        spec = CronSpec.parse("0 0 29 2 *")
        start = datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()
        calls = 0
        real_matches = CronSpec.matches

        def counting_matches(self, local):
            nonlocal calls
            calls += 1
            return real_matches(self, local)

        with mock.patch.object(CronSpec, "matches", counting_matches):
            occurrence = spec.next_after(start, "UTC")

        local = datetime.fromtimestamp(occurrence, tz=timezone.utc)
        self.assertEqual(
            (local.year, local.month, local.day, local.hour, local.minute),
            (2028, 2, 29, 0, 0),
        )
        # Minute-stepping would need ~4.3M probes for the same answer.
        self.assertLess(calls, 5000)

    def test_restricted_hours_skip_without_losing_matches(self):
        from rau.scheduler.cron import CronSpec

        spec = CronSpec.parse("30 1 * * *")
        start = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc).timestamp()
        occurrence = spec.next_after(start, "Asia/Seoul")
        local = datetime.fromtimestamp(occurrence, tz=timezone.utc).astimezone(
            ZoneInfo("Asia/Seoul")
        )
        self.assertEqual((local.hour, local.minute), (1, 30))
        self.assertEqual((local.month, local.day), (7, 28))

    def test_dense_cron_still_fires_every_minute(self):
        from rau.scheduler.cron import CronSpec

        spec = CronSpec.parse("* * * * *")
        start = datetime(2026, 7, 27, 12, 34, 56, tzinfo=timezone.utc).timestamp()
        occurrence = spec.next_after(start, "UTC")
        self.assertEqual(occurrence, float(int(start // 60) * 60 + 60))

    def test_posix_dom_dow_or_semantics_survive_day_skipping(self):
        from rau.scheduler.cron import CronSpec

        spec = CronSpec.parse("0 9 1 * 1")  # 09:00 on the 1st AND on Mondays
        monday = datetime(2026, 7, 27, 8, 59, tzinfo=timezone.utc).timestamp()
        occurrence = spec.next_after(monday, "UTC")
        # Monday matches via day-of-week even though the 27th is not the 1st.
        self.assertEqual(
            occurrence,
            datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc).timestamp(),
        )
        following = spec.next_after(occurrence, "UTC")
        # The 1st matches via day-of-month before the next Monday (Aug 3).
        self.assertEqual(
            following,
            datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc).timestamp(),
        )


if __name__ == "__main__":
    unittest.main()
