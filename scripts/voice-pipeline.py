#!/usr/bin/env python3
"""WALL-E Interactive Voice Chat — Real Pipeline (Phase 2 Complete)

Pipeline:
  Mic → webrtcvad (detect speech) → record buffer
      → faster-whisper (STT) → Ollama (LLM with WALL-E system prompt)
      → parse emotion tag → play SFX
      → kokoro-onnx (TTS) + pedalboard (robot FX)
      → play through speaker

Usage:
  source venv/bin/activate
  python3 scripts/voice-pipeline.py
"""

import io
import json
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd
import webrtcvad

# ===================== CONFIG =====================
PROJECT_ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system-prompt.md"
SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
MODELS_DIR = PROJECT_ROOT / "models"
OLLAMA_MODEL = "gemma3:4b"  # 3.3GB — 5GB saved vs 12b

# Audio
SAMPLE_RATE = 16000  # Whisper native rate
FRAME_MS = 30         # 30ms frames for VAD
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)
VAD_MODE = 2          # 0=least aggressive, 3=most

# Silence detection
SILENCE_SEC = 1.5     # seconds of silence to end utterance
MAX_RECORD_SEC = 10   # max recording duration

# ===================== SFX MAP =====================
SFX_MAP = {
    "[HAPPY]": "curious_beep.wav",      # closest to happy chirp
    "[CURIOUS]": "curious_beep.wav",
    "[EXCITED]": "excited_trill.wav",
    "[SAD]": "sad_whir.wav",
    "[COMPACT]": "compacting.wav",
    "[SCARED]": "scared_beep.wav",
    "[AMAZED]": "whoa.wav",
    "[LOVE]": "eva_sigh.wav",
    "[DETERMINED]": "determined_whir.wav",
}


# ===================== VAD + RECORD =====================
def record_speech() -> Optional[np.ndarray]:
    """Listen for speech, record until silence. Returns float32 mono at 16kHz."""
    vad = webrtcvad.Vad(VAD_MODE)
    
    pre_buffer = []        # hold frames until speech detected
    speech_frames = []     # frames with speech
    silent_frames = 0
    silence_frames_thresh = int(SILENCE_SEC * 1000 / FRAME_MS)
    max_frames = int(MAX_RECORD_SEC * 1000 / FRAME_MS)
    has_speech = False

    def callback(indata, frames, time_info, status):
        nonlocal silent_frames, has_speech

        audio_16 = (indata[:, 0] * 32767).astype(np.int16)

        is_speech = vad.is_speech(audio_16.tobytes(), SAMPLE_RATE)

        if not has_speech:
            pre_buffer.append(audio_16)
            if len(pre_buffer) > 10:
                pre_buffer.pop(0)

        if is_speech:
            has_speech = True
            speech_frames.append(audio_16)
            silent_frames = 0
        elif has_speech:
            speech_frames.append(audio_16)
            silent_frames += 1

        if not has_speech and len(pre_buffer) > 10 and not any(
            vad.is_speech(f.tobytes(), SAMPLE_RATE) for f in pre_buffer[-5:]
        ):
            pre_buffer.clear()

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        callback=callback,
        blocksize=FRAME_SIZE,
    )

    with stream:
        while silent_frames < silence_frames_thresh and len(speech_frames) < max_frames:
            sd.sleep(50)

    if not speech_frames or len(speech_frames) < 15:
        return None

    audio = np.concatenate(pre_buffer[-4:] + speech_frames).astype(np.float32) / 32768.0
    return audio


# ===================== STT =====================
whisper_model = None  # lazy load

def stt(audio: np.ndarray) -> str:
    """Transcribe using faster-whisper tiny."""
    global whisper_model
    if whisper_model is None:
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")

    segments, _ = whisper_model.transcribe(audio, language=None, beam_size=5, vad_filter=False)
    text = " ".join(s.text for s in segments).strip()
    return text


# ===================== LLM =====================
def wall_e_chat(text: str) -> str:
    """Send to Ollama with WALL-E system prompt."""
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
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(result.stdout)
    return data.get("message", {}).get("content", "*confused beep* [CURIOUS]")


def extract_emotion(response: str) -> Tuple[str, Optional[str]]:
    """Extract [EMOTION] tag. Returns (clean_text, emotion_tag)."""
    import re
    match = re.search(
        r"\[(HAPPY|CURIOUS|EXCITED|SAD|COMPACT|SCARED|AMAZED|LOVE|DETERMINED)\]",
        response
    )
    if match:
        tag = f"[{match.group(1)}]"
        clean = response.replace(tag, "").strip()
        return clean, tag
    return response, None


