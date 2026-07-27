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


class AnthropicThinkingBudgetTests(unittest.TestCase):
    """Anthropic requires max_tokens > thinking.budget_tokens (else HTTP 400).

    Slot max_tokens shapes: face 512, player 400, dream 2048, subagent 4096.
    The budget clamps to max_tokens - 1 down to the 1024 floor; a payload
    too small for the floor omits thinking entirely (no thinking beats a
    guaranteed 400).
    """

    def _payload(self, max_tokens: int, effort: str) -> dict:
        from rau.providers.reasoning import apply_reasoning_payload

        payload: dict = {
            "model": "k3",
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "messages": [],
        }
        apply_reasoning_payload(payload, "kimi_code", "k3", effort)
        return payload

    def test_face_shape_omits_thinking(self) -> None:
        # face max_tokens 512: even the low budget (1024) cannot fit under it.
        payload = self._payload(512, "low")
        self.assertNotIn("thinking", payload)

    def test_player_shape_omits_thinking(self) -> None:
        payload = self._payload(400, "high")
        self.assertNotIn("thinking", payload)

    def test_dream_shape_clamps_budget(self) -> None:
        payload = self._payload(2048, "high")  # mapped budget 4096
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 2047})

    def test_subagent_shape_clamps_budget(self) -> None:
        payload = self._payload(4096, "max")  # mapped budget 8192
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 4095})

    def test_budget_that_fits_is_left_alone(self) -> None:
        payload = self._payload(4096, "low")  # 1024 fits under 4096
        self.assertEqual(payload["thinking"]["budget_tokens"], 1024)

    def test_missing_max_tokens_keeps_mapped_budget(self) -> None:
        # Contract pinned by tests/test_stability_providers.py: without a
        # max_tokens to reconcile against, the raw mapped budget is kept.
        from rau.providers.reasoning import apply_reasoning_payload

        payload: dict = {"model": "k3", "messages": []}
        apply_reasoning_payload(payload, "kimi_code", "k3", "max")
        self.assertEqual(payload["thinking"]["budget_tokens"], 8192)


class OpenAIProviderDefaultTests(unittest.TestCase):
    """Unlisted openai/codex ids: temperature is only dropped for the
    reasoning families that actually reject it, not for chat models."""

    def test_unlisted_chat_model_keeps_temperature(self) -> None:
        from rau.providers.catalog import reasoning_for

        cap = reasoning_for("openai", "gpt-4o")
        self.assertTrue(cap["supported"])
        self.assertFalse(cap["fixed_temperature"])

    def test_unlisted_reasoning_models_stay_strict(self) -> None:
        from rau.providers.catalog import reasoning_for

        for model in ("gpt-5.9", "o3", "o4-mini"):
            cap = reasoning_for("openai", model)
            self.assertTrue(cap["fixed_temperature"], model)

    def test_apply_keeps_temperature_for_unlisted_chat_model(self) -> None:
        from rau.providers.reasoning import apply_reasoning_payload

        payload: dict = {"model": "gpt-4o", "temperature": 0.7, "messages": []}
        apply_reasoning_payload(payload, "openai", "gpt-4o", "high")
        self.assertEqual(payload["temperature"], 0.7)
        self.assertEqual(payload["reasoning_effort"], "high")


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
            "player": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "max_tokens": 400,
                "temperature": 0.6,
                "effort": "medium",
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
                    self.assertEqual(checked["player"]["effort"], "high")
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
