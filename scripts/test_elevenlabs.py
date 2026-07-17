#!/usr/bin/env python3
"""Quick ElevenLabs TTS test."""
import os, sys, io, numpy as np, time
from pathlib import Path

# Load API key from .env
project_root = Path(__file__).parent.parent
env_file = project_root / ".env"
for line in open(env_file):
    if line.startswith("ELEVENLABS_API_KEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

from elevenlabs.client import ElevenLabs
client = ElevenLabs(api_key=key)

# Test voice
text = "WALL-E! Directive?"
voice_id = "TX3LPaxmHKxFdv7VOQHJ"  # Liam

t0 = time.perf_counter()
audio_gen = client.text_to_speech.convert(
    voice_id=voice_id,
    text=text,
    model_id="eleven_flash_v2_5",
    output_format="pcm_24000",
)
audio_bytes = b"".join(audio_gen)
audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
ttfb = (time.perf_counter() - t0) * 1000
print(f"Liam | TTFT {ttfb:.0f}ms | dur {len(audio)/24000:.1f}s | samples {len(audio)}")

# Save wav for playback test
import wave
with wave.open(str(project_root / "test_output.wav"), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(24000)
    wf.writeframes(audio_bytes)
print("Saved test_output.wav")
