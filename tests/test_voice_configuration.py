from __future__ import annotations

import unittest
from types import SimpleNamespace


class SttResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        from rau.voice.stt import registry

        self.registry = registry
        self.original_slot = registry.get_slot
        self.original_secret = registry.has_secret

    def tearDown(self) -> None:
        self.registry.get_slot = self.original_slot
        self.registry.has_secret = self.original_secret

    def test_auto_prefers_streaming_deepgram_and_uses_its_model(self) -> None:
        self.registry.get_slot = lambda _name: {
            "provider": "auto",
            "model": "",
            "language": "en",
        }
        self.registry.has_secret = lambda env: env == "DEEPGRAM_API_KEY"

        provider, slot = self.registry.resolve_stt()

        self.assertEqual(provider, "deepgram")
        self.assertEqual(slot["model"], "nova-3")
        self.assertEqual(slot["_configured_provider"], "auto")
        self.assertFalse(slot["_fallback"])

    def test_missing_provider_key_falls_back_without_reusing_wrong_model(self) -> None:
        self.registry.get_slot = lambda _name: {
            "provider": "elevenlabs",
            "model": "scribe_v2",
            "language": "ko",
        }
        self.registry.has_secret = lambda env: env == "DEEPGRAM_API_KEY"

        provider, slot = self.registry.resolve_stt()

        self.assertEqual(provider, "deepgram")
        self.assertEqual(slot["model"], "nova-3")
        self.assertTrue(slot["_fallback"])
        self.assertIn("key", slot["_reason"])


class VoiceCatalogTests(unittest.TestCase):
    def test_required_personalities_are_complete_and_unique(self) -> None:
        from rau.providers.catalog import VOICE_PRESETS

        self.assertEqual(
            {preset["id"] for preset in VOICE_PRESETS},
            {"robotic", "grandfather", "girlfriend", "child"},
        )
        self.assertEqual(
            len({preset["voice_id"] for preset in VOICE_PRESETS}),
            len(VOICE_PRESETS),
        )
        for preset in VOICE_PRESETS:
            self.assertIn(preset["effect"], {"none", "robot", "childlike"})
            self.assertTrue(preset["settings"]["use_speaker_boost"])

    def test_account_voice_mapping_returns_only_safe_fields(self) -> None:
        from rau.voice import elevenlabs_api

        original = elevenlabs_api._client
        elevenlabs_api._client = lambda: SimpleNamespace(
            voices=SimpleNamespace(
                search=lambda **_kwargs: SimpleNamespace(
                    voices=[
                        SimpleNamespace(
                            voice_id="abc123",
                            name="My voice",
                            category="generated",
                            labels={"age": "adult"},
                            description="A custom voice",
                            preview_url="https://example.test/preview.mp3",
                            secret_internal_field="must not escape",
                        )
                    ]
                )
            )
        )
        try:
            voices = elevenlabs_api.list_voices()
        finally:
            elevenlabs_api._client = original

        self.assertEqual(len(voices), 1)
        self.assertEqual(voices[0]["id"], "abc123")
        self.assertNotIn("secret_internal_field", voices[0])


class LanguageNormalizationTests(unittest.TestCase):
    def test_scribe_converts_common_two_letter_codes(self) -> None:
        from rau.voice.stt.elevenlabs_scribe import ScribeStt

        self.assertEqual(ScribeStt(language="en").language, "eng")
        self.assertEqual(ScribeStt(language="ko").language, "kor")
        self.assertEqual(ScribeStt(language="jpn").language, "jpn")
        self.assertEqual(ScribeStt(language="xx").language, "")


if __name__ == "__main__":
    unittest.main()
