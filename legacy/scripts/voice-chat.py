#!/usr/bin/env python3
"""WALL-E Voice Chat Pipeline (Phase 2)
Mic → faster-whisper STT → Ollama LLM → kokoro-onnx TTS + SFX overlay → Speaker
"""
import io
import json
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel  # Alternative: mlx_whisper

# ===================== CONFIG =====================
PROJECT_ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system-prompt.md"
SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
OLLAMA_MODEL = "qwen3:14b"

# Audio settings
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.02
SILENCE_DURATION = 1.5  # seconds of silence to end recording
MAX_RECORDING = 10  # seconds max

# TTS settings
TTS_VOICE = "af_heart"  # Kokoro voice preset — soft/feminine, closest to Wall-E
TTS_SPEED = 1.1

# ===================== SFX MAP =====================
SFX_MAP = {
    "[HAPPY]": "happy_trill.wav",
    "[CURIOUS]": "curious_beep.wav",
    "[EXCITED]": "excited_trill.wav",
    "[SAD]": "sad_whir.wav",
    "[COMPACT]": "compacting.wav",
    "[SCARED]": "scared_beep.wav",
    "[AMAZED]": "whoa.wav",
    "[LOVE]": "eva_sigh.wav",
    "[DETERMINED]": "determined_whir.wav",
}


def record_until_silence() -> Optional[np.ndarray]:
    """Record audio until silence detected. Returns float32 numpy array or None."""
    print("🎤 Listening... (speak now)")

    audio_chunks = []
    silent_chunks = 0
    chunk_duration = 0.1  # 100ms chunks
    chunk_size = int(SAMPLE_RATE * chunk_duration)
    silence_chunks_needed = int(SILENCE_DURATION / chunk_duration)

    def callback(indata, frames, time_info, status):
        nonlocal silent_chunks
        audio_chunks.append(indata.copy())
        volume = np.abs(indata).mean()
        if volume < SILENCE_THRESHOLD:
            silent_chunks += 1
        else:
            silent_chunks = 0

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        callback=callback,
        blocksize=chunk_size,
    )

    with stream:
        start = time.time()
        while silent_chunks < silence_chunks_needed:
            sd.sleep(100)
            if time.time() - start > MAX_RECORDING:
                break

    if len(audio_chunks) < 5:
        print("  → No speech detected")
        return None

    audio = np.concatenate(audio_chunks)
    return audio


def transcribe(audio: np.ndarray) -> str:
    """STT using faster-whisper (tiny model for speed)."""
    model = WhisperModel("tiny", device="cpu", compute_type="int8")  # CPU for M4 compatibility
    segments, _ = model.transcribe(audio, language=None, beam_size=5)
    text = " ".join(s.text for s in segments).strip()
    return text


def wall_e_chat(text: str) -> str:
    """Send to Ollama with Wall-E system prompt."""
    with open(SYSTEM_PROMPT) as f:
        system = f.read()

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0.9, "top_p": 0.95, "num_predict": 80},
    }

    result = subprocess.run(
        ["curl", "-s", "http://127.0.0.1:11434/api/chat", "-d", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    return data.get("message", {}).get("content", "*confused beep* [CURIOUS]")


def extract_emotion(response: str) -> tuple[str, Optional[str]]:
    """Extract [EMOTION] tag from response. Returns (clean_text, emotion_or_none)."""
    import re

    match = re.search(r"\[(HAPPY|CURIOUS|EXCITED|SAD|COMPACT|SCARED|AMAZED|LOVE|DETERMINED)\]", response)
    if match:
        emotion = f"[{match.group(1)}]"
        clean = response.replace(emotion, "").strip()
        return clean, emotion
    return response, None


def speak_kokoro(text: str) -> Optional[np.ndarray]:
    """TTS using kokoro-onnx. Returns audio numpy array."""
    try:
        from kokoro_onnx import Kokoro

        kokoro = Kokoro("kokoro-v0_19.onnx", voices_path="voices.json")
        samples, sample_rate = kokoro.create(text, voice=TTS_VOICE, speed=TTS_SPEED, lang="en-us")
        return samples
    except Exception as e:
        print(f"  ⚠️ TTS failed: {e}")
        return None


def apply_robot_effect(audio: np.ndarray, pitch_factor: float = 1.3) -> np.ndarray:
    """Simple pitch shift for robot voice effect."""
    from scipy.signal import resample

    num_samples = int(len(audio) / pitch_factor)
    return resample(audio, num_samples)


def play_audio(audio: np.ndarray, sample_rate: int = 24000):
    """Play audio through speakers."""
    sd.play(audio, sample_rate)
    sd.wait()


def play_sfx(emotion_tag: str):
    """Play sound effect for emotion tag."""
    sfx_file = SFX_MAP.get(emotion_tag)
    if sfx_file and (SFX_DIR / sfx_file).exists():
        with wave.open(str(SFX_DIR / sfx_file), "rb") as wf:
            audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            sd.play(audio, wf.getframerate())
            sd.wait()


# ===================== MAIN LOOP =====================
def main():
    print("=" * 50)
    print("  WALL-E Voice Chat — Phase 2")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    while True:
        try:
            # 1. Record
            audio = record_until_silence()
            if audio is None:
                continue

            # 2. STT
            text = transcribe(audio)
            if not text:
                print("  → No speech detected")
                continue
            print(f"🧑 You: {text}")

            # 3. LLM
            response = wall_e_chat(text)
            clean_text, emotion = extract_emotion(response)
            print(f"🤖 WALL-E: {clean_text} {emotion or ''}")

            # 4. SFX (if emotion tag)
            if emotion:
                play_sfx(emotion)

            # 5. TTS (if there's text to speak)
            if clean_text and clean_text.strip("*beep*").strip():
                pass  # TODO: kokoro TTS integration

            print()

        except KeyboardInterrupt:
            print("\n👋 WALL-E signing off... *sad whir*")
            break
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
