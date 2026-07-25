#!/usr/bin/env python3
"""WALL-E Voice Pipeline v2 — Threaded, Streaming, Production-Grade

Architecture (HF speech-to-speech pattern):
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ VAD      │───→│ STT      │───→│ LLM      │───→│ TTS      │
  │ Silero v5│    │f-whisper │    │DeepSeek  │    │kokoro+FX │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘
       ↑               ↑               ↑               ↑
       └─── Each in its own thread, connected by queues ───┘

Improvements over v1:
  - DeepSeek v4 Flash (cloud) — no local model needed
  - Silero VAD v5 instead of webrtcvad — better accuracy
  - Threaded pipeline — no blocking between stages
  - Streaming TTS — first audio chunk plays while LLM generates
  - Bitcrush in robot FX chain
  - Expression state machine (IDLE/LISTEN/THINK/SPEAK/EMOTE)
  - ffmpeg audio capture (bypasses macOS mic permission for Python)
  - ElevenLabs flash TTS (replaces Piper)

Usage:
  source venv/bin/activate
  python3 scripts/voice-pipeline-v2.py
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Event
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd

# Keep model loaded forever

# ===================== CONFIG =====================
PROJECT_ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = PROJECT_ROOT / "prompts" / "system-prompt.md"
SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
MODELS_DIR = PROJECT_ROOT / "models"
DEEPSEEK_MODEL = "deepseek-chat"

SAMPLE_RATE = 16000
TTS_SAMPLE_RATE = 24000
SILENCE_SEC = 1.2
MAX_RECORD_SEC = 8

# ===================== SFX MAP =====================
SFX_MAP = {
    "[HAPPY]": "curious_beep.wav",
    "[CURIOUS]": "curious_beep.wav",
    "[EXCITED]": "excited_trill.wav",
    "[SAD]": "sad_whir.wav",
    "[COMPACT]": "compacting.wav",
    "[SCARED]": "scared_beep.wav",
    "[AMAZED]": "whoa.wav",
    "[LOVE]": "eva_sigh.wav",
    "[DETERMINED]": "determined_whir.wav",
}

# ===================== EXPRESSION STATE MACHINE =====================
EXPRESSION_URL = "http://127.0.0.1:8765/api/emotion"


def post_expression(state: str, text: str = ""):
    """Send expression state to eye server (fire-and-forget)."""
    try:
        subprocess.run(
            ["curl", "-s", "-X", "POST", EXPRESSION_URL,
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"emotion": state, "text": text})],
            timeout=0.3,
        )
    except Exception:
        pass


def expression_state_machine(state: str, text: str = ""):
    """Manage expression transitions."""
    states = {
        "listening": "CURIOUS",
        "thinking": "DETERMINED",
        "speaking": "idle",  # eyes animate via TTS amplitude
        "idle": "idle",
    }
    emotion = states.get(state, "idle")
    post_expression(emotion, text)


def _log_to_server(role: str, text: str):
    """Send chat log entry to eye server (fire-and-forget)."""
    try:
        subprocess.run(
            ["curl", "-s", "-X", "POST", "http://127.0.0.1:8765/api/log",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"role": role, "text": text})],
            timeout=0.5,
        )
    except Exception:
        pass


# ===================== VAD + RECORD (ffmpeg capture + Silero v5) =====================
_vad_model = None


def get_vad():
    global _vad_model
    if _vad_model is None:
        try:
            from silero_vad import VADIterator, load_silero_vad
            _vad_model = load_silero_vad(onnx=True)
        except ImportError:
            print("  ⚠️ Silero VAD not found, falling back to energy-based VAD")
            return None
    return _vad_model


def _open_ffmpeg_stream():
    """Open ffmpeg as audio source (bypasses macOS mic permission issue with Python)."""
    proc = subprocess.Popen(
        [
            "ffmpeg", "-f", "avfoundation", "-i", ":0",
            "-ar", str(SAMPLE_RATE), "-ac", "1",
            "-af", "volume=16dB",  # boost for quiet USB mics (e.g. Britz BZ-PM10)
            "-f", "s16le", "-bufsize", "1024", "-",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return proc


def record_speech() -> Optional[np.ndarray]:
    """Listen for speech using ffmpeg capture + Silero VAD, record until silence."""
    model = get_vad()

    print("🎤 Listening (ffmpeg)...")

    proc = _open_ffmpeg_stream()
    frame_size = 512  # 32ms at 16kHz
    bytes_per_frame = frame_size * 2  # int16 = 2 bytes

    if model is not None:
        return _record_silero_ffmpeg(model, proc, frame_size, bytes_per_frame)
    else:
        return _record_energy_ffmpeg(proc, frame_size, bytes_per_frame)


def _record_silero_ffmpeg(model, proc, frame_size, bytes_per_frame):
    """Silero VAD v5 with ffmpeg audio capture."""
    speech_buffer = []
    silent_frames = 0
    silence_thresh = int(SILENCE_SEC * 1000 / 32)
    has_speech = False
    audio_buffer = []
    max_frames = int(MAX_RECORD_SEC * 1000 / 32)

    try:
        while silent_frames < silence_thresh and len(speech_buffer) < max_frames:
            raw = proc.stdout.read(bytes_per_frame)
            if len(raw) < bytes_per_frame:
                break
            chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            import torch
            tensor_chunk = torch.from_numpy(chunk)
            speech_prob = model(tensor_chunk, SAMPLE_RATE).item()

            audio_buffer.append(chunk)
            if len(audio_buffer) > 30:
                audio_buffer.pop(0)

            if speech_prob > 0.5:
                if not has_speech:
                    speech_buffer.extend(audio_buffer[-10:])
                has_speech = True
                speech_buffer.append(chunk)
                silent_frames = 0
            elif has_speech:
                speech_buffer.append(chunk)
                silent_frames += 1
    finally:
        proc.kill()
        proc.wait()

    if not speech_buffer or len(speech_buffer) < 10:
        return None
    return np.concatenate(speech_buffer)


def _record_energy_ffmpeg(proc, frame_size, bytes_per_frame):
    """Fallback: energy-based VAD with ffmpeg capture."""
    speech_buffer = []
    silent_frames = 0
    silence_thresh = int(SILENCE_SEC * 1000 / 32)
    has_speech = False
    max_frames = int(MAX_RECORD_SEC * 1000 / 32)
    energy_threshold = 0.015  # RMS threshold for speech detection

    try:
        while silent_frames < silence_thresh and len(speech_buffer) < max_frames:
            raw = proc.stdout.read(bytes_per_frame)
            if len(raw) < bytes_per_frame:
                break
            chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = np.sqrt(np.mean(chunk ** 2))

            if rms > energy_threshold:
                has_speech = True
                speech_buffer.append(chunk)
                silent_frames = 0
            elif has_speech:
                speech_buffer.append(chunk)
                silent_frames += 1
    finally:
        proc.kill()
        proc.wait()

    if not speech_buffer or len(speech_buffer) < 10:
        return None
    return np.concatenate(speech_buffer)


# ===================== STT =====================
_whisper_model = None

def stt(audio: np.ndarray) -> str:
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        # small: much better Korean + English WER than tiny.
        # M4 CPU: ~600ms first-token, ~2x slower than tiny but acceptable
        # for Wall-E's character; tiny is too lossy for Rocky voice intent.
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = _whisper_model.transcribe(audio, language=None, beam_size=5, vad_filter=False)
    return " ".join(s.text for s in segments).strip()


# ===================== LLM =====================
def _load_deepseek_key():
    """Load DeepSeek API key from .env or env var."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in open(env_file):
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'").strip("'")
                    break
    return key

