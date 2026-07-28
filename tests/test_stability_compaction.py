"""Regression tests for context-compaction stability fixes.

Covers: the goal pin when the summarizer fails or comes back empty, and the
per-image token surcharge that lets CUA screenshot loops trigger compaction.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.agent import compaction  # noqa: E402
from rau.providers.base import Message  # noqa: E402


def _long_convo() -> List[Message]:
    convo = [
        Message(role="system", content="you are Rau"),
        Message(role="user", content="Hard task goal:\nfind the memory leak"),
    ]
    for i in range(60):
        convo.append(Message(role="assistant", content=f"step {i} " + "x" * 400))
        convo.append(Message(role="user", content=f"reply {i} " + "y" * 400))
    return convo


class SummarizerFallbackTests(unittest.TestCase):
    def test_failed_summarizer_keeps_the_goal_message(self) -> None:
        def broken(_text: str) -> str:
            raise RuntimeError("summarizer down")

        out = compaction.compact(_long_convo(), broken, budget=8000)
        self.assertLess(len(out), len(_long_convo()))
        self.assertEqual(out[0].role, "system")
        self.assertEqual(out[1].role, "user", "the goal turn must be pinned")
        joined = " ".join(m.content or "" for m in out)
        self.assertIn("Hard task goal", joined)
        self.assertIn("memory leak", joined)

    def test_empty_summary_keeps_the_goal_message(self) -> None:
        out = compaction.compact(_long_convo(), lambda _t: "  ", budget=8000)
        joined = " ".join(m.content or "" for m in out)
        self.assertIn("Hard task goal", joined)

    def test_working_summarizer_still_folds(self) -> None:
        out = compaction.compact(
            _long_convo(), lambda _t: "GOAL: find the memory leak", budget=8000
        )
        self.assertLess(len(out), len(_long_convo()))
        joined = " ".join(m.content or "" for m in out)
        self.assertIn("Summary of earlier conversation", joined)
        self.assertIn("step 59", joined)


class ImageTokenTests(unittest.TestCase):
    def test_images_add_a_per_image_surcharge(self) -> None:
        bare = Message(role="tool", content="ok")
        with_image = Message(role="tool", content="ok", images=[{"image_b64": "x"}])
        with_two = Message(
            role="tool", content="ok", images=[{"image_b64": "x"}, {"image_b64": "y"}]
        )
        base = compaction.message_tokens(bare)
        self.assertEqual(
            compaction.message_tokens(with_image) - base,
            compaction.PER_IMAGE_TOKENS,
        )
        self.assertEqual(
            compaction.message_tokens(with_two) - base,
            2 * compaction.PER_IMAGE_TOKENS,
        )

    def test_screenshot_loops_can_trigger_compaction(self) -> None:
        convo = [
            Message(role="system", content="s"),
            Message(role="user", content="g"),
        ]
        for _ in range(30):
            convo.append(Message(role="tool", content="", images=[{"image_b64": "x"}]))
        self.assertTrue(compaction.should_compact(convo, budget=8000))
        text_only = convo[:2] + [Message(role="tool", content="ok") for _ in range(30)]
        self.assertFalse(compaction.should_compact(text_only, budget=8000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
