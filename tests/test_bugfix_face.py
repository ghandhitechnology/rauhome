"""
Regression tests for the face bug-sweep.

Covers: a browse activity that must be closed even when the backend cannot
search (or he stands at the desk until the watchdog), `record_speech` bailing
out when the capture pump dies mid-record instead of parking forever, the
`list_panels(0)` neg-zero slice, and a NaN/inf `hold_ms` coming back as a
structured plan error rather than killing the turn.

Run: python -m unittest tests.test_bugfix_face -v
"""
from __future__ import annotations

import math
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.control.store import control_store  # noqa: E402
from rau.events import BUS  # noqa: E402
from rau.face import choreography, panels, pipeline, web  # noqa: E402


class Recorder:
    """Collect bus events for the duration of a test."""

    def __init__(self, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if not self._kinds or event.get("kind") in self._kinds:
            self.events.append(event)

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]

    def stop(self) -> None:
        with BUS._lock:  # noqa: SLF001 — the bus has no public detach
            BUS._subs["*"] = [fn for fn in BUS._subs["*"] if fn is not self._append]


class BrowseActivityTests(unittest.TestCase):
    class FakeBrowser:
        can_search = False
        label = "Fake"

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def setUp(self) -> None:
        self._get_browser = web.get_browser
        self._resolve_browse = web.resolve_browse
        self.browser = self.FakeBrowser()
        web.get_browser = lambda: ("fake", self.browser)
        web.resolve_browse = lambda: ("fake", {"can_search": False})

    def tearDown(self) -> None:
        web.get_browser = self._get_browser
        web.resolve_browse = self._resolve_browse

    def test_an_unsupported_search_still_closes_the_desk_visit(self) -> None:
        recorder = Recorder("browse_started", "browse_finished")
        try:
            result = web.browse_web({"query": "anything at all"})
        finally:
            recorder.stop()

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["code"], "unsupported")

        started = recorder.of("browse_started")
        finished = recorder.of("browse_finished")
        self.assertEqual(len(started), 1)
        # The renderer holds him at the desk until this lands; without it the
        # only way back is the 90-second watchdog.
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0]["activity_id"], started[0]["activity_id"])
        self.assertFalse(finished[0]["ok"])
        self.assertTrue(self.browser.closed)


class _AliveThread:
    def is_alive(self) -> bool:
        return True


class FakeCapture:
    """A capture whose pump answers whatever frames it was loaded with."""

    def __init__(self, frames: Optional[List[bytes]] = None) -> None:
        self.thread = _AliveThread()
        self.frames = list(frames or [])
        self.reads = 0
        self.on_read = None

    def flush(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self, timeout: float = 1.0) -> bytes:
        self.reads += 1
        if self.on_read is not None:
            self.on_read()
        if self.frames:
            return self.frames.pop(0)
        return b""


class RecordSpeechTests(unittest.TestCase):
    def setUp(self) -> None:
        self._capture = pipeline._audio_capture  # noqa: SLF001 — the fixture point
        self._stop_was_set = pipeline._stop.is_set()

    def tearDown(self) -> None:
        pipeline._audio_capture = self._capture
        if not self._stop_was_set:
            pipeline._stop.clear()

    def install(self, capture: FakeCapture) -> None:
        pipeline._audio_capture = capture

    def test_a_dead_capture_ends_the_recording_instead_of_parking_it(self) -> None:
        # The pump thread is gone (ffmpeg exited), so read() only ever times
        # out. Before the fix this loop never advanced `frames` again and the
        # voice pipeline hung here for the rest of the process.
        capture = FakeCapture()
        self.install(capture)

        outcome: Dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["audio"] = pipeline.record_speech(local_vad=False)
            except Exception as exc:  # noqa: BLE001 — reported by the assert
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout=5)
        if worker.is_alive():
            # Let the spinning thread out before failing, so the suite can
            # continue against the old code.
            pipeline._stop.set()
            worker.join(timeout=5)
            self.fail("record_speech parked on a dead capture")
        self.assertNotIn("error", outcome)
        self.assertIsNone(outcome["audio"])
        self.assertLessEqual(capture.reads, 4)

    def test_speech_captured_before_the_cut_is_kept(self) -> None:
        loud = (np.ones(512, dtype=np.int16) * 20000).tobytes()
        capture = FakeCapture([loud])
        self.install(capture)
        audio = pipeline.record_speech(local_vad=False)
        self.assertIsNotNone(audio)
        assert audio is not None
        self.assertEqual(len(audio), 512)

    def test_the_global_capture_cleared_mid_record_is_not_an_error(self) -> None:
        # stop_face() sets the module global to None while a record is in
        # flight; reading through the global again would be an AttributeError.
        capture = FakeCapture()
        capture.on_read = lambda: setattr(pipeline, "_audio_capture", None)
        self.install(capture)
        self.assertIsNone(pipeline.record_speech(local_vad=False))


class ListPanelsTests(unittest.TestCase):
    def setUp(self) -> None:
        # The wall is rows in control.db now, not a module dict, so a test that
        # clears it would clear the user's real wall. Redirect the singleton at
        # a throwaway database first — see PanelStoreIsolation in
        # tests/test_room_life.py, which does the same for the panel suite.
        self._tmp = tempfile.TemporaryDirectory(prefix="rau-panels-")
        self._real_path = control_store.path
        self._real_ready = control_store._ready  # noqa: SLF001
        control_store.path = Path(self._tmp.name) / "control.db"
        control_store._ready = False  # noqa: SLF001 — forces re-initialize
        control_store.initialize()

    def tearDown(self) -> None:
        control_store.path = self._real_path
        control_store._ready = self._real_ready  # noqa: SLF001
        self._tmp.cleanup()

    def test_a_zero_limit_lists_nothing_not_everything(self) -> None:
        panels.show_panel({"title": "one", "html": "<p>1</p>"})
        panels.show_panel({"title": "two", "html": "<p>2</p>"})
        # `values()[-0:]` is the whole list, so this is the case that regresses.
        self.assertEqual(panels.list_panels(0), [])
        self.assertEqual(panels.list_panels(-2), [])
        self.assertEqual([p["title"] for p in panels.list_panels(1)], ["two"])
        self.assertEqual(len(panels.list_panels()), 2)


class HoldValidationTests(unittest.TestCase):
    def test_a_nan_or_infinite_hold_is_a_plan_error_not_a_crash(self) -> None:
        # Python's json parser accepts NaN/Infinity, so a model can deliver
        # one; int() on it raises a bare ValueError that escapes submit_plan
        # and kills the whole face turn.
        for bad in (math.nan, math.inf, -math.inf):
            result = choreography.submit_plan(
                {
                    "cues": [
                        {"anchor": "reply_start", "motion": "wave", "hold_ms": bad}
                    ]
                },
                turn_id="turn_test",
            )
            self.assertFalse(result["ok"], (bad, result))
            self.assertEqual(result["code"], "hold_out_of_range", (bad, result))

    def test_a_fractional_hold_still_truncates(self) -> None:
        cues = choreography.validate_cues(
            [{"anchor": "reply_start", "motion": "wave", "hold_ms": 3000.9}]
        )
        self.assertEqual(cues[0]["hold_ms"], 3000)


if __name__ == "__main__":
    unittest.main()
