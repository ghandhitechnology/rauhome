"""Regression tests for the agent-tool bug sweep (tools/edit/sandbox/danger)."""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.agent import edit  # noqa: E402
from rau.agent.danger import classify_tool  # noqa: E402
from rau.agent.sandbox import PathEscape, resolve_in_root  # noqa: E402
from rau.agent.tools import _number, run_tool  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


class NullBytePathTests(unittest.TestCase):
    """A path the OS cannot even stat must be refused, not raised."""

    def test_resolve_in_root_refuses_null_byte(self) -> None:
        with self.assertRaises(PathEscape):
            resolve_in_root("a\0b")

    def test_file_tools_return_an_error_instead_of_raising(self) -> None:
        cases = (
            ("read_file", {"path": "a\0b"}),
            ("write_file", {"path": "a\0b", "content": "x"}),
            ("edit_file", {"path": "a\0b", "old_string": "x", "new_string": "y"}),
        )
        for tool, args in cases:
            with self.subTest(tool=tool):
                result = run_tool(tool, args)
                self.assertFalse(result["ok"])
                self.assertIn("error", result)

    def test_danger_classifier_survives_null_byte(self) -> None:
        needs_confirm, _summary = classify_tool(
            "write_file", {"path": "a\0b", "content": "x"}
        )
        self.assertIs(needs_confirm, False)


class NumberParsingTests(unittest.TestCase):
    def test_explicit_null_falls_back_to_default(self) -> None:
        self.assertEqual(
            _number(None, default=120.0, minimum=1.0, maximum=600.0), 120.0
        )

    def test_out_of_range_is_still_rejected(self) -> None:
        self.assertIsNone(_number(9999, default=120.0, minimum=1.0, maximum=600.0))
        self.assertIsNone(_number("abc", default=120.0, minimum=1.0, maximum=600.0))

    def test_null_timeout_runs_with_default(self) -> None:
        result = run_tool("run_shell", {"command": "printf ok", "timeout_sec": None})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["stdout"], "ok")


class BoundedReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(dir=REPO_ROOT))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_large_file_is_truncated_and_not_edit_licensed(self) -> None:
        big = self.tmp / "big.txt"
        big.write_text("x" * 200_000, encoding="utf-8")
        result = run_tool("read_file", {"path": str(big)})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["content"]), 50000)
        # A truncated read must not license an edit against unseen contents.
        seen, _why = edit._seen_current(big.resolve())
        self.assertFalse(seen)

    def test_small_file_is_fully_read_and_edit_licensed(self) -> None:
        small = self.tmp / "small.txt"
        small.write_text("alpha = 1\n", encoding="utf-8")
        result = run_tool("read_file", {"path": str(small)})
        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "alpha = 1\n")
        seen, _why = edit._seen_current(small.resolve())
        self.assertTrue(seen)
        edited = edit.edit_file(str(small), "alpha = 1", "alpha = 2")
        self.assertTrue(edited["ok"], edited.get("error"))


class ShellOutputCapTests(unittest.TestCase):
    def test_runaway_output_is_killed_instead_of_filling_the_disk(self) -> None:
        started = time.monotonic()
        with patch("rau.agent.tools.MAX_SHELL_OUTPUT_BYTES", 4096):
            result = run_tool("run_shell", {"command": "yes", "timeout_sec": 60})
        self.assertLess(time.monotonic() - started, 15)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("output_overflow"), str(result)[:200])
        self.assertLessEqual(len(result["stdout"]), 8000)

    def test_unkillable_process_is_reported_not_raised(self) -> None:
        class StubbornProcess:
            pid = 0

            def poll(self):  # already exited, so the poll loop is skipped
                return 0

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(cmd=["fake"], timeout=timeout)

        with (
            patch("rau.agent.tools.shell_argv", return_value=(["/bin/true"], None)),
            patch("rau.agent.tools.subprocess.Popen", return_value=StubbornProcess()),
        ):
            result = run_tool("run_shell", {"command": "fake"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], -signal.SIGKILL)


class CuaActionErrorTests(unittest.TestCase):
    def test_session_conflict_is_an_error_result_not_an_exception(self) -> None:
        with patch(
            "rau.computer.session.compatibility_cua_action",
            side_effect=RuntimeError(
                "another computer-use session owns the machine"
            ),
        ):
            result = run_tool("cua_action", {"action": "screenshot"})
        self.assertFalse(result["ok"])
        self.assertIn("owns the machine", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