DEEPSEEK_API_KEY = _load_deepseek_key()
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"



def wall_e_chat_stream(text: str):
    """Stream LLM response from DeepSeek v4 Flash. Yields (token_text, is_final).

    On the final token, re-emit a corrected (asterisk-stripped) full text
    because the model may still emit markdown emphasis; cleaner can't
    operate on raw streaming tokens without seeing pairs.
    """
    import re as _re
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set in .env or environment")

    with open(SYSTEM_PROMPT) as f:
        system = f.read()

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "stream": True,
        "max_tokens": 200,
        "temperature": 0.9,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        DEEPSEEK_BASE_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    resp = urllib.request.urlopen(req, timeout=30)

    accum = []
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="ignore").rstrip("\n")
        if not line.startswith("data:"):
            continue
        payload_str = line[len("data:"):].strip()
        if payload_str == "[DONE]":
            break
        try:
            chunk = json.loads(payload_str)
        except json.JSONDecodeError:
            continue
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        token = delta.get("content", "") or ""
        finish_reason = choice.get("finish_reason")
        done = finish_reason is not None
        if token:
            accum.append(token)
            yield token, done
        if done:
            full = "".join(accum)
            cleaned = _re.sub(r'\*([^*\n]{1,80}?)\*', r'\1', full)
            cleaned = _re.sub(r'\*+', '', cleaned)
            if cleaned != full:
                yield cleaned, True
            break


