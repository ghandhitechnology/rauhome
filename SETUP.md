# Setup

Target machine: an Apple-silicon Mac (developed on an M4 Mac mini with 16 GB RAM) with a
USB microphone, a speaker, and a display or browser for the eye UI. These steps are written
for that machine; nothing here is meant to be portable.

## 1. System dependencies

```bash
brew install ffmpeg python@3.11
```

- `ffmpeg` is required — the voice pipeline captures microphone audio through it
  (`avfoundation`), not through Python's audio stack.
- Ollama (`brew install ollama`) is only needed for the legacy modes `--test` and
  `--text-only`, and because `launch.sh` still checks for it on startup. See "Caveats" in
  the README.

## 2. Python environment

The launcher expects the virtualenv at `venv/` in the repo root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install numpy sounddevice faster-whisper silero-vad torch pedalboard elevenlabs
```

What each is for:

| Package | Used by |
|---|---|
| `numpy`, `sounddevice` | audio buffers and speaker playback |
| `faster-whisper` | speech-to-text (`small`, CPU int8) |
| `silero-vad`, `torch` | voice activity detection (falls back to energy-based VAD if absent) |
| `pedalboard` | robot voice FX (pitch shift, bitcrush, distortion, reverb) |
| `elevenlabs` | text-to-speech client |

The faster-whisper `small` model downloads on first run (a few hundred MB) and is cached
by the library outside the repo.

## 3. API keys

The current pipeline uses two cloud services. Create a `.env` file in the repo root
(it is gitignored):

```
DEEPSEEK_API_KEY=sk-...
ELEVENLABS_API_KEY=...
```

Both are also read from the environment if set there. Without them the pipeline starts but
cannot generate or speak replies.

## 4. Sound effects

Emotion tags in LLM replies (`[HAPPY]`, `[CURIOUS]`, `[EXCITED]`, `[SAD]`, `[COMPACT]`,
`[SCARED]`, `[AMAZED]`, `[LOVE]`, `[DETERMINED]`) map to WAV files in `assets/sfx/`
(see `SFX_MAP` in `scripts/voice-pipeline-v2.py`). That directory is gitignored, so drop
your own robot beeps/whirs there — 16-bit PCM WAV. Missing files are skipped silently; the
pipeline works fine with none, just without sound effects.

## 5. Run

```bash
bash launch.sh                 # voice pipeline + eye server (http://127.0.0.1:8765)
bash launch.sh --eyes-only     # eye server alone
bash launch.sh --test          # canned prompts through the LLM (needs Ollama)
bash launch.sh --text-only     # keyboard chat, no audio (needs Ollama)
```

To skip the launcher's Ollama check entirely, run the pipeline directly:

```bash
source venv/bin/activate
python3 scripts/voice-pipeline-v2.py
```

Open `http://127.0.0.1:8765` in a browser for the dashboard: it shows the current emotion,
the chat log, and service status, and accepts control commands.

## 6. Verify

- `python3 scripts/profile.py` — per-stage latency benchmark of the pipeline.
- `python3 scripts/test_elevenlabs.py` — quick check that the ElevenLabs key works.
- `python3 scripts/llm.py` — streaming benchmark against the DeepSeek API.
