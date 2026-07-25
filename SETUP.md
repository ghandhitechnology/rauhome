# Setup

Target: Apple-silicon Mac with mic, speaker, and a browser for the Rau UI.

## 1. System

```bash
brew install ffmpeg python@3.11 node
```

`ffmpeg` is required for microphone capture (`avfoundation`).

Optional for desktop clicks if PyObjC/Quartz is unavailable: `brew install cliclick`.
Grant Accessibility / Screen Recording to Terminal (or your host) for computer use.

## 2. Python

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Web UI

```bash
cd web && npm install && npm run build && cd ..
```

Dev UI (proxied to hub):

```bash
# terminal A
PYTHONPATH=. python -m rau hub
# terminal B
cd web && npm run dev
```

## 4. Secrets (`.env`)

```
OPENROUTER_API_KEY=
ELEVENLABS_API_KEY=
COMPOSIO_API_KEY=
DEEPSEEK_API_KEY=
KIMI_API_KEY=
KIMI_CODING_API_KEY=
OPENAI_API_KEY=
DEEPGRAM_API_KEY=   # optional — streaming speech-to-text for voice mode

# Kimi Coding Plan (membership) is separate from Moonshot pay-as-you-go.
# In Settings, pick provider `kimi_code` and a model such as:
#   kimi-for-coding | kimi-for-coding-highspeed | k3 | k3-256k
# Docs: https://www.kimi.com/code/docs/en/
```

Configure face / subagent / dream models live in **Settings** (writes `config/models.json`).

## 5. Identity

First open of `http://127.0.0.1:8765` runs Setup:

- **Fresh state** — minimal seed + synthesized `soul.md`
- **Hard startup** — paste `identity.md` + `backstory.md` → `soul.md`

Later: **Identity** page hard-steers (re-synthesize with backup). Dreaming may rewrite `soul.md` overnight.

## 6. Run

```bash
bash launch.sh
```

Modes: `--hub`, `--text`, `--no-audio`, `--face`.

## 7. Voice mode

Rau has two conversational modes. **Shift+Space** switches between them from
anywhere in the UI.

- **Chat** — type, as before.
- **Voice** — live listening, Rau speaks as he generates, and you can talk over
  him to cut him off mid-sentence.

Voice mode runs its audio **in the browser tab**, not through the Python
pipeline. That is deliberate: the browser gives us hardware echo cancellation,
which is the only thing that stops Rau hearing his own voice through your
speakers and interrupting himself. The first time you enter voice mode the
browser will ask for microphone permission.

### Hearing (speech-to-text)

Configured in **Settings → Hearing**. Four backends:

| Backend | Key needed | Live transcript |
|---|---|---|
| Deepgram | `DEEPGRAM_API_KEY` | yes — words appear as you speak |
| ElevenLabs Scribe | reuses `ELEVENLABS_API_KEY` | no |
| OpenAI | reuses `OPENAI_API_KEY` | no |
| Local (faster-whisper) | none | no |

Only Deepgram streams interim results; the others transcribe once you stop
talking. Local whisper needs no key and never sends your voice anywhere, but is
the slowest.

If the configured backend's key is missing, voice mode falls back to local
whisper rather than failing — Settings tells you when that will happen.

### Speaking (text-to-speech)

Needs `ELEVENLABS_API_KEY`. Replies are synthesised sentence by sentence, so
Rau starts talking before he has finished thinking. Without the key, voice mode
still listens and replies in text.

### Notes

- Headphones are not required, but they make barge-in more reliable in a loud
  room.
- While a browser voice session is open, the host-side mic loop is suspended so
  the two do not both transcribe you.