def extract_emotion(response: str) -> Tuple[str, Optional[str]]:
    match = re.search(
        r"\[(HAPPY|CURIOUS|EXCITED|SAD|COMPACT|SCARED|AMAZED|LOVE|DETERMINED)\]",
        response
    )
    if match:
        tag = f"[{match.group(1)}]"
        clean = response.replace(tag, "").strip()
        return clean, tag
    return response, None


# ===================== TTS + ROBOT FX (ElevenLabs) =====================
import sys as _sys
_scripts_dir = str(Path(__file__).parent)
if _scripts_dir not in _sys.path:
    _sys.path.insert(0, _scripts_dir)
from elevenlabs_tts import tts_elevenlabs


def apply_robot_fx(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Wall-E voice: PitchShift + Bitcrush + Distortion + Reverb."""
    try:
        from pedalboard import Pedalboard, PitchShift, Bitcrush, Distortion, Reverb
        board = Pedalboard([
            PitchShift(semitones=4),
            Bitcrush(bit_depth=8),
            Distortion(drive_db=4),
            Reverb(room_size=0.2, wet_level=0.1, dry_level=0.9),
        ])
        return board(audio, sample_rate)
    except Exception as e:
        print(f"  ⚠️ FX error: {e}")
        return audio


# ===================== SFX =====================
_sfx_cache = {}

def play_sfx(emotion_tag: str):
    sfx_file = SFX_MAP.get(emotion_tag)
    if not sfx_file or not (SFX_DIR / sfx_file).exists():
        return
    if sfx_file not in _sfx_cache:
        with wave.open(str(SFX_DIR / sfx_file), "rb") as wf:
            audio = np.frombuffer(
                wf.readframes(wf.getnframes()), dtype=np.int16
            ).astype(np.float32) / 32768.0
            _sfx_cache[sfx_file] = (audio, wf.getframerate())
    audio, rate = _sfx_cache[sfx_file]
    sd.play(audio, rate)
    sd.wait()


# ===================== THREADED PIPELINE =====================
class WallePipeline:
    """Threaded pipeline: VAD→STT→LLM→TTS — each stage in its own thread."""

    def __init__(self):
        self.audio_queue = Queue(maxsize=1)
        self.text_queue = Queue(maxsize=1)
        self.tts_tokens = Queue(maxsize=10)
        self.stop_event = Event()

    def record_thread(self):
        """Thread 1: VAD + recording → audio_queue."""
        while not self.stop_event.is_set():
            expression_state_machine("listening")
            print("🎤 Listening...")
            audio = record_speech()
            if audio is not None and len(audio) > 1000:
                expression_state_machine("thinking")
                self.audio_queue.put(audio)

    def stt_thread(self):
        """Thread 2: STT → text_queue."""
        while not self.stop_event.is_set():
            try:
                audio = self.audio_queue.get(timeout=0.5)
                print("  📝 Transcribing...")
                text = stt(audio)
                if text:
                    print(f"🧑 You: {text}")
                    _log_to_server("user", text)
                    self.text_queue.put(text)
            except Empty:
                continue

    def llm_tts_thread(self):
        """Thread 3: LLM (streaming) → TTS tokens + SFX + playback."""
        while not self.stop_event.is_set():
            try:
                text = self.text_queue.get(timeout=0.5)
                print("  🧠 Thinking...")

                full_response = ""
                emotion = None

                # Stream LLM response
                for token, done in wall_e_chat_stream(text):
                    full_response += token
                    if done:
                        clean_text, emotion = extract_emotion(full_response)
                        print(f"🤖 WALL-E: {clean_text} {emotion or ''}")

                        # SFX first
                        if emotion:
                            post_expression(emotion.strip("[]"), clean_text)
                            play_sfx(emotion)

                        # TTS + FX + Play
                        if clean_text:
                            expression_state_machine("speaking")
                            print("  🔊 Speaking...")
                            result = tts_elevenlabs(clean_text)
                            if result is not None:
                                tts_audio, tts_sr = result
                                tts_audio = apply_robot_fx(tts_audio, tts_sr)
                                play_audio(tts_audio, tts_sr)

                        expression_state_machine("idle")
                        print()

            except Empty:
                continue

    def start(self):
        """Launch all threads."""
        threads = [
            Thread(target=self.record_thread, daemon=True, name="VAD"),
            Thread(target=self.stt_thread, daemon=True, name="STT"),
            Thread(target=self.llm_tts_thread, daemon=True, name="LLM-TTS"),
        ]
        for t in threads:
            t.start()

        print("=" * 60)
        print(f"  🤖  WALL-E Voice Pipeline v2")
        print(f"  Model: {DEEPSEEK_MODEL} | VAD: Silero v5")
        print(f"  STT: faster-whisper tiny | TTS: elevenlabs flash + Bitcrush")
        print(f"  SFX: {len([f for f in SFX_DIR.glob('*.wav')])} files")
        print(f"  Arch: Threaded pipeline (HF speech-to-speech)")
        print("  Press Ctrl+C to stop")
        print("=" * 60)
        print()

        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\n🤖 WALL-E: *sad whir* ...goodbye... [SAD]")
            self.stop_event.set()


def play_audio(audio: np.ndarray, sample_rate: int = 24000):
    sd.play(audio, sample_rate)
    sd.wait()


# ===================== PRE-WARM =====================
def prewarm_all():
    """Pre-load all models at startup to eliminate cold-start latency."""
    print("🔥 Pre-warming models...")
    t0 = time.perf_counter()

    # 1. STT warm
    print("  📝 STT (faster-whisper small)...")
    global _whisper_model
    from faster_whisper import WhisperModel
    _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    dummy = np.random.randn(16000).astype(np.float32) * 0.01
    list(_whisper_model.transcribe(dummy, language="en", beam_size=1, vad_filter=False))

    # 2. TTS warm
    print("  🔊 TTS (elevenlabs flash)...")
    from elevenlabs_tts import warmup as warmup_tts
    warmup_tts()

    # 3. LLM warm (ping via DeepSeek)
    print("  🧠 LLM (deepseek-chat via DeepSeek API)...")
    if not DEEPSEEK_API_KEY:
        print("  ⚠️  DEEPSEEK_API_KEY not set — skipping LLM warm")
    else:
        data = json.dumps({
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": "ping"},
                {"role": "user", "content": "pong"}
            ],
            "max_tokens": 1,
            "temperature": 0.0,
        }).encode()
        req = urllib.request.Request(
            DEEPSEEK_BASE_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=15)
        print("  ✅ DeepSeek reachable")

    # 4. FX warm
    print("  🎛️  FX (pedalboard)...")
    from pedalboard import Pedalboard, PitchShift, Bitcrush, Distortion, Reverb
    board = Pedalboard([PitchShift(semitones=4), Bitcrush(bit_depth=8),
                        Distortion(drive_db=4), Reverb(room_size=0.2)])
    board(np.zeros(1000, dtype=np.float32), 16000)

    print(f"  ✅ All models warm ({((time.perf_counter()-t0)*1000):.0f}ms)")
    print()


# ===================== MAIN =====================
def main():
    sd.default.dtype = "float32"
    prewarm_all()
    pipeline = WallePipeline()
    pipeline.start()


if __name__ == "__main__":
    main()
