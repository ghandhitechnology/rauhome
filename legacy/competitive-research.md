# Competitive Research: Local LLM Robot Companion Projects

> **Research commissioned by:** Andy Ha (인천과학고 1학년)  
> **Target hardware:** Apple M4 Mac Mini, 16GB unified memory  
> **Current stack:** Ollama gemma3:12b, faster-whisper tiny, kokoro-onnx int8, pedalboard robot FX, Three.js eye UI, Python voice pipeline with webrtcvad  
> **Date:** July 2026  

---

## Executive Summary

Building a local LLM-powered WALL-E companion is an active space with several high-quality shipping projects. The key finding: **gemma3:12b may be too large for 16GB RAM** when running a full pipeline (STT + LLM + TTS + UI + effects). Several independent reports confirm OOM errors on Mac Mini M4 16GB with gemma3:12b even at Q4_0 quantization. The sweet spot for this hardware is **gemma3:4b or Qwen3:4b**, which deliver 40+ tok/s with ample headroom.

---

## Top 5 Most Relevant Projects

### 1. Open-LLM-VTuber (⭐ 11.2K) — The Gold Standard

**URL:** https://github.com/Open-LLM-VTuber/Open-LLM-VTuber  
**DeepWiki:** https://deepwiki.com/Open-LLM-VTuber/Open-LLM-VTuber

**What it is:** A voice-interactive AI companion with Live2D avatars. Fully offline, cross-platform (Windows/macOS/Linux). Supports voice interruption, visual perception, and desktop pet mode.

**Architecture (what to steal):**
- **ASR → LLM → TTS → Live2D animation pipeline**
- **Voice interruption** (barge-in): The system can interrupt itself mid-response if the user starts speaking — crucial for natural conversation feel
- **Live2D** face animation mapped to audio output and emotional state
- **Desktop pet mode** with always-on avatar overlay

**Key techniques:**
- Modular backend: swap any LLM (Ollama, vLLM, OpenAI-compatible), any ASR, any TTS
- Character system with configurable personalities
- Sensor-based expression mapping (audio amplitude → mouth movement, sentiment → expression)

**Pitfalls reported:** Cloud API backends are significantly lower latency than local; local pipeline has noticeable delay compared to OpenAI Advanced Voice (sub-500ms). The project acknowledges this trade-off.

---

### 2. Alisa — Fully Local Desktop AI Companion

**URL:** https://github.com/Kush05Bhardwaj/Alisa-AI_Local_LLM_Desktop_Companion

**What it is:** A fully local AI companion that combines an animated avatar, natural voice conversation, presence detection, and intelligent desktop integration. Everything runs on-device.

**Architecture (what to steal):**
- **Desktop overlay UI** with animated avatar
- **Presence detection** (user proximity awareness)
- **Voice pipeline** with hinglish/multilingual support
- **Backend in Python**, modular design

**Key techniques:**
- Desktop integration (screen reading, system control)
- Presence-aware behavior (avatar reacts to user being nearby)
- Modular voice system with language-specific guides

---

### 3. AIRI (⭐ 3K+) — Self-Hosted AI Companion with Gaming

**URL:** https://github.com/moeru-ai/airi

**What it is:** A self-hosted AI digital companion supporting real-time voice chat, autonomous gaming (Minecraft, Factorio), and 2D/3D character animation. Hit GitHub Trending #5 (March 2026, 3,006 stars).

**Architecture (what to steal):**
- **VAD + STT + LLM + TTS** pipeline
- **WebGPU-based** voice chat for browser performance
- **2D/3D character animation** system
- **DuckDB WASM** for local data storage

**Key techniques:**
- WebGPU for low-level GPU access in browser (better than WebGL for AI workloads)
- Modular companion framework
- Real-time voice interaction design patterns

---

### 4. HuggingFace speech-to-speech — Reference Pipeline Architecture

**URL:** https://github.com/huggingface/speech-to-speech  
**DeepWiki:** https://deepwiki.com/huggingface/speech-to-speech

**What it is:** Official reference implementation for local voice agents by HuggingFace. The most architecturally significant project for understanding how to build a production-grade voice pipeline.

**Architecture (MUST STUDY):**
```
┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐
│ VAD  │───→│ STT  │───→│ LLM  │───→│ TTS  │
│Silero│    │Moon- │    │Ollama│    │Kokoro│
│ v5   │    │shine │    │/HF   │    │/Parler│
└──────┘    └──────┘    └──────┘    └──────┘
   ↑           ↑            ↑           ↑
   └─── Each in its own thread, connected by queues ───┘
```

