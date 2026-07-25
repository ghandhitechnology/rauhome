"""Pick an STT backend from the `stt` slot in config/models.json."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from rau.env import has_secret
from rau.providers.registry import get_slot
from rau.voice.stt.base import SttProvider

#: provider id -> env var that must be present for it to work.
STT_AUTH: Dict[str, str] = {
    "deepgram": "DEEPGRAM_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
    "local": "",  # no credential needed
}


def _build(provider: str, model: str, language: str) -> SttProvider:
    if provider == "deepgram":
        from rau.voice.stt.deepgram import DeepgramStt

        return DeepgramStt(model=model, language=language)
    if provider == "elevenlabs":
        from rau.voice.stt.elevenlabs_scribe import ScribeStt

        return ScribeStt(model=model, language=language)
    if provider == "openai":
        from rau.voice.stt.openai_stt import OpenAiStt

        return OpenAiStt(model=model, language=language)
    from rau.voice.stt.local_whisper import LocalWhisperStt

    return LocalWhisperStt(model=model or "small", language=language)


def available_stt() -> Dict[str, bool]:
    """Which backends are usable right now, for the UI."""
    return {
        pid: (True if not env else has_secret(env)) for pid, env in STT_AUTH.items()
    }


def resolve_stt() -> Tuple[str, Dict[str, Any]]:
    """
    Resolve the configured slot, falling back when its key is missing.

    A misconfigured slot must not leave voice mode dead — local whisper always
    works, so we degrade to it rather than raising.
    """
    slot = get_slot("stt")
    provider = str(slot.get("provider") or "local").lower()
    if provider not in STT_AUTH:
        provider = "local"
        slot = {**slot, "provider": "local", "model": "small", "_fallback": True}
    env = STT_AUTH.get(provider, "")
    if env and not has_secret(env):
        provider = "local"
        slot = {**slot, "provider": "local", "model": "small", "_fallback": True}
    return provider, slot


def get_stt_provider() -> SttProvider:
    provider, slot = resolve_stt()
    return _build(
        provider,
        str(slot.get("model") or ""),
        str(slot.get("language") or ""),
    )
