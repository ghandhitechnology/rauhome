"""Face tools announce desk work so the avatar can walk to the computer."""
from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest import mock

from rau.events import BUS
from rau.face import brain
from rau.providers.base import ChatResult, ToolCall


class Recorder:
    def __init__(self, *kinds: str) -> None:
        self.events: List[Dict[str, Any]] = []
        self._kinds = set(kinds)
        BUS.on("*", self._append)

    def _append(self, event: Dict[str, Any]) -> None:
        if not self._kinds or event.get("kind") in self._kinds:
            self.events.append(event)

    def kinds(self) -> List[str]:
        return [e["kind"] for e in self.events]

    def stop(self) -> None:
        with BUS._lock:  # noqa: SLF001
            BUS._subs["*"] = [fn for fn in BUS._subs["*"] if fn is not self._append]


class DeskWorkSignalTests(unittest.TestCase):
    def test_shell_tool_brackets_with_started_and_finished(self) -> None:
        recorder = Recorder("tool_started", "tool_finished")
        try:
            with mock.patch.object(
                brain, "_run_face_tool", return_value={"ok": True, "stdout": "hi"}
            ):
                messages: list = []
                result = ChatResult(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="run_shell",
                            arguments={"command": "echo hi"},
                        )
                    ],
                )
                brain._record_tool_round(messages, result, "")
        finally:
            recorder.stop()

        self.assertEqual(recorder.kinds(), ["tool_started", "tool_finished"])
        self.assertEqual(recorder.events[0]["name"], "run_shell")
        self.assertEqual(recorder.events[0]["motion"], "type")
        self.assertTrue(recorder.events[1]["ok"])

    def test_body_choreography_does_not_claim_the_desk(self) -> None:
        recorder = Recorder("tool_started", "tool_finished")
        try:
            with mock.patch.object(
                brain, "_run_face_tool", return_value={"ok": True}
            ):
                messages: list = []
                result = ChatResult(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="body_choreography",
                            arguments={"cues": []},
                        )
                    ],
                )
                brain._record_tool_round(messages, result, "")
        finally:
            recorder.stop()

        self.assertEqual(recorder.kinds(), [])


if __name__ == "__main__":
    unittest.main()
