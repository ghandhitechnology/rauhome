"""Provider-neutral voice discovery and browser preview helpers."""
from __future__ import annotations

from typing import Any, Dict, List

from rau.voice.stt.buffered import pcm_to_wav
from rau.voice.tts_stream import RobotVoice, SR, synth_sentence


def list_voices(provider: str) -> List[Dict[str, Any]]:
    if provider == "elevenlabs":
        from rau.voice.elevenlabs_api import list_voices as list_elevenlabs

        return list_elevenlabs()
    if provider == "cartesia":
        from rau.voice.cartesia_api import list_voices as list_cartesia

        return list_cartesia()
    raise ValueError(f"Unsupported TTS provider: {provider}")


def render_preview(
    *,
    provider: str,
    text: str,
    voice_id: str,
    model: str,
    effect: str,
    voice_settings: Dict[str, Any],
) -> bytes:
    pcm = b"".join(
        synth_sentence(
            text,
            provider=provider,
            voice_id=voice_id,
            model=model,
            voice_settings=voice_settings,
        )
    )
    if not pcm:
        raise RuntimeError(f"{provider.title()} returned no audio.")
    if effect != "none":
        pcm = RobotVoice(effect).process_pcm(pcm)
    return pcm_to_wav(pcm, sample_rate=SR)


__all__ = ["list_voices", "render_preview"]
