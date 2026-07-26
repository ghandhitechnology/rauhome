# Rau

A continuous local companion that lives on a Mac mini: one voice, durable memory,
daily dreaming, pluggable model providers, Composio MCP, and on-demand computer use.

Rau is a single being — not a team of agents. Hard work runs as silent inner subagents
while Rau keeps talking. Dangerous actions ask for confirm (voice or dashboard).

## Layout

- `rau/` — Python runtime (hub, face, providers, agent, MCP, CUA, memory, dream, heartbeat)
- `web/` — Vite + React + TypeScript UI (setup, home, identity, settings)
- `identity/` — `identity.md`, `backstory.md`, living `soul.md` (rotating `soul*.bak.md` backups are gitignored)
- `memories/` — diary, traces, daily dream logs (gitignored)
- `config/` — models, MCP, settings (non-secrets)
- `legacy/` — previous WALL-E scripts kept for reference

## Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..

# .env in repo root (examples):
#   OPENROUTER_API_KEY=...
#   ELEVENLABS_API_KEY=...
#   COMPOSIO_API_KEY=...
#   DEEPSEEK_API_KEY=...
#   KIMI_API_KEY=...           # Moonshot platform (pay-as-you-go)
#   KIMI_CODING_API_KEY=...    # Kimi Coding Plan membership (api.kimi.com/coding)
#   OPENAI_API_KEY=...         # codex / openai provider

bash launch.sh                 # hub + voice face
bash launch.sh --hub           # UI + API only
bash launch.sh --text          # hub without mic loop
```

Open `http://127.0.0.1:8765` — first visit forces Setup (Fresh or Hard startup).

## How it works

```
Mic → VAD → Whisper STT → Face model (soul + memory + skills/tools)
    ↘ start_hard_task → local subagent (MCP / CUA / shell) → weave result
Eyes/dashboard ← hub (HTTP + WebSocket)
Heartbeat (adaptive presence) + daily dream (soul rewrite + daily log)
```

## Two modes

**Shift+Space** switches between them anywhere in the UI.

- **Chat** — type and read.
- **Voice** — live listening, interruptible. Audio runs in the browser tab so
  the OS echo canceller can strip Rau's own output from the mic; that is what
  lets you talk over him without him cutting himself off. Replies are
  synthesised sentence by sentence, so he starts speaking before he has
  finished thinking, and interrupting him trims his memory to only what you
  actually heard.

```
Browser mic ─(PCM16 16k)─▶ /ws/voice ─▶ STT ─▶ face model (streaming + tools)
                                                    │
Browser speakers ◀─(PCM16 24k)─ sentence TTS ◀──────┘
      ▲ local VAD detects you talking → flush + {barge} → cancel everything
```

Speech-to-text is a pluggable slot (Deepgram, ElevenLabs Scribe, OpenAI, or
local whisper). Automatic mode prefers the lowest-latency connected backend.
ElevenLabs speaking includes Robotic, Grandfather, Girlfriend, and Childlike
presets plus every voice available to the user's own key — see
**Settings → Voice / Hearing** and [SETUP.md](SETUP.md).

### Always-available skills

Skills live in `skills/*/SKILL.md` and are always injectable. In talk:

| Slash | Purpose |
|-------|---------|
| `/grill-me` | One-question-at-a-time design interview |
| `/plan` | Concrete ordered plan |
| `/read` `/write` | Local file work |
| `/goal` | Set / show / clear the active goal |
| `/shell` `/search` `/remember` `/computer` `/summarize` | Essentials |
| `/skills` | List them |
| `/effort low\|medium\|high\|max` | Thinking depth |

Dashboard also has **Model effort** knobs (face / subagent / dream) and a skills list.

## Safety model

- The hub defaults to loopback and rejects untrusted Host, Origin, cross-site HTTP, and WebSocket traffic. Set `hub_allowed_hosts` explicitly for trusted LAN names.
- Every shell command, external app action, computer input, destructive write, and skill installation requires explicit confirmation. Model-authored subprocesses do not inherit provider credentials.
- File tools and the Pi sidecar are confined to the project root. A non-loopback Pi sidecar additionally requires a 32+ character `PI_SIDECAR_TOKEN`.
- Secrets are stored atomically in owner-only `.env`; model config and `soul.md` use atomic replacement and recoverable backups.

## Verification

```bash
source venv/bin/activate
python -m compileall -q rau tests
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/regress.py && python tests/agentic.py
python tests/agentic_hardening.py && python tests/e2e.py

(cd web && npm test && npm run build && npm run lint && npm audit)
(cd pi-sidecar && npm test && npm audit)
```

Credentialed speech providers and physical microphone/speaker latency still require a real-device smoke test. See [SETUP.md](SETUP.md) for hardware and dependency notes.
