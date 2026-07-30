<p align="center">
  <img src="docs/rau-header.png" alt="Rau, an orange pencil-sketch companion, holding a Rau sign" width="720">
</p>

# Rau

A continuous local companion that lives on a Mac mini: one voice, durable memory,
daily dreaming, bilingual conversation, pluggable model providers, Composio MCP,
and on-demand computer use.

Rau is a single being — not a team of agents. Hard work runs as silent inner subagents
while Rau keeps talking. Dangerous actions ask for confirmation in the conversation
or dashboard. You can talk by text or voice, share a room, and play chess or
Exploding Kittens together.

## Layout

- `rau/` — Python runtime (hub, face, providers, agent, MCP, CUA, memory, dream, heartbeat)
- `web/` — Vite + React + TypeScript UI (setup, Talk, Room, operations, settings, games)
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

Open `http://127.0.0.1:8765`. On the first visit, choose English or Korean with
a live preview, follow the short introduction, then complete Setup with a Fresh
or Hard startup.

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
Mic / keyboard → conversation mode → Face model (soul + memory + skills/tools)
             ↘ start_hard_task → local subagent (MCP / CUA / shell) → weave result
Talk / Room / games ← hub (HTTP + WebSocket)
Heartbeat (adaptive presence) + daily dream (soul rewrite + daily log)
```

## Four ways to talk

**Shift+Space** cycles through them anywhere in the UI.

- **Chat** — type and read.
- **Voice** — live listening, interruptible. Audio runs in the browser tab so
  the OS echo canceller can strip Rau's own output from the mic; that is what
  lets you talk over him without him cutting himself off. Replies are
  synthesised sentence by sentence, so he starts speaking before he has
  finished thinking, and interrupting him trims his memory to only what you
  actually heard.
- **Talk** — type to Rau and hear the answer aloud, with the microphone off.
- **Space Talk** — hold Space to speak and release it to send.

Voice and Space Talk also offer **Hyper** for delicate, rapid conversational
tiki-taka. It uses early endpointing, warm streaming connections, a tiny
recent-turn window, minimal reasoning, short replies, and no tools. Its
activation travels outward from the toggle and leaves a quiet edge ambience;
reduced-motion preferences skip the effect. Switch back to Normal for research,
durable memory context, or multi-step work. Talk always stays on Normal.

```
Browser mic ─(PCM16 16k)─▶ /ws/voice ─▶ STT ─▶ face model (streaming + tools)
                                                    │
Browser speakers ◀─(PCM16 24k)─ sentence TTS ◀──────┘
      ▲ local VAD detects you talking → flush + {barge} → cancel everything
```

The Talk page is the center of the thread and opens the Room through a
canvas-aware transition that waits for the first incoming frame. Games begin
from that same conversation: ask Rau to set up chess or deal Exploding Kittens,
and the table appears in the Room.

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

### The interface in Korean

**Settings → Experience → Language** switches the whole product, not just the
labels. The choice is stored on the hub, so Rau also answers in that language,
and every string a person reads follows it:

- the first-run language gate previews the entire screen in English or Korean
  before the choice is confirmed;
- the interface itself, from `web/src/locales/{en,ko}.ts` — one key set, with
  the Korean file typed as a total map over it, so a string added without a
  translation fails the build rather than showing through in English;
- the copy the hub owns — provider blurbs, slot guidance, voice presets,
  connection help — translated in `rau/providers/korean.py` as an overlay keyed
  by the English text, so a model added upstream never silently disappears;
- the activity plane, in `rau/face/phrases.py`: what a tool is called while it
  runs, what a turn summarised, what Rau says out loud between long tool calls.

Model ids, env var names, file paths and provider errors stay in English on
purpose. They are identifiers, and a translated identifier is a wrong one.

Typography is in `web/src/hangul.css`. Two things there matter more than the
rest. `word-break: keep-all` is global rather than Korean-only, because Rau can
answer in Korean while the interface is still English, and without it a line can
end in the middle of a word — 다시 arriving as 다 / 시. And Hangul gets its own
pair of faces: Pretendard beside DM Sans, Nanum Myeongjo beside Instrument
Serif, chosen so their x-height and cap height land within a percent of the
Latin they sit next to. Both are subset to the Hangul blocks with a matching
`unicode-range`, so an English session never downloads either file.

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

The presence heartbeat can generate a short, context-aware check-in in the
active language after 12 quiet minutes. If there is no reply, it waits at least
another hour before one final check-in, then stays quiet until the user returns.
The allowance, timing, and recent nudge are persisted so a restart cannot reset
the social backoff.

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