**Critical design decisions to steal:**
1. **Thread-per-component architecture** — Each stage runs in its own thread with queues between them. This prevents blocking and allows pipelining.
2. **Silero VAD v5** — Voice activity detection for speech boundaries and turn-taking. Chosen over WebRTC VAD for better accuracy with ML-based detection.
3. **Local mode** — Single-process deployment where audio I/O and inference run on the same machine. Ideal pattern for the WALL-E project.
4. **Streaming audio chunks** — Audio is accumulated until end-of-speech detected, then passed to STT. Live partial transcripts supported.

---

### 5. AgentVox / Chatty — Low-Latency STT-LLM-TTS Pipeline

**URLs:**
- https://github.com/MIMICLab/AgentVox (edge-based, Gemma LLM)
- https://github.com/mwtuni/chatty (modular, pluggable adapters)

**What they are:** Production-grade voice assistant pipelines with a focus on low latency.

**Architecture (what to steal):**
- **RealtimeSTT + RealtimeTTS** for streaming — dramatically reduces perceived latency vs batch processing
- **Pluggable LLM adapters** — Ollama adapter, OpenAI adapter, easily switchable
- **Streaming TTS** via RealtimeTTS's Kokoro engine — first audio chunk plays while LLM is still generating

**Key techniques:**
- `chatty` uses `pipeline.py` with configurable engine selection
- AgentVox specifically targets Gemma models on edge devices
- Streaming TTS reduces perceived latency by 40-60% vs waiting for full response

---

## Critical Hardware Reality Check: 16GB Memory Budget

### The gemma3:12b Problem

**Multiple independent sources confirm:** gemma3:12b causes OOM on Mac Mini M4 with 16GB RAM:

- **Stan370's test (Aug 2025):** "Running Gemma 3 on Mac mini M4 with only 16GB... kept hitting 500 errors — even Q4_0 quantization wasn't enough"
- **Medium report:** "Not Enough RAM! local Gemma3n vs Qwen3 on 16Gb device"
- **ai-on-mac.com:** Recommends 24-32GB for gemma3:12b with moderate context

### Realistic Memory Budget (16GB total)

| Component | Memory | Notes |
|-----------|--------|-------|
| macOS base | ~3-4 GB | System + WindowServer + browser |
| **Option A: gemma3:4b (Q4_K_M)** | ~3 GB | **RECOMMENDED** |
| Option B: gemma3:12b (Q4_K_M) | ~8 GB | OOM risk, zero headroom |
| Option C: Qwen3:4b | ~3 GB | Strong alternative |
| faster-whisper tiny | ~200 MB | Enough for Korean/English |
| kokoro-onnx int8 | ~200 MB | ONNX runtime is efficient |
| pedalboard + Python runtime | ~500 MB | Audio processing |
| Three.js eye UI (browser) | ~500 MB-1 GB | If running locally |
| **Total with 4B model** | **~7.5-9 GB** | **Comfortable, 7-8.5GB free** |
| **Total with 12B model** | **~12.5-14 GB** | **Danger zone, 2-3.5GB free** |

### Recommendation: **Switch to gemma3:4b or Qwen3:4b**

The 4B models running on Mac M4 deliver **40-80 tok/s** with Q4_K_M quantization — more than fast enough for conversational use. The quality difference between 4B and 12B is noticeable but acceptable for a character companion. The memory headroom is critical for:
- Running the browser-based eye UI
- Long conversation context (4K+ tokens)
- Future features (vision, memory, tool use)

---

## Latency Optimization: The Complete Picture

### Pipeline Latency Budget (best-case, Mac M4)

| Stage | Best Case | Typical | Optimization |
|-------|-----------|---------|--------------|
| VAD (Silero) | 20ms | 30-80ms | Silero v5, frame-level processing |
| STT (faster-whisper tiny) | 50ms | 100-300ms | Metal GPU acceleration, tiny model |
| LLM TTFT (gemma3:4b) | 300ms | 500-800ms | OLLAMA_KEEP_ALIVE=-1 (pre-loaded) |
| LLM generation (40 tok/s) | 500ms (20 tok) | 1-2s (40-80 tok) | Streaming output, short responses |
| TTS first chunk (kokoro-onnx) | 30ms | 50-100ms | ONNX NEON SIMD on ARM64 |
| **Total best case** | **~900ms** | | STT→LLM→TTS sequential |
| **Total pipelined** | **~600ms** | | STT + TTS overlap with LLM streaming |

