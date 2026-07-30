"""Pick an STT backend from the `stt` slot in config/models.json."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from rau.env import has_secret
from rau.providers.registry import get_slot
from rau.voice.stt.base import SttProvider

#: provider id -> env var that must be present for it to work.
STT_AUTH: Dict[str, str] = {
    "auto": "",
    "deepgram": "DEEPGRAM_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
    "local": "",  # no credential needed
}

STT_DEFAULT_MODELS: Dict[str, str] = {
    "deepgram": "nova-3",
    "elevenlabs": "scribe_v2",
    "openai": "gpt-live-transcribe",
    "local": "small",
}


def _best_available() -> str:
    for provider in ("deepgram", "elevenlabs", "openai"):
        if has_secret(STT_AUTH[provider]):
            return provider
    return "local"


def _build(provider: str, model: str, language: str) -> SttProvider:
    if provider == "deepgram":
        from rau.voice.stt.deepgram import DeepgramStt

        return DeepgramStt(model=model, language=language)
    if provider == "elevenlabs":
        from rau.voice.stt.elevenlabs_scribe import ScribeStt

        return ScribeStt(model=model, language=language)
    if provider == "openai":
        from rau.voice.stt.openai_realtime import LIVE_MODELS, OpenAiRealtimeStt
        from rau.voice.stt.openai_stt import OpenAiStt

        if model in LIVE_MODELS:
            return OpenAiRealtimeStt(model=model, language=language)
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
    configured = str(slot.get("provider") or "auto").lower()
    provider = configured
    fallback_reason = ""
    if provider == "auto":
        provider = _best_available()
        fallback_reason = f"automatic selection chose {provider}"
    if provider not in STT_AUTH:
        fallback_reason = f"unknown backend {configured!r}"
        provider = _best_available()
    env = STT_AUTH.get(provider, "")
    if env and not has_secret(env):
        fallback_reason = f"{configured} key is not configured"
        provider = _best_available()

    # A model ID belongs to one provider. Never hand Deepgram's `nova-3` to
    # Scribe just because the configured backend had to fall back.
    configured_model = str(slot.get("model") or "")
    if configured != provider or configured == "auto":
        model = STT_DEFAULT_MODELS[provider]
    else:
        model = configured_model or STT_DEFAULT_MODELS[provider]
    slot = {
        **slot,
        "provider": provider,
        "model": model,
        "_configured_provider": configured,
        "_fallback": configured not in ("auto", provider),
        "_reason": fallback_reason,
    }
    return provider, slot


def get_stt_provider() -> SttProvider:
    provider, slot = resolve_stt()
    return _build(
        provider,
        str(slot.get("model") or ""),
        str(slot.get("language") or ""),
    )
