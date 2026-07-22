# Rau Home

A voice-controlled companion robot that runs on a Mac mini (Apple M4, 16 GB) sitting in a
home, with a microphone, speaker, and display plugged directly into it. You talk to it, it
listens, thinks for a moment, and replies in a robot voice with beeps, whirs, and animated
eyes on a local web page.

The project started as a WALL-E build; the current persona is Rocky (an engineer-scientist
character inspired by *Project Hail Mary*), defined in `prompts/system-prompt.md`.

This repository is the deployment source only. It deliberately excludes machine-local state:
API keys, downloaded models, sound-effect files, timing history, and memories are all
gitignored.

## How it works

The main entry point is `scripts/voice-pipeline-v2.py`, a threaded pipeline where each stage
runs in its own thread and stages hand off through queues:

```
Mic (ffmpeg capture) → Silero VAD v5 → faster-whisper (STT)
    → DeepSeek API (LLM, streaming) → emotion tag parse → SFX overlay
    → ElevenLabs flash TTS → pedalboard robot FX → Speaker
```

- **Audio capture** — ffmpeg (`avfoundation`) reads the mic directly, which sidesteps the
  macOS microphone-permission problems Python has.
- **Voice activity detection** — Silero VAD v5, with an energy-based fallback if the
  `silero-vad` package is missing.
- **Speech-to-text** — faster-whisper, `small` model on CPU (int8). Handles Korean and
  English; `small` was chosen over `tiny` because Korean accuracy matters.
- **LLM** — DeepSeek (`deepseek-chat`) over the cloud API, streaming, with the character
  system prompt. The reply ends with an emotion tag like `[HAPPY]` or `[CURIOUS]`.
- **Emotion tags** — parsed out of the reply and mapped to a sound effect
  (`assets/sfx/*.wav`) and an eye expression on the web UI.
- **Text-to-speech** — ElevenLabs `eleven_flash_v2_5`, then a pedalboard FX chain (pitch
  shift, bitcrush, distortion, reverb) to make it sound like a robot instead of a person.

A note on "offline": the original goal was a fully local build, and earlier iterations in
this repo (Ollama + kokoro-onnx) did exactly that. The current pipeline moved the LLM and
TTS to cloud APIs for quality and latency, so it needs internet access and two API keys.
Audio capture, VAD, STT, and all sound effects still run locally on the machine.

## Repository layout

- `launch.sh` — one-command launcher (see below)
- `scripts/voice-pipeline-v2.py` — the current voice pipeline (this is what actually runs)
- `scripts/eye-server.py` — local web server on `http://127.0.0.1:8765`
- `scripts/llm.py` — DeepSeek backend, streaming and non-streaming
- `scripts/elevenlabs_tts.py` — ElevenLabs TTS client
- `scripts/engine.py`, `scripts/cache.py` — keyword-matched response cache for instant
  replies to common inputs, bypassing the LLM
- `scripts/profile.py` — per-stage latency profiling for the pipeline
- `scripts/voice-pipeline.py`, `scripts/voice-chat.py`, `scripts/launch.py`,
  `scripts/test-chat.py` — earlier iterations kept for reference (local Ollama + kokoro
  stack); not the current path
- `prompts/` — character system prompts
- `dashboard/` — control dashboard served by the eye server (chat log, emotion state,
  status, controls)
- `ui/eyes.html` — the original standalone eye-animation page, used as a fallback if
  `dashboard/` is absent
- `research-notes.md`, `competitive-research.md` — dated background research from the
  planning phase; useful context, but describe earlier stacks, not the current one

## Quick start

Full setup details are in [SETUP.md](SETUP.md). In short:

```bash
python3 -m venv venv && source venv/bin/activate
pip install numpy sounddevice faster-whisper silero-vad torch pedalboard elevenlabs
brew install ffmpeg

# .env in the repo root:
#   DEEPSEEK_API_KEY=...
#   ELEVENLABS_API_KEY=...

bash launch.sh                 # full voice pipeline + eye server
bash launch.sh --eyes-only     # just the web UI on :8765
bash launch.sh --test          # canned prompts through the LLM
bash launch.sh --text-only     # text chat, no audio
```

Two caveats worth knowing:

- `launch.sh` checks for a local Ollama install with `gemma3:4b` before starting any mode,
  a leftover from the previous local-LLM stack. The voice pipeline itself does not use
  Ollama; running `python3 scripts/voice-pipeline-v2.py` directly skips that check.
- `--test` and `--text-only` route through the older Ollama-based scripts, so those two
  modes genuinely need Ollama (with `gemma3:4b` / `qwen3:14b` pulled).

## Status

Working prototype on a single machine. The v2 voice pipeline, eye server, and dashboard are
the current state; vision (webcam input) is not implemented. Everything runs against real
hardware (USB mic, speaker, a browser pointed at the eye server), so the repo contains no
automated tests — `scripts/profile.py` and `bash launch.sh --test` are the sanity checks.