### Key Latency Optimizations Found

1. **Keep model loaded:** `OLLAMA_KEEP_ALIVE=-1` or `ollama run --keepalive -1` — eliminates 5-30s cold start
2. **ONNX Runtime on ARM64:** 4-10x faster than PyTorch for Kokoro TTS (NEON SIMD instructions)
3. **Streaming TTS:** Start playing audio while LLM is still generating (RealtimeTTS pattern)
4. **faster-whisper with CTranslate2:** 4x faster than openai/whisper, Metal-accelerated on Apple Silicon
5. **Silero VAD v5:** Better accuracy than WebRTC VAD (<2MB model, >95% accuracy, real-time CPU)
6. **Thread-per-component:** Parallel execution prevents blocking (HF speech-to-speech pattern)
7. **Short, character-appropriate responses:** Prompt engineering for concise WALL-E dialogue reduces generation tokens

### Voice Pipeline Optimization (Python 2026 Best Practices)

From the **Gladia concurrent pipelines** guide and **LiveKit voice agent architecture**:

- **Streaming partial transcripts** from STT instead of waiting for final — LLM can start processing sooner
- **Token-level TTS streaming** — TTS generates first audio chunk from first few LLM tokens
- **Overlap LLM generation with TTS** — Thread 1 runs LLM, Thread 2 consumes tokens for TTS
- **Audio chunk size:** 20-40ms frames for VAD, 100-300ms for STT processing

---

## Robot Voice Effects: What Works for WALL-E

### Proven WALL-E Voice Chain (Pedalboard)

Based on the **Robot Voice Effect Tutorial** (VoxBooster, May 2026) and **Dalek voice experiments** (Raspberry Pi StackExchange):

```python
from pedalboard import Pedalboard, Bitcrush, PitchShift, Distortion, Reverb
from pedalboard.io import AudioStream

# WALL-E signature chain
board = Pedalboard([
    # 1. Pitch shift up (WALL-E is higher-pitched)
    PitchShift(semitones=+3),          # Shift up 3 semitones
    
    # 2. Bitcrush for that digital/robot texture
    Bitcrush(bit_depth=8),             # 8-bit gives classic robot crunch
    
    # 3. Light distortion for warmth
    Distortion(drive_db=5),            # Subtle drive, not full metal
    
    # 4. Small room reverb for presence
    Reverb(room_size=0.2, wet_level=0.3, dry_level=0.8),
])

# Real-time streaming
with AudioStream(input_device_name=None, output_device_name=None) as stream:
    stream.plugins = board
    # Stream audio through effects in real-time
```

**Alternative effects to experiment with:**
- Ring Modulation (for more mechanical sound)
- Chorus (subtle, for "character")
- Compressor (even out TTS output before effects)
- LowpassFilter (cut above 4-8kHz for lo-fi robot)

**Key insight:** Apply effects to TTS output, not microphone input. The cleaner the source audio, the better the effect chain sounds.

---

## Expression/Animation Systems

### Three.js Eye UI (Current Approach) — Validated

Multiple successful projects use Three.js/browser-based rendering for robot expressions:
- **"AI robot built with window.ai and three.js"** (robot-companion on Vercel, 2023) — Three.js robot that can move, emote, and change expressions
- **Alisa** — Desktop overlay with animated avatar
- **Open-LLM-VTuber** — Live2D with expression mapping

### Expression State Machine (Proven Pattern)

Based on the **Ani-Emo-Eye project** (ESP32 OLED, sentiment-driven) and **companion robot with LLM** paper (MDPI):

```
States:
  IDLE        → Eyes half-closed, occasional blink, "sleepy WALL-E"
  LISTENING   → Eyes wide, slight tilt, "attentive"
  THINKING    → Eyes looking up/side, animated "processing" (spinning gears)
  SPEAKING    → Eyes animated with audio amplitude, "talking"
  HAPPY       → Eyes curved up (^_^), brighter
  SAD         → Eyes drooping, dimmer
  CONFUSED    → One eye bigger than other, tilt
  EXCITED     → Eyes wide, vibrating, brighter

Triggers:
  - VAD active → LISTENING
  - STT processing → THINKING  
  - LLM generating → THINKING (with streaming for fluid transition)
  - TTS playing → SPEAKING (mouth sync via amplitude)
  - Sentiment from LLM response → HAPPY/SAD/EXCITED
  - No activity for 10s → IDLE (occasional blinks)
  - Error detected → CONFUSED
```

