# Wall-E Real-Time STT/TTS Research Notes
> Apple M4 Mac Mini · 16GB RAM · Fully Offline
> Generated: 2026-07-06

---

## 1. STT (Speech-to-Text): Latency Comparison

### Benchmark Summary for Short Utterances on M4

| Implementation | Model | Realtime Factor | 1s Audio | 3s Audio | Notes |
|---|---|---|---|---|---|
| **whisper.cpp** (Metal) | tiny (q5) | **~38×** | ~26ms | ~79ms | C++ binary. Fastest raw speed. CoreML/ANE optional for encoder. |
| **faster-whisper** (CTranslate2) | tiny (fp16) | **~27×** | ~37ms | ~111ms | Python-native. Well-tested, stable. Good Python integration. |
| **mlx-whisper** (Apple MLX) | tiny | **~25-30×** est. | ~33-40ms | ~100-120ms | Uses GPU/ANE via MLX. Python-native. Better GPU utilization, but overhead for very short chunks. |
| **faster-whisper** | base | 18× | ~56ms | ~167ms | Better accuracy, still sub-200ms. |

All three options easily achieve **sub-200ms** transcription latency for short utterances (1-5 seconds). Even the base model stays well under 500ms.

### Recommendation: **faster-whisper (tiny)** — already installed

**Why not mlx-whisper:**
- On M4, the raw speed gap between whisper.cpp Metal and mlx-whisper is small for tiny models.
- mlx-whisper has more Python dependency complexity (mlx, mlx-lm, etc.).
- For the tiny model specifically, the CTranslate2 backend in faster-whisper is extremely well-optimized and battle-tested.
- The Neural Engine advantage shows more for medium/large models, not tiny.

**Why not whisper.cpp directly:**
- Requires subprocess calls or ctypes bindings to the C++ binary.
- faster-whisper gives native Python integration with same CTranslate2 speed.
- Easier to integrate with the rest of the Python pipeline.

### Installation (if needed):
```bash
source /Users/pyu/.hermes/workspace/walle/venv/bin/activate
pip install faster-whisper
# Model auto-downloads on first use (~75MB for tiny)
```

---

## 2. TTS (Text-to-Speech): Wall-E Robot Voice

### Option A: kokoro-onnx (Installed ✓)

**Status:** kokoro-onnx 0.4.7 installed in walle venv.

**Model files needed:**
- `kokoro-v1.0.onnx` (~330MB fp32) or `kokoro-v0_19.int8.onnx` (~88MB quantized)
- `voices-v1.0.bin` or `voices.json` (voice embeddings ~100MB)

**Available voices (v1.0, 54 total):**
American English: `af_heart`, `af_bella`, `af_sarah`, `af_nicole`, `af_sky`, `af_alloy`, `af_aoede`, `af_jessica`, `af_kore`, `af_nova`, `af_river`, `am_adam`, `am_echo`, `am_eric`, `am_fenrir`, `am_liam`, `am_michael`, `am_onyx`, `am_puck`, `am_santa`
British English: `bf_alice`, `bf_emma`, `bf_isabella`, `bf_lily`, `bm_daniel`, `bm_fable`, `bm_george`, `bm_lewis`

**Best Wall-E-like voices to test:**
- `am_onyx` — deeper, more robotic tone
- `am_echo` — resonant, could sound mechanical
- `am_puck` — playful, possibly quirky like Wall-E
- `bm_george` or `bm_lewis` — British male, could be tweaked
- **Voice blending** is supported — mix two voices for custom tone (e.g., `am_onyx:0.7,am_echo:0.3`)

**Latency:** ~100-300ms for short sentences. Very fast.

### Option B: piper-tts (Alternative)

**Why it could be perfect for Wall-E:**
- Piper's voice quality is slightly robotic/less natural — which is IDEAL for a robot character.
- Significantly faster than kokoro on CPU (reported 2-5x realtime).
- Tiny models: `en_US-lessac-low.onnx` (~30MB), `en_US-amy-low.onnx` (~30MB).
- C++ backend with Python bindings via `piper-tts` package.