# ===================== TTS + ROBOT FX =====================
kokoro = None
pedalboard_loaded = False

def _init_kokoro():
    global kokoro
    if kokoro is None:
        from kokoro_onnx import Kokoro
        kokoro = Kokoro(
            str(MODELS_DIR / "kokoro-v0_19.int8.onnx"),
            voices_path=str(MODELS_DIR / "voices.bin"),
        )

def tts_kokoro(text: str) -> Optional[np.ndarray]:
    """TTS with kokoro-onnx. Returns float32 audio at 24kHz."""
    try:
        _init_kokoro()
        samples, sample_rate = kokoro.create(
            text, voice="am_adam", speed=1.1, lang="en-us"
        )
        return samples
    except Exception as e:
        print(f"  ⚠️ TTS error: {e}")
        return None


def apply_robot_fx(audio: np.ndarray, sample_rate: int = 24000) -> np.ndarray:
    """Apply pedalboard effects for Wall-E robot voice."""
    try:
        from pedalboard import Pedalboard, PitchShift, Distortion, Reverb

        board = Pedalboard([
            PitchShift(semitones=4),          # Higher pitch (Wall-E is squeaky)
            Distortion(drive_db=3),           # Light crackle
            Reverb(room_size=0.2, wet_level=0.1),  # Slight presence
        ])
        return board(audio, sample_rate)
    except ImportError:
        return audio  # No effects if pedalboard missing
    except Exception as e:
        print(f"  ⚠️ FX error: {e}")
        return audio


# ===================== SFX PLAYBACK =====================
sfx_cache = {}

def play_sfx(emotion_tag: str):
    """Play pre-loaded SFX for emotion."""
    sfx_file = SFX_MAP.get(emotion_tag)
    if not sfx_file:
        return

    path = SFX_DIR / sfx_file
    if not path.exists():
        return

    if sfx_file not in sfx_cache:
        with wave.open(str(path), "rb") as wf:
            n_frames = wf.getnframes()
            audio = np.frombuffer(wf.readframes(n_frames), dtype=np.int16).astype(np.float32)
            audio /= 32768.0
            rate = wf.getframerate()
            sfx_cache[sfx_file] = (audio, rate)

    audio, rate = sfx_cache[sfx_file]
    sd.play(audio, rate)
    sd.wait()


def play_audio(audio: np.ndarray, sample_rate: int = 24000):
    """Blocking playback."""
    sd.play(audio, sample_rate)
    sd.wait()


def post_emotion_to_server(emotion: str, text: str = ""):
    """Send emotion to eye server (non-blocking, fire-and-forget)."""
    try:
        subprocess.run(
            ["curl", "-s", "-X", "POST", "http://127.0.0.1:8765/api/emotion",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"emotion": emotion.strip("[]"), "text": text})],
            timeout=0.5,
        )
    except Exception:
        pass  # Eye server may not be running — ok


# ===================== MAIN LOOP =====================
def main():
    print("=" * 60)
    print("  🤖  WALL-E Interactive Voice Chat")
    print(f"  Model: {OLLAMA_MODEL} | STT: faster-whisper tiny")
    print(f"  TTS: kokoro-onnx + pedalboard robot FX")
    print(f"  SFX: {len([f for f in SFX_DIR.glob('*.wav')])} files")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    sd.default.dtype = "float32"

    while True:
        try:
            # 1. Listen
            print("🎤 Listening...")
            audio = record_speech()
            if audio is None or len(audio) < 1000:
                continue

            # 2. STT
            print("  📝 Transcribing...")
            text = stt(audio)
            if not text:
                print("  → (no speech detected)")
                continue
            print(f"🧑 You: {text}")

            # 3. LLM
            print("  🧠 Thinking...")
            response = wall_e_chat(text)
            clean_text, emotion = extract_emotion(response)
            print(f"🤖 WALL-E: {clean_text} {emotion or ''}")

            # 4. Tell eye server
            if emotion:
                post_emotion_to_server(emotion, clean_text)

            # 5. SFX
            if emotion:
                play_sfx(emotion)

            # 6. TTS + Robot FX → Speaker
            if clean_text:
                print("  🔊 Speaking...")
                tts_audio = tts_kokoro(clean_text)
                if tts_audio is not None:
                    tts_audio = apply_robot_fx(tts_audio, 24000)
                    play_audio(tts_audio, 24000)

            print()

        except KeyboardInterrupt:
            print("\n\n🤖 WALL-E: *sad whir* ...goodbye... [SAD]")
            break
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
