"""Provider-neutral TTS + legacy robot FX."""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from rau.providers.registry import get_slot
from rau.voice.tts_stream import synth_sentence

SR = 24000
def tts(text: str) -> Optional[Tuple[np.ndarray, int]]:
    if not text or not text.strip():
        return None
    slot = get_slot("tts")
    provider = str(slot.get("provider") or "elevenlabs")
    voice_id = slot.get("voice_id") or "TX3LPaxmHKxFdv7VOQHJ"
    model = slot.get("model") or (
        "sonic-3.5" if provider == "cartesia" else "eleven_flash_v2_5"
    )
    try:
        raw = b"".join(
            synth_sentence(
                text,
                provider=provider,
                voice_id=voice_id,
                model=model,
                voice_settings=slot.get("voice_settings"),
            )
        )
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