**Installation:**
```bash
pip install piper-tts
# Download voice model (e.g.):
# wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx
# wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx.json
```

**Recommendation:** Try BOTH. kokoro-onnx for natural/expressive voice, piper-tts for inherently robotic tone. Use whichever sounds more Wall-E-like after effects.

### Robot Voice Effects (Post-TTS)

**pedalboard** (Spotify) — **SUCCESSFULLY INSTALLED ✓**

```python
from pedalboard import Pedalboard, PitchShift, Distortion, RingModulator, Reverb
import soundfile as sf

# Wall-E robot voice chain
board = Pedalboard([
    # Slight pitch shift up (Wall-E has higher, squeaky voice)
    PitchShift(semitones=3),        # +3 semitones for higher pitch
    
    # Ring modulation for robotic/Dalek character
    RingModulator(
        frequency_hz=30,            # Low freq modulation = classic robot
        mix=0.35,                   # Blend 35% wet
    ),
    
    # Light distortion for "speaker" quality
    Distortion(drive_db=6),
    
    # Tiny bit of reverb for presence
    Reverb(room_size=0.15, wet_level=0.1),
])

# Apply to TTS output
audio, sample_rate = sf.read("tts_output.wav")
effected = board(audio, sample_rate)
sf.write("walle_voice.wav", effected, sample_rate)
```

**Key effects for Wall-E:**
1. **PitchShift** (+2 to +5 semitones) — Wall-E's voice is higher-pitched
2. **RingModulator** (20-50 Hz, mix 0.2-0.4) — core "robot" character
3. **Distortion** (light) — cheap speaker/crackle
4. **Bitcrush** (optional, via `Resample` to 8kHz then back) — retro digital feel
5. **Bandpass filter** (via `LowpassFilter` + `HighpassFilter`) — narrow "radio" voice

---

## 3. VAD (Voice Activity Detection)

| Option | Speed | Accuracy | Dependencies | Memory |
|---|---|---|---|---|
| **silero-vad** | Fast | Best (95%+) | PyTorch (~800MB) or ONNX | ~50MB |
| **silero-vad-lite** | Fast | Best | ONNX Runtime only | ~5MB |
| **webrtcvad** | Fastest | Good (85%) | None (pure Python binding) | ~1MB |

### Recommendation: **webrtcvad** for initial prototype, **silero-vad-lite** for production

**webrtcvad** is dead simple, zero-dependency, and extremely fast. Perfect for the initial pipeline. If false positives/negatives become an issue, upgrade to silero-vad-lite.

```bash
pip install webrtcvad
# or
pip install silero-vad-lite  # Pure ONNX, no PyTorch
```

### Wake Word vs VAD:

For Wall-E, **VAD-based pipeline is simpler and more responsive:**
- No wake word training needed
- Wall-E reacts as soon as speech is detected (more natural for a robot companion)
- Less latency (wake word adds 200-500ms)
- Optional: Add "Hey Wall-E" wake word later using `openwakeword` or `pvporcupine` if needed

---

## 4. Real-Time Pipeline Architecture

### Recommended: Simple Sequential (not streaming/async for MVP)

```
Microphone → VAD → [speech detected] → Record buffer → faster-whisper → LLM → kokoro/piper → pedalboard effects → Speaker
```

**Why sequential for MVP:**
- Simpler to debug and tune
- Turn-based interaction feels natural for Wall-E (robot pauses to "think")
- Total pipeline latency: VAD(50ms) + STT(100ms) + LLM(500-2000ms) + TTS(200ms) + effects(50ms) = ~1-3 seconds
- The LLM inference dominates — streaming STT/TTS doesn't help much here

### Pipeline details:

```python
import webrtcvad
import sounddevice as sd
import numpy as np

# 1. VAD detects speech
vad = webrtcvad.Vad(2)  # Aggressiveness 0-3
# 2. Record until silence (e.g., 800ms of no speech)
# 3. Transcribe with faster-whisper
# 4. Send to LLM → get response
# 5. Synthesize with kokoro-onnx
# 6. Apply pedalboard robot effects
# 7. Play through sounddevice
```

