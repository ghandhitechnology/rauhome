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
#   CARTESIA_API_KEY=...       # optional Sonic 3.5 alternative
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

Install optional subsystems explicitly; normal startup never installs or builds:

```bash
scripts/setup.sh --voice
scripts/setup.sh --computer-use
scripts/setup.sh --chess          # python-chess + Stockfish, for the board
scripts/setup.sh --pi --web
python -m rau doctor
python -m rau launch-agent install   # one supervisor, never one entry per schedule
```

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

Voice also offers **Hyper** for delicate, rapid conversational tiki-taka. It
uses early endpointing, warm streaming connections, a tiny recent-turn window,
minimal reasoning, short replies, and no tools. Switch back to Normal for
research, durable memory context, or multi-step work.

```
Browser mic ─(PCM16 16k)─▶ /ws/voice ─▶ STT ─▶ face model (streaming + tools)
                                                    │
Browser speakers ◀─(PCM16 24k)─ sentence TTS ◀──────┘
      ▲ local VAD detects you talking → flush + {barge} → cancel everything
```

Speech-to-text is a pluggable slot (Deepgram, ElevenLabs Scribe, OpenAI, or
local whisper). Automatic mode prefers the lowest-latency connected backend.
Speaking can use ElevenLabs or Cartesia Sonic 3.5. ElevenLabs includes
Robotic, Grandfather, Girlfriend, and Childlike presets; both providers expose
the voices available to the user's own key — see
**Settings → Voice / Hearing** and [SETUP.md](SETUP.md).

### What the voice actually reads

The transcript keeps Rau's original text; only the copy sent to the synthesiser
is normalised, so `25 km/s` stays compact on screen while the voice says the
whole thing. Which normaliser runs depends on the script:

- **English** (`rau/voice/pronunciation.py`) expands units, currency, formulas
  and abbreviations — "25 kilometers per second".
- **Korean** (`rau/voice/korean/`) does the opposite, and runs the moment a
  sentence contains any Hangul. A Korean voice can only read Hangul, so every
  Latin word, acronym, unit symbol and chemical formula is turned into it:
  `25°C` → 섭씨 25도, `60 km/h` → 시속 60킬로미터, `H2O` → 물, `Google` → 구글,
  `kimchi` → 김치, `3개` → 세 개, `3시` → 세 시. Roughly 7,900 settled readings
  across brands, places, people, science, medicine, technology and romanised
  Korean back it; anything missing goes through a rule-based transliterator, so
  the voice is never handed a character it cannot pronounce. Particles are
  corrected to match the new sound — `H2O와` becomes 물과, not 물와.

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

## Durable operations

The **Operations** page shows persisted job plans, step evidence, budgets,
schedules and coalesced occurrences, pending approvals, and computer sessions.
Schedules use UTC storage plus an IANA timezone (default `Asia/Seoul`), never
overlap, and safely coalesce downtime. Computer use holds one exclusive
machine lease, resolves Accessibility targets before visual coordinates, and
re-observes to verify each mutation.

Resource profiles tune model limits, worker parallelism, canvas frame rate,
pixel ratio, and background activity. Pi and local speech models stay unloaded
until selected.

To record the required 30-minute before/after idle measurements, start Rau,
capture its root PID, then run:

```bash
venv/bin/python scripts/measure_power.py measure --pid PID --duration 1800 \
  --label before --output measurements/before.json
venv/bin/python scripts/measure_power.py measure --pid PID --duration 1800 \
  --label after --output measurements/after.json
venv/bin/python scripts/measure_power.py compare \
  measurements/before.json measurements/after.json
```

On macOS the report reads per-process idle and interrupt wakeups directly from
`libproc`; no `sudo` or heavyweight status scan is required.

## Safety model

- The hub defaults to loopback and rejects untrusted Host, Origin, cross-site HTTP, and WebSocket traffic. Set `hub_allowed_hosts` explicitly for trusted LAN names.
- Every shell command, external app action, computer input, destructive write, and skill installation requires explicit confirmation. Model-authored subprocesses do not inherit provider credentials.
- File tools and the Pi sidecar are confined to the project root; confined shell writes additionally cover temp and cache dirs. A non-loopback Pi sidecar additionally requires a 32+ character `PI_SIDECAR_TOKEN`.
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
