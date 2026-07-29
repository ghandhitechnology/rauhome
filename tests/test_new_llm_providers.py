"""Catalog, auth slots, and verify wiring for Claude / Grok / Gemini / Z.AI."""
from __future__ import annotations

import unittest
from unittest import mock

from rau.env import AUTH_SLOTS, slot_by_id
from rau.providers.catalog import PROVIDER_AUTH, catalog, reasoning_for
from rau.providers.openai_compat import PROVIDERS
from rau.providers import verify


class NewProviderCatalogTests(unittest.TestCase):
    def test_auth_slots_and_env_names(self) -> None:
        by_id = {s["id"]: s for s in AUTH_SLOTS}
        self.assertEqual(by_id["zai_code"]["env"], "ZAI_API_KEY")
        self.assertEqual(by_id["anthropic"]["env"], "ANTHROPIC_API_KEY")
        self.assertEqual(by_id["xai"]["env"], "XAI_API_KEY")
        self.assertEqual(by_id["gemini"]["env"], "GEMINI_API_KEY")
        self.assertTrue(by_id["anthropic"]["docs_url"])
        self.assertTrue(by_id["zai_code"].get("connect_url"))

    def test_provider_auth_maps_to_slots(self) -> None:
        self.assertEqual(PROVIDER_AUTH["zai_code"], "zai_code")
        self.assertEqual(PROVIDER_AUTH["zai"], "zai_code")
        self.assertEqual(PROVIDER_AUTH["anthropic"], "anthropic")
        self.assertEqual(PROVIDER_AUTH["claude"], "anthropic")
        self.assertEqual(PROVIDER_AUTH["xai"], "xai")
        self.assertEqual(PROVIDER_AUTH["grok"], "xai")
        self.assertEqual(PROVIDER_AUTH["gemini"], "gemini")
        self.assertEqual(PROVIDER_AUTH["google"], "gemini")

    def test_catalog_exposes_curated_models(self) -> None:
        payload = catalog()
        providers = payload["providers"]
        self.assertIn("zai_code", providers)
        self.assertIn("anthropic", providers)
        self.assertIn("xai", providers)
        self.assertIn("gemini", providers)
        self.assertEqual(providers["zai_code"]["models"][0]["id"], "glm-5.2")
        self.assertEqual(providers["anthropic"]["models"][0]["id"], "claude-fable-5")
        self.assertEqual(providers["xai"]["models"][0]["id"], "grok-4.5")
        self.assertEqual(providers["gemini"]["models"][0]["id"], "gemini-3.1-pro-preview")
        # Blurbs stay short and practical (no legacy retirement notes).
        for pid in ("zai_code", "anthropic", "xai", "gemini"):
            blurb = providers[pid]["blurb"]
            self.assertTrue(blurb)
            self.assertNotIn("legacy", blurb.lower())

    def test_runtime_clients_registered(self) -> None:
        self.assertIn("zai_code", PROVIDERS)
        self.assertIn("anthropic", PROVIDERS)
        self.assertIn("xai", PROVIDERS)
        self.assertIn("gemini", PROVIDERS)
        self.assertIs(PROVIDERS["zai"], PROVIDERS["zai_code"])
        self.assertIs(PROVIDERS["claude"], PROVIDERS["anthropic"])
        self.assertIs(PROVIDERS["grok"], PROVIDERS["xai"])
        self.assertIs(PROVIDERS["google"], PROVIDERS["gemini"])
        self.assertEqual(PROVIDERS["zai_code"].base_url, "https://api.z.ai/api/coding/paas/v4")
        self.assertEqual(PROVIDERS["anthropic"].base_url, "https://api.anthropic.com")
        self.assertEqual(PROVIDERS["xai"].base_url, "https://api.x.ai/v1")
        self.assertEqual(
            PROVIDERS["gemini"].base_url,
            "https://generativelanguage.googleapis.com/v1beta/openai",
        )

    def test_claude_console_uses_anthropic_thinking(self) -> None:
        cap = reasoning_for("anthropic", "claude-opus-5")
        self.assertTrue(cap["supported"])
        self.assertEqual(cap["param"], "anthropic")
        self.assertTrue(cap["fixed_temperature"])
        haiku = reasoning_for("anthropic", "claude-haiku-4-5")
        self.assertFalse(haiku["supported"])


class NewProviderVerifyTests(unittest.TestCase):
    def test_openai_compat_verify_urls(self) -> None:
        self.assertEqual(
            verify._OPENAI_COMPAT_LIST["zai_code"],
            "https://api.z.ai/api/coding/paas/v4/models",
        )
        self.assertEqual(verify._OPENAI_COMPAT_LIST["xai"], "https://api.x.ai/v1/models")
        self.assertTrue(
            verify._OPENAI_COMPAT_LIST["gemini"].endswith("/v1beta/openai/models")
        )

    def test_anthropic_verify_lists_models(self) -> None:
        with mock.patch.object(
            verify,
            "_get_json",
            return_value={"data": [{"id": "claude-opus-5"}, {"id": "claude-sonnet-5"}]},
        ) as get:
            result = verify._verify_anthropic("sk-ant-test")
        self.assertTrue(result["ok"])
        self.assertIn("2 models", result["detail"])
        self.assertEqual(get.call_args[0][0], "https://api.anthropic.com/v1/models")
        self.assertEqual(get.call_args[0][1]["x-api-key"], "sk-ant-test")
        self.assertEqual(get.call_args[0][1]["anthropic-version"], "2023-06-01")

    def test_verify_dispatch_reaches_new_slots(self) -> None:
        self.assertIsNotNone(slot_by_id("anthropic"))
        with mock.patch.object(
            verify,
            "_verify_anthropic",
            return_value={"ok": True, "detail": "ok", "models": []},
        ) as check:
            with mock.patch.object(verify, "get_secret", return_value="sk-saved"):
                result = verify.verify("anthropic")
        self.assertTrue(result["ok"])
        check.assert_called_once_with("sk-saved")

        with mock.patch.object(
            verify,
            "_verify_openai_compat",
            return_value={"ok": True, "detail": "ok", "models": []},
        ) as check_oa:
            with mock.patch.object(verify, "get_secret", return_value="key"):
                for slot in ("zai_code", "xai", "gemini"):
                    self.assertTrue(verify.verify(slot)["ok"])
        self.assertEqual(check_oa.call_count, 3)


if __name__ == "__main__":
    unittest.main()
