# pi bridge (spike)

A bridge from Rau's Python hub to [pi](https://github.com/earendil-works/pi)'s
`AgentHarness`, for long-horizon deep work. Voice and face stay in Python.

Two pieces:

- `pi-sidecar/` — a ~515-line Node service that owns one `AgentHarness` per run
  and exposes it over local HTTP + SSE.
- `rau/pi/client.py` — a stdlib-only Python client shaped like
  `orchestrator._run_subagent`: goal in, progress callbacks, cancellable via a
  `threading.Event`, result out.

Nothing here is wired into `orchestrator.py` or the hub. Importing `rau.pi` has
no side effects and does not require the sidecar to be running.

## Running it

```bash
cd pi-sidecar && npm install     # 97 packages, pinned to pi 0.82.1
node src/server.mjs              # PI_SIDECAR_HOST/PI_SIDECAR_PORT, default 127.0.0.1:8791
```

Requires Node >= 22.19 (tested on v26.5.0).

```python
from rau.pi import PiSidecar, RunSpec

pi = PiSidecar()
result = pi.run(
    RunSpec(goal="audit the voice pipeline", cwd="/Users/…/Rau"),
    on_progress=print,
    on_confirm=lambda req: req.tool != "bash",
    cancel=job.cancel,              # the same threading.Event a Rau Job carries
)
result.state    # done | failed | cancelled
result.result
```

`provider="faux"` (the default) drives pi's scripted fake provider, so the whole
path runs with **no API keys**. Set `provider="anthropic"`, `model="claude-…"`
to hit a real one; auth resolves through pi's own provider credentials, the
sidecar never touches keys.

### API

| | |
|---|---|
| `GET /health` | version, faux scenarios, defaults |
| `POST /runs` | start a goal, returns a snapshot with `id` |
| `GET /runs/:id` | snapshot: `state`, `progress`, `result`, `turns`, pending `confirm` |
| `GET /runs/:id/events` | SSE, replayed from run start: `state`, `text`, `tool`, `confirm_request`, `confirm_result`, `result`, `close` |
| `POST /runs/:id/cancel` | |
| `POST /runs/:id/confirm` | `{confirm_id, approved}` |

States are exactly Rau's: `running`, `awaiting_confirm`, `done`, `failed`,
`cancelled`, with the same rule that a terminal state is immutable.

## Verified end to end

Sidecar running, driven from Python, no API keys, real `bash` execution:

```
health: True v26.5.0

--- 1. approve the bash confirm ---
  progress: running bash
  progress: run: echo "goal: inspect the repo" && ls -1 | head -3
  confirm? tool=bash summary='run: echo "goal: inspect the repo" && ls -1 | head -3' -> APPROVE
  progress: running bash
  progress: turn 1
  progress: turn 2
  progress: done
  -> done | Done. Goal was: inspect the repo | ok= True

--- 2. deny the bash confirm ---
  -> done | Done. Goal was: deny this

--- 3. cancel a long run via threading.Event ---
  progress: running bash
  progress: cancelled
  -> cancelled after 1.5s

--- 4. cancel while parked on a confirm ---
  confirm handler parked for 12s; cancelled from another thread at t+0.8s
  -> cancelled after 0.8s

--- 5. turn budget ---
  -> failed | turn budget of 1 exhausted
```

Case 3 cancels a real `sleep 60` mid-execution and the process dies. Case 4's
number is the one that matters: `run()` returns on the cancel, not when the
parked handler eventually answers. Case 5 is `max_turns=1` on a two-turn
scenario.

**What "faux" means and does not mean.** The agent loop, tool preflight, tool
execution, session writes, event stream, abort plumbing and confirm gate are all
pi's real code. Only the LLM's replies are scripted. No run against a real
provider has been made — token accounting, retries, thinking levels and
compaction under load are all unexercised.

## Integration seams — the honest part

### The confirm gate composes, but only in one order

Rau's `awaiting_confirm` maps cleanly onto pi's `tool_call` hook, which is an
async preflight that can return `{block: true, reason}`. Blocking feeds an error
tool result back to the model, which is exactly what
`_run_subagent` does today with `"user denied or confirm timed out"`.

But **`harness.abort()` does not interrupt a parked hook.** `abort()` calls
`waitForIdle()`, which awaits the run promise, which cannot settle while a hook
is still awaiting. And `emitHook()` — unlike `emitAny()` — does not pass the
abort signal to handlers, so the hook has no way to learn it should give up.
Measured with a probe: with a hook parked, `abort()` had not returned after
3000ms.

Consequence for the bridge: cancel **must** resolve the pending confirm as
denied *before* calling `abort()`. `PiRun.cancel()` does this and the ordering is
load-bearing — swap the two lines and cancel hangs forever. Anything else that
later parks inside a pi hook inherits the same trap.

The Python side has the mirror of it. The events that end `run()` arrive on the
stream reader, so a `on_confirm` handler answered on that thread makes cancel
latency equal to however long the human takes to decide — the sidecar settles in
under a second and the caller notices minutes later. `_handle_confirm` therefore
decides on its own thread and lets the reader keep draining; a reply for a gate
that has already settled is rejected by confirm id, so racing is safe.

### pi has no turn budget

`runAgentLoop` is `while (true)`; it runs until the model stops calling tools.
There is no `maxTurns`, no step cap, no wall-clock guard anywhere in
`packages/agent`. Rau's 24-step ceiling has no pi equivalent.

The sidecar enforces it from outside by counting `turn_end` events and aborting.
That is imprecise: the abort is async and the loop can start another turn before
it lands (observed — a `max_turns=1` run still reported `turn 2`). The final
state is right; the overshoot is one turn. A run against a paid provider can
therefore exceed its budget by one turn's tokens.