### LLM-Driven Expression Extraction

**Pattern from academic papers** (MDPI companion robot, 2025): Extract emotional metadata from LLM responses:

```python
# Add to system prompt
"You are WALL-E. Prefix every response with an emotion tag in brackets 
followed by the response: [neutral] ..., [happy] ..., [sad] ..., 
[excited] ..., [curious] ..."

# Parse emotion tag from response
# Map to expression state + eye animation parameters
```

---

## VAD vs Wake Word Decision

### Research Findings

| Aspect | VAD-only (Silero) | Wake Word |
|--------|-------------------|-----------|
| Latency to activation | ~30ms | ~200-500ms |
| False positives | Higher (TV, background noise) | Very low |
| Memory overhead | ~2MB (Silero v5) | ~5-50MB (Porcupine, snowboy) |
| Natural feel | More natural, interruptible | More deliberate |
| Best for | Continuous conversation | Command-based | 

### Recommendation: **VAD + Optional Push-to-Talk**

For a WALL-E companion that feels alive and responsive:
- **Silero VAD v5** for always-listening mode (WALL-E is always curious)
- **Push-to-talk button** as fallback for noisy environments
- **End-of-speech detection** with configurable silence duration (500ms-1.5s)
- Wake word only if targeting Home Assistant-like "Hey WALL-E" activation

---

## Multi-Model Orchestration Patterns

### What the Best Projects Do

1. **HF speech-to-speech:** Thread per model, queue-based communication
2. **Open-LLM-VTuber:** Plugin architecture — swap any model at any position
3. **Chatty:** Adapter pattern — `llm_ollama_adapter.py`, `llm_openai_adapter.py`

### Recommended Pattern for WALL-E

```python
# architecture.py
from queue import Queue
from threading import Thread

stt_queue = Queue()   # audio chunks → STT text
llm_queue = Queue()   # STT text → LLM response tokens
tts_queue = Queue()   # LLM tokens → TTS audio
expression_queue = Queue()  # LLM tokens/metadata → eye animation

# Component threads
Thread(target=vad_loop, args=(stt_queue,))
Thread(target=stt_loop, args=(stt_queue, llm_queue))
Thread(target=llm_loop, args=(llm_queue, tts_queue, expression_queue))
Thread(target=tts_loop, args=(tts_queue,))
Thread(target=expression_loop, args=(expression_queue,))
```

---

## Ollama Memory Management Strategies

### Command-Line / Env Var Controls

```bash
# Keep model loaded indefinitely (no unload after 5 min default)
export OLLAMA_KEEP_ALIVE=-1

# Limit concurrent models (critical for 16GB)
export OLLAMA_MAX_LOADED_MODELS=1

# Set parallelism (keep at 1 for single-user WALL-E)
export OLLAMA_NUM_PARALLEL=1

# Pre-load model at startup (in systemd or launchd)
ollama run gemma3:4b ""  # loads model, empty prompt exits
```

### API-Level Keep-Alive

```python
import ollama

# On startup: load and pin model
ollama.chat(
    model='gemma3:4b',
    messages=[{'role': 'user', 'content': ''}],
    keep_alive=-1  # Never unload
)

# Or: periodic ping to keep alive
import asyncio
async def keep_alive_ping():
    while True:
        await asyncio.sleep(240)  # every 4 minutes
        ollama.chat(model='gemma3:4b', 
                    messages=[{'role': 'user', 'content': 'ping'}],
                    keep_alive=-1)
```

### Memory Monitoring

```bash
# Check what's loaded
ollama ps

# Memory pressure on Mac
memory_pressure  # macOS command
vm_stat           # Detailed breakdown
```

---

## Benchmarks Summary

### STT: faster-whisper on Apple Silicon (M4)

| Model | Size | Speed (relative) | Memory | WER (English) |
|-------|------|------------------|--------|---------------|
| tiny | 39M | 1x (fastest) | ~75MB | ~7% |
| base | 74M | ~0.7x | ~150MB | ~5% |
| small | 244M | ~0.35x | ~500MB | ~3.5% |

**Recommendation:** `tiny` is sufficient for Korean-accented English. If accuracy issues, upgrade to `base`.

