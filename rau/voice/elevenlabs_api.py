"""Small, server-only helpers for ElevenLabs voice discovery and previews."""
from __future__ import annotations

from typing import Any, Dict, List

from rau.env import get_secret
from rau.voice.stt.buffered import pcm_to_wav
from rau.voice.tts_stream import RobotVoice, SR, synth_sentence


def _client():
    from elevenlabs.client import ElevenLabs

    key = get_secret("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("Connect an ElevenLabs API key first.")
    return ElevenLabs(api_key=key)


def list_voices() -> List[Dict[str, Any]]:
    """Return the voices this key can actually synthesize with."""
    response = _client().voices.search(page_size=100)
    output: List[Dict[str, Any]] = []
    for voice in getattr(response, "voices", None) or []:
        voice_id = str(getattr(voice, "voice_id", "") or "")
        name = str(getattr(voice, "name", "") or "")
        if not voice_id or not name:
            continue
        raw_labels = getattr(voice, "labels", None) or {}
        labels = {
            str(key): str(value)
            for key, value in dict(raw_labels).items()
            if key and value
        }
        preview_url = str(getattr(voice, "preview_url", "") or "")
        if preview_url and not preview_url.startswith("https://"):
            preview_url = ""
        output.append(
            {
                "id": voice_id,
                "label": name,
                "category": str(getattr(voice, "category", "") or ""),
                "description": str(getattr(voice, "description", "") or "")[:500],
                "labels": labels,
                "preview_url": preview_url,
            }
        )
    output.sort(
        key=lambda item: (
            item["category"] == "premade",
            str(item["label"]).casefold(),
        )
    )
    return output


def render_preview(
    *,
    text: str,
    voice_id: str,
    model: str,
    effect: str,
    voice_settings: Dict[str, Any],
) -> bytes:
    """Synthesize the exact configured voice and return a browser-playable WAV."""
    pcm = b"".join(
        synth_sentence(
            text,
            provider="elevenlabs",
            voice_id=voice_id,
            model=model,
            voice_settings=voice_settings,
        )
    )
    if not pcm:
        raise RuntimeError("ElevenLabs returned no audio.")
    if effect != "none":
        pcm = RobotVoice(effect).process_pcm(pcm)
    return pcm_to_wav(pcm, sample_rate=SR)
