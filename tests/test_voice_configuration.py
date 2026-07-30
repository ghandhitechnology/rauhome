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


class OpenAiSttModelTests(unittest.TestCase):
    def test_catalog_lists_live_and_file_models(self) -> None:
        from rau.providers.catalog import STT_PROVIDERS, stt_supports_partials

        models = {m["id"]: m for m in STT_PROVIDERS["openai"]["models"]}
        self.assertIn("gpt-live-transcribe", models)
        self.assertIn("gpt-transcribe", models)
        self.assertTrue(stt_supports_partials("openai", "gpt-live-transcribe"))
        self.assertFalse(stt_supports_partials("openai", "gpt-transcribe"))
        self.assertFalse(stt_supports_partials("openai", "gpt-4o-transcribe"))

    def test_registry_routes_live_model_to_realtime(self) -> None:
        from rau.voice.stt import registry
        from rau.voice.stt.openai_realtime import OpenAiRealtimeStt
        from rau.voice.stt.openai_stt import OpenAiStt

        live = registry._build("openai", "gpt-live-transcribe", "en")
        buffered = registry._build("openai", "gpt-transcribe", "en")
        legacy = registry._build("openai", "gpt-4o-transcribe", "ko")

        self.assertIsInstance(live, OpenAiRealtimeStt)
        self.assertTrue(live.supports_partials)
        self.assertIsInstance(buffered, OpenAiStt)
        self.assertIsInstance(legacy, OpenAiStt)
        self.assertFalse(buffered.supports_partials)

    def test_upsample_16k_to_24k_is_three_halves(self) -> None:
        from array import array

        from rau.voice.stt.openai_realtime import upsample_pcm16_16k_to_24k

        samples = array("h", [0, 3000, -3000, 6000])
        out, carry = upsample_pcm16_16k_to_24k(samples.tobytes())
        self.assertEqual(carry, b"")
        self.assertEqual(len(out), len(samples) * 3)  # 2 bytes × 3/2 samples

    def test_upsample_preserves_odd_trailing_byte_across_frames(self) -> None:
        from array import array

        from rau.voice.stt.openai_realtime import upsample_pcm16_16k_to_24k

        # First frame ends mid-sample; the orphaned byte must survive in carry.
        first = b"\x01\x00\x02\x00\x03"
        out1, carry1 = upsample_pcm16_16k_to_24k(first)
        self.assertEqual(out1, array("h", [1, 1, 2]).tobytes())
        self.assertEqual(carry1, b"\x03")

        # Completing the sample with the next frame recovers it.
        out2, carry2 = upsample_pcm16_16k_to_24k(b"\x00\x04\x00", carry1)
        self.assertEqual(carry2, b"")
        self.assertEqual(out2, array("h", [3, 3, 4]).tobytes())

    def test_session_update_uses_languages_for_live_model(self) -> None:
        from rau.voice.stt.openai_realtime import OpenAiRealtimeStt

        update = OpenAiRealtimeStt(model="gpt-live-transcribe", language="ko")._session_update()
        transcription = update["session"]["audio"]["input"]["transcription"]
        self.assertEqual(transcription["model"], "gpt-live-transcribe")
        self.assertEqual(transcription["languages"], ["ko"])
        self.assertNotIn("language", transcription)


if __name__ == "__main__":
    unittest.main()