### `tool_execution_start` fires before the block decision

pi emits `tool_execution_start` during preflight, *before* the `tool_call` hook
returns. A naive UI binding would render "running bash" while the confirm is
still pending, and would render it for tools that then get blocked. The sidecar
works around it by emitting its own `state` transition after the hook resolves;
the raw `tool` event is still forwarded and still lies about ordering.

### Session and compaction: composes for jobs, fights for conversation

This is the question that matters, and the answer splits.

**It composes for background jobs.** pi's `systemPrompt` option accepts a
callback, and pi re-resolves it for *every provider request*, not once per run.
Verified: a callback returning `emotion=idle` / `emotion=curious` /
`emotion=tired` produced exactly those three system prompts across the three
turns of one `prompt()` call. So injecting live `soul.md` + the current emotion
tag on every turn is not a workaround, it is the intended extension point.
Compaction is also **not automatic** — `shouldCompact()` is a helper the
application calls; the harness never compacts behind your back. Between those
two facts, a pi run started fresh per Job does not fight Rau at all: fresh
session, Rau owns the prompt, Rau owns when to compact.

**It fights if pi is ever given the conversation.** Three concrete places:

1. **Compaction discards Rau's voice.** `compact()` runs its own LLM call with a
   hardcoded `SUMMARIZATION_SYSTEM_PROMPT` ("You are a context summarization
   assistant") and a fixed `## Goal / ## Progress / ## Key Decisions` output
   format. `soul.md` is not in that call. The summary that replaces the
   transcript is written in a generic assistant's register. Harmless for a
   silent worker whose summary is never spoken; corrosive for anything Rau reads
   back out.
2. **Anything Rau injects into *messages* gets summarized away.** Rau's per-turn
   emotion tag survives only because it lives in the system prompt, which
   compaction does not touch. Anything pushed as a user/assistant message —
   memory recalls, diary excerpts, tool traces — is transcript, and compaction
   will replace it with a paraphrase. The `context` hook can re-inject on every
   turn, but that means Rau re-derives it each turn rather than trusting the
   transcript.
3. **Two transcripts, two sources of truth.** pi's `Session` is a durable JSONL
   tree with branching, forking, leaf pointers and its own compaction entries.
   Rau has `state._chat_log` plus `rau/memory/store.py`. Nothing reconciles
   them. Per-job that is fine (the pi session is scratch, thrown away after the
   result). Making pi own the voice conversation means either abandoning Rau's
   log or writing a two-way sync, and pi's tree model has no counterpart on the
   Rau side.

The clean line is: **pi owns a job's transcript, never Rau's conversation.**
That is also the split the hybrid plan already assumes.

### Skills: name and path cross, body does not

pi's `Skill` is `{name, description, content, filePath}`, but
`formatSkillsForSystemPrompt` only emits name, description and **location** —
the model is expected to `read` the file itself. Rau's
`rau.skills.loader.Skill.prompt_block()` inlines the whole body instead.

`pi_skill()` maps the fields, but the mapping is lossy in practice: `content` is
carried and then ignored by the prompt builder, so a pi run only really gets a
skill if `filePath` is readable from the run's `cwd` and the `read` tool is
enabled. Skills Rau synthesises in memory, or skills whose body matters more
than their file, do not survive the crossing. Rau's `always: true` skills have
no pi equivalent at all — pi has no notion of an always-on skill, only
`disableModelInvocation` to hide one.

### Tools do not cross at all

pi's tools are `bash`/`read`/`write`/`edit` + a file mutation queue, defined as
typebox-schema'd JS closures. Rau's tools (`rau/agent/tools.py`) are Python:
`memory_write`, `finish`, MCP calls, the computer-use bridge. A pi run cannot
call them without a second bridge hop back into Python.

This also changes the termination contract. Rau's subagent ends by calling
`finish(summary)`. A pi run ends when the model emits no tool calls, and the
result is whatever text the final assistant message happened to contain. The
sidecar reports that text as `result`. It is strictly less structured than
`finish(summary)`, and there is no way to distinguish "finished the goal" from
"gave up and said so".

### Smaller things

- **Session storage is in-memory here.** `JsonlSessionRepo` exists and would give
  durable, resumable runs across a sidecar restart; the spike does not use it,
  so a sidecar restart loses every run.
- **One process, no isolation.** Every run shares the sidecar's process, cwd
  permissions and `NodeExecutionEnv`. pi ships sandbox examples in
  `packages/coding-agent/examples/extensions/sandbox`; none of that is wired up.
  A pi run currently has the same filesystem reach as the sidecar itself.
- **97 npm packages** land in `pi-sidecar/node_modules` for a project that
  otherwise ships Python and a Vite frontend. `@earendil-works/pi-ai` pulls in
  `@google/genai` and `protobufjs` transitively. That is the real cost of the
  hybrid, and it is not small.
- **`text` deltas are forwarded but unused.** The client exposes `on_text`. A
  silent background worker has nothing to do with a token stream; it is there
  for a future foreground use.

## If this were to ship

The seams that must be closed first, in order:

1. Switch to `JsonlSessionRepo` so runs survive a sidecar restart.
2. Supervise the sidecar from Python (`launch.sh` or the hub) instead of
   requiring a hand-started `node`.
3. Decide the termination contract — either register a pi-side `finish` tool that
   mirrors Rau's, or accept unstructured final text.
4. Sandbox the run.

Steps 1–3 are small. Step 4 is not, and it is the one that decides whether a pi
run can be trusted with a goal nobody is watching.
