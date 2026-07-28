"""ElevenLabs TTS + robot FX."""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from rau.env import get_secret
from rau.providers.registry import get_slot
from rau.voice.pronunciation import normalize_for_tts

SR = 24000
_client = None


def _client_el():
    global _client
    if _client is None:
        from elevenlabs.client import ElevenLabs

        key = get_secret("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")
        _client = ElevenLabs(api_key=key)
    return _client


def tts(text: str) -> Optional[Tuple[np.ndarray, int]]:
    if not text or not text.strip():
        return None
    spoken = normalize_for_tts(text)
    if not spoken:
        return None
    slot = get_slot("tts")
    voice_id = slot.get("voice_id") or "TX3LPaxmHKxFdv7VOQHJ"
    model = slot.get("model") or "eleven_flash_v2_5"
    try:
        c = _client_el()
        gen = c.text_to_speech.convert(
            voice_id=voice_id,
            text=spoken,
            model_id=model,
            output_format="pcm_24000",
        )
        raw = b"".join(gen)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return audio, SR
    except Exception as e:
        print(f"  TTS err: {e}")
        return None


def apply_robot_fx(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    try:
        from pedalboard import Pedalboard, PitchShift, Bitcrush, Distortion, Reverb

        board = Pedalboard(
            [
                PitchShift(semitones=2),
                Bitcrush(bit_depth=10),
                Distortion(drive_db=2),
                Reverb(room_size=0.15, wet_level=0.08, dry_level=0.92),
            ]
        )
        return board(audio, sample_rate)
    except Exception:
        return audio


def warmup() -> None:
    try:
        tts("warm")
    except Exception as e:
        print(f"  TTS warmup skipped: {e}")