### Sample rate consistency:
- Microphone: 16000 Hz mono (16-bit)
- faster-whisper: 16000 Hz (native)
- kokoro-onnx: 24000 Hz (output)
- pedalboard effects: 24000 Hz
- Speaker playback: 24000 Hz

Use `sounddevice` for both input and output with appropriate resampling.

---

## 5. Memory Footprint Analysis (16GB Total)

| Component | Model Size (Disk) | RAM Usage (Runtime) |
|---|---|---|
| **qwen3:14b** (Q4_K_M GGUF) | ~8.5 GB | **~9-10 GB** |
| **faster-whisper** (tiny, fp16) | ~75 MB | **~1 GB** |
| **kokoro-onnx** (v1.0 fp32) | ~330 MB | **~500 MB** |
| **kokoro-onnx** (int8 quantized) | ~88 MB | **~200 MB** |
| **pedalboard effects** | — | **~50 MB** |
| **sounddevice buffers** | — | **~50 MB** |
| **macOS base** | — | **~2-3 GB** |
| **TOTAL (fp32 kokoro)** | | **~13-15 GB** |
| **TOTAL (int8 kokoro)** | | **~12.5-14 GB** |

### Verdict: **TIGHT but FEASIBLE** ⚠️

- With Q4_K_M qwen3:14b (~9GB) + tiny whisper (~1GB) + int8 kokoro (~200MB) + OS (~2.5GB) = **~12.7GB**
- Leaves ~3.3GB headroom, which is adequate but not generous.
- **Use quantized kokoro-onnx** (int8, ~88MB) to maximize headroom.
- Monitor with `memory_pressure` command during testing.
- If swapping occurs, options:
  - Drop to qwen3:8b (~5GB) — still good quality
  - Use piper-tts instead of kokoro (piper is even lighter)
  - Use whisper.cpp as subprocess (unloads between calls)

---

## 6. Summary: Recommended Stack

| Layer | Choice | Why |
|---|---|---|
| **VAD** | `webrtcvad` then `silero-vad-lite` | Fastest/lightest → upgrade if needed |
| **STT** | `faster-whisper` (tiny) | Installed, 27× realtime, sub-50ms for short phrases |
| **LLM** | `qwen3:14b` (Q4_K_M) | Already planned, ~9-10GB |
| **TTS** | `kokoro-onnx` (int8) + `piper-tts` fallback | Fast, 54 voices, try `am_onyx`/`am_echo` |
| **Robot FX** | `pedalboard` | Installed ✓, PitchShift + RingModulator + Distortion |
| **Audio I/O** | `sounddevice` | Installed ✓ |

---

## 7. Installation Commands (Complete)

```bash
source /Users/pyu/.hermes/workspace/walle/venv/bin/activate

# Already installed:
# - kokoro-onnx 0.4.7
# - sounddevice 0.5.5
# - pedalboard 0.9.23

# Install remaining:
pip install faster-whisper webrtcvad

# Optionally for higher accuracy VAD:
pip install silero-vad-lite

# Optionally for piper-tts alternative:
pip install piper-tts

# Download kokoro model files:
# cd /Users/pyu/.hermes/workspace/walle/models/
# wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/v1.0/kokoro-v1.0.onnx
# wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/v1.0/voices-v1.0.bin

# Or quantized version (smaller):
# wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.19/kokoro-v0_19.int8.onnx
# wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.19/voices.bin
```

---

## 8. Next Steps

1. **Install** faster-whisper, webrtcvad in the walle venv
2. **Download** kokoro model + voices files
3. **Test** kokoro voices → find most Wall-E-like (`am_onyx`, `am_echo`, `am_puck`)
4. **Build** pedalboard effects chain → tune PitchShift/RingModulator params
5. **Benchmark** end-to-end pipeline latency
6. **Monitor** memory pressure with all three models loaded
7. **Document** voice presets as Wall-E character profiles
