"""
Bug-sweep regressions: browse error classification, CDP error shapes, cron
day-of-week ranges ending in 7, and the pi sidecar lifecycle.

Nothing here touches the network; transports and processes are fakes.

Run: python -m unittest tests.test_bugfix_browse -v
"""
from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.browse.base import BrowseError, post_json  # noqa: E402
from rau.browse.browserbase import _Cdp  # noqa: E402, SLF001
from rau.pi.client import PiSidecar, PiSidecarError  # noqa: E402
from rau.pi.supervisor import PiSupervisor  # noqa: E402
from rau.scheduler.cron import CronError, CronSpec  # noqa: E402


class TimeoutClassificationTests(unittest.TestCase):
    """urllib wraps socket timeouts in URLError; they are not 'unreachable'."""

    def test_a_wrapped_socket_timeout_is_a_timeout_not_unreachable(self) -> None:
        def opener(*_args, **_kwargs):
            raise urllib.error.URLError(TimeoutError("timed out"))

        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(BrowseError) as caught:
                post_json("https://x", {}, {}, timeout=1)
        self.assertEqual(caught.exception.code, "timeout")

    def test_a_bare_timeout_is_still_a_timeout(self) -> None:
        def opener(*_args, **_kwargs):
            raise TimeoutError("timed out")

        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(BrowseError) as caught:
                post_json("https://x", {}, {}, timeout=1)
        self.assertEqual(caught.exception.code, "timeout")

    def test_a_genuine_connection_failure_is_still_unreachable(self) -> None:
        def opener(*_args, **_kwargs):
            raise urllib.error.URLError("no route")

        with mock.patch("urllib.request.urlopen", opener):
            with self.assertRaises(BrowseError) as caught:
                post_json("https://x", {}, {}, timeout=1)
        self.assertEqual(caught.exception.code, "unreachable")


class _ReplySocket:
    """A CDP peer that answers every command with the same canned reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def send(self, _raw: str) -> None:
        pass

    def recv(self, timeout: float = 0):  # noqa: ARG002
        return self.reply


class CdpErrorShapeTests(unittest.TestCase):
    def test_a_non_dict_error_is_a_browse_error_not_a_crash(self) -> None:
        # A provider that sends {"error": "boom"} used to die on .get with an
        # AttributeError instead of failing the fetch cleanly.
        cdp = _Cdp(_ReplySocket(json.dumps({"id": 1, "error": "boom"})))
        with self.assertRaises(BrowseError) as caught:
            cdp.call("Page.navigate")
        self.assertEqual(caught.exception.code, "provider_error")
        self.assertIn("boom", str(caught.exception))

    def test_a_dict_error_still_reports_its_message(self) -> None:
        cdp = _Cdp(_ReplySocket(json.dumps({"id": 1, "error": {"message": "nope"}})))
        with self.assertRaises(BrowseError) as caught:
            cdp.call("Page.navigate")
        self.assertEqual(caught.exception.code, "provider_error")
        self.assertIn("nope", str(caught.exception))


class CronDayOfWeekTests(unittest.TestCase):
    # 2024-01-01 was a Monday, so the 5th/6th/7th/8th are Fri/Sat/Sun/Mon.

    def test_a_range_ending_in_7_spans_the_weekend(self) -> None:
        # POSIX spells Sunday as 7; folding 7 to 0 before expanding turned
        # 5-7 into a "descending range" and rejected a valid expression.
        spec = CronSpec.parse("0 9 * * 5-7")
        self.assertEqual(spec.weekdays, {0, 5, 6})
        self.assertTrue(spec.matches(datetime(2024, 1, 5, 9, 0)))
        self.assertTrue(spec.matches(datetime(2024, 1, 6, 9, 0)))
        self.assertTrue(spec.matches(datetime(2024, 1, 7, 9, 0)))
        self.assertFalse(spec.matches(datetime(2024, 1, 8, 9, 0)))

    def test_zero_to_seven_means_every_day(self) -> None:
        spec = CronSpec.parse("0 9 * * 0-7")
        self.assertEqual(spec.weekdays, {0, 1, 2, 3, 4, 5, 6})
        self.assertTrue(spec.matches(datetime(2024, 1, 8, 9, 0)))

    def test_seven_alone_is_still_sunday(self) -> None:
        spec = CronSpec.parse("0 9 * * 7")
        self.assertEqual(spec.weekdays, {0})
        self.assertTrue(spec.matches(datetime(2024, 1, 7, 9, 0)))
        self.assertFalse(spec.matches(datetime(2024, 1, 8, 9, 0)))

    def test_eight_is_still_outside_the_field(self) -> None:
        with self.assertRaises(CronError):
            CronSpec.parse("0 9 * * 8")

    def test_a_descending_range_is_still_rejected(self) -> None:
        with self.assertRaises(CronError):
            CronSpec.parse("0 9 * * 6-5")


class _FakeProc:
    """A live process stand-in: poll() says running, wait() says it exited."""

    def __init__(self) -> None:
        self.pid = 4242
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):  # noqa: ARG002
        return 0

    def kill(self) -> None:
        self.killed = True


class IdleStopTests(unittest.TestCase):
    def test_the_idle_decision_and_the_stop_are_atomic(self) -> None:
        # stop_if_idle used to drop the lock between the idle check and the
        # stop, so an ensure_running landing in between lost its fresh sidecar.
        supervisor = PiSupervisor()
        supervisor._process = _FakeProc()  # noqa: SLF001
        supervisor._last_used = time.time() - 10_000  # noqa: SLF001
        owned: list[bool] = []
        real_stop = supervisor.stop

        def recording_stop() -> None:
            owned.append(supervisor._lock._is_owned())  # noqa: SLF001
            real_stop()

        with mock.patch.object(supervisor, "stop", recording_stop):
            with mock.patch("os.killpg"):
                stopped = supervisor.stop_if_idle(300.0)
        self.assertTrue(stopped)
        self.assertEqual(owned, [True])

    def test_a_recently_used_sidecar_is_not_stopped(self) -> None:
        supervisor = PiSupervisor()
        supervisor._process = _FakeProc()  # noqa: SLF001
        supervisor.touch()
        with mock.patch.object(supervisor, "stop") as stop:
            self.assertFalse(supervisor.stop_if_idle(300.0))
        stop.assert_not_called()

    def test_a_dead_sidecar_is_not_stopped_again(self) -> None:
        supervisor = PiSupervisor()
        with mock.patch.object(supervisor, "stop") as stop:
            self.assertFalse(supervisor.stop_if_idle(300.0))
        stop.assert_not_called()


class _UnreadableBody:
    def read(self, *_args, **_kwargs):
        raise OSError("connection dropped mid-body")

    def close(self) -> None:
        pass


class ErrorBodyTests(unittest.TestCase):
    """An HTTPError whose body cannot be read must still be a PiSidecarError."""

    @staticmethod
    def _opener(*_args, **_kwargs):
        raise urllib.error.HTTPError("u", 500, "boom", {}, _UnreadableBody())

    def test_health_raises_a_sidecar_error(self) -> None:
        client = PiSidecar()
        with mock.patch("urllib.request.urlopen", self._opener):
            with self.assertRaises(PiSidecarError):
                client.health()

    def test_available_stays_false_instead_of_crashing(self) -> None:
        client = PiSidecar()
        with mock.patch("urllib.request.urlopen", self._opener):
            self.assertFalse(client.available())


if __name__ == "__main__":
    unittest.main()