### LLM: Gemma3 on Mac M4

| Model | Quant | Tok/s (M4) | TTFT | RAM | Viable for 16GB? |
|-------|-------|------------|------|-----|------------------|
| gemma3:4b | Q4_K_M | 50-80 | ~400ms | ~3GB | ✅ YES |
| gemma3:12b | Q4_K_M | 30-40 | ~1.3s | ~8GB | ⚠️ TIGHT |
| Qwen3:4b | Q4_K_M | 45-70 | ~350ms | ~3GB | ✅ YES |

### TTS: Kokoro-onnx

| Metric | Value |
|--------|-------|
| Model size | 82M params (~86MB ONNX) |
| Inference (CPU) | <50ms per utterance |
| ONNX ARM64 speedup | 4-10x vs PyTorch |
| Voice quality | Near ElevenLabs for short utterances |
| Real-time factor | >100x real-time |

---

## What We Should Steal (Actionable Items)

### Immediately:
1. **Switch to gemma3:4b or Qwen3:4b** — 12B is too tight for 16GB
2. **Set `OLLAMA_KEEP_ALIVE=-1`** — eliminate cold-start latency
3. **Silero VAD v5** — replace webrtcvad for better accuracy
4. **Threaded pipeline** — HF speech-to-speech architecture (queue-based)
5. **Streaming TTS** — kokoro-onnx can start playing before LLM finishes

### Short-term:
6. **Expression state machine** — IDLE/LISTENING/THINKING/SPEAKING/EMOTION states
7. **LLM emotion tag extraction** — parse [emotion] prefix from responses
8. **Pedalboard AudioStream** — real-time effects instead of post-processing
9. **Ollama pre-load on startup** — systemd/launchd or Python startup script
10. **Memory monitoring** — log memory pressure during conversations

### Medium-term:
11. **Barge-in/interruption** — Open-LLM-VTuber pattern for natural conversation
12. **Presence detection** — Alisa's approach (camera or proximity sensor)
13. **Desktop overlay** — Alisa-style floating avatar window
14. **Live2D or more sophisticated eye rig** — Open-LLM-VTuber's approach
15. **WebGPU Three.js** — AIRI's approach for better browser GPU performance

---

## Sources

1. Open-LLM-VTuber — GitHub (11.2K stars) — https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
2. Alisa AI Desktop Companion — https://github.com/Kush05Bhardwaj/Alisa-AI_Local_LLM_Desktop_Companion
3. AIRI Self-Hosted AI Companion — https://github.com/moeru-ai/airi
4. HuggingFace speech-to-speech — https://github.com/huggingface/speech-to-speech
5. AgentVox / MIMICLab — https://github.com/MIMICLab/AgentVox
6. Chatty low-latency pipeline — https://github.com/mwtuni/chatty
7. "Not Enough RAM! Gemma3n vs Qwen3 on 16Gb" — Stan370 blog post, Aug 2025
8. Gemma 3 on Mac: RAM, Models & Ollama — https://ai-on-mac.com/articles/gemma3-mac-setup/
9. InsiderLLM Voice Chat Guide — https://insiderllm.com/guides/voice-chat-local-llms-whisper-tts/
10. Local Voice AI Stack on Apple Silicon (dev.to) — https://dev.to/xadenai/
11. Whisper.cpp vs faster-whisper 2026 Benchmarks — promptquorum.com
12. 2026 Local STT on Apple Silicon Mac — macgpu.com
13. Gladia Concurrent Pipelines for Voice AI — gladia.io
14. LiveKit Voice Agent Architecture — livekit.com
15. Picovoice VAD Comparison 2026 — picovoice.ai
16. Robot Voice Effect Tutorial (VoxBooster) — voxbooster.com, May 2026
17. Pedalboard + Dalek voice — Raspberry Pi StackExchange, May 2026
18. Ani-Emo-Eye Project — osrtos.com, Feb 2026
19. Companion Robot with LLM-Based Emotional Expression — MDPI Applied Sciences, Dec 2025
20. Ollama RAM Management Guide — https://github.com/jameschrisa/Ollama_Tuning_Guide
21. Make Magazine "Hey Robot!" — makezine.com, Oct 2024
22. WALL-E replica (chillibasket) — https://github.com/chillibasket/walle-replica
23. Ollama Gemma3:12b benchmark — ollamatps.com, llmcheck.net
