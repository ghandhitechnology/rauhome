"""Capability-aware effort / reasoning wire mapping."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class ReasoningForTests(unittest.TestCase):
    def test_deepseek_levels(self) -> None:
        from rau.providers.catalog import reasoning_for

        cap = reasoning_for("deepseek", "deepseek-v4-pro")
        self.assertTrue(cap["supported"])
        self.assertEqual(cap["levels"], ["high", "max"])
        self.assertEqual(cap["param"], "deepseek")

    def test_luna_unsupported(self) -> None:
        from rau.providers.catalog import reasoning_for

        cap = reasoning_for("openai", "gpt-5.6-luna")
        self.assertFalse(cap["supported"])
        self.assertEqual(cap["levels"], [])


class ClampAndBuildTests(unittest.TestCase):
    def test_deepseek_maps_medium_to_high_and_enables_thinking(self) -> None:
        from rau.providers.reasoning import build_reasoning_fields, clamp_effort

        self.assertEqual(
            clamp_effort("deepseek", "deepseek-v4-flash", "medium"),
            "high",
        )
        fields = build_reasoning_fields("deepseek", "deepseek-v4-flash", "medium")
        self.assertEqual(fields.get("reasoning_effort"), "high")
        self.assertEqual(fields.get("thinking"), {"type": "enabled"})

    def test_unsupported_omits_fields(self) -> None:
        from rau.providers.reasoning import build_reasoning_fields, clamp_effort

        self.assertIsNone(clamp_effort("openai", "gpt-5.6-luna", "high"))
        self.assertEqual(
            build_reasoning_fields("openai", "gpt-5.6-luna", "high"),
            {},
        )

    def test_kimi_medium_maps_to_high(self) -> None:
        from rau.providers.reasoning import build_reasoning_fields

        fields = build_reasoning_fields("kimi", "kimi-k3", "medium")
        self.assertEqual(fields.get("reasoning_effort"), "high")


class OpenAICompatWireTests(unittest.TestCase):
    def test_apply_on_payload(self) -> None:
        from rau.providers.reasoning import apply_reasoning_payload

        payload: dict = {"model": "deepseek-v4-pro", "messages": []}
        apply_reasoning_payload(payload, "deepseek", "deepseek-v4-pro", "max")
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertEqual(payload["thinking"], {"type": "enabled"})


class SaveModelsClampTests(unittest.TestCase):
    def test_validated_models_clamps_deepseek_medium(self) -> None:
        from rau.providers import registry

        cfg = {
            "face": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "max_tokens": 4096,
                "temperature": 0.7,
                "effort": "medium",
            },
            "subagent": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "max_tokens": 4096,
                "temperature": 0.2,
                "effort": "high",
            },
            "dream": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "max_tokens": 2048,
                "temperature": 0.5,
                "effort": "low",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with mock.patch.object(registry, "MODELS_CONFIG", path):
                with mock.patch.object(registry, "_models", {}):
                    # Need tts/stt defaults from validation
                    checked = registry._validated_models(cfg)
                    self.assertEqual(checked["face"]["effort"], "high")
                    self.assertEqual(checked["subagent"]["effort"], "high")
                    self.assertEqual(checked["dream"]["effort"], "high")


class EffortSnapshotTests(unittest.TestCase):
    def test_slots_expose_allowed(self) -> None:
        from rau.providers.reasoning import effort_snapshot

        snap = effort_snapshot(
            {
                "face": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                    "effort": "medium",
                },
                "subagent": {
                    "provider": "openai",
                    "model": "gpt-5.6-luna",
                    "effort": "high",
                },
                "dream": {
                    "provider": "kimi",
                    "model": "kimi-k3",
                    "effort": "medium",
                },
            }
        )
        self.assertEqual(snap["slots"]["face"]["allowed"], ["high", "max"])
        self.assertEqual(snap["face"], "high")
        self.assertFalse(snap["slots"]["subagent"]["supported"])
        self.assertEqual(snap["slots"]["dream"]["allowed"], ["low", "high", "max"])
        self.assertEqual(snap["dream"], "high")


if __name__ == "__main__":
    unittest.main()
