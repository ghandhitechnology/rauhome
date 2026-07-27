"""
Regression harness for the agent plumbing.

Runs without API keys: every provider is faked, so this exercises Rau's own
message assembly, tool loop, streaming path and voice timeline rather than any
model. Run it before and after touching `providers/`, `face/brain.py` or
`agent/orchestrator.py` — those five files sit under chat, voice and deep work
at once, so a change there can silently break barge-in while the type checker
stays happy.

    python tests/regress.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rau.providers.base import (  # noqa: E402
    ChatProvider,
    ChatResult,
    Message,
    StreamDone,
    TextDelta,
    ToolCall,
)

PASS: List[str] = []
FAIL: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


class ScriptedProvider(ChatProvider):
    """
    Replays a fixed script of turns.

    Each entry is (text, tool_calls). Records the messages it was handed so a
    test can assert on how Rau encoded the conversation.
    """

    name = "scripted"

    def __init__(self, script: List[tuple]):
        self.script = list(script)
        self.seen: List[List[Message]] = []

    def _next(self, messages: List[Message]) -> ChatResult:
        self.seen.append(list(messages))
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return ChatResult(content=text, tool_calls=list(calls))

    def chat(self, messages, **kw) -> ChatResult:
        return self._next(messages)

    def stream_turn(self, messages, **kw):
        result = self._next(messages)
        if result.content:
            for word in result.content.split(" "):
                yield TextDelta(word + " ")
        yield StreamDone(result)


def _install(monkey: Dict[str, Any]) -> None:
    from rau.face import brain

    brain.append_diary = lambda *a, **k: None
    for key, val in monkey.items():
        setattr(brain, key, val)


# ── chat ──────────────────────────────────────────────────────────────


def test_blocking_chat() -> None:
    print("\nblocking chat (brain.chat)")
    from rau.face import brain

    provider = ScriptedProvider([("Hello there.", [])])
    _install({"chat_for_slot": lambda s: (provider, {"model": "m", "max_tokens": 64})})
    brain.reset_history()

    out = brain.chat("hi")
    check("returns the reply", out == "Hello there.", repr(out))
    roles = [m.role for m in brain.snapshot_history()]
    check("history is user+assistant", roles == ["user", "assistant"], str(roles))


def test_tool_loop() -> None:
    print("\ntool loop (blocking, one round trip)")
    from rau.face import brain

    call = ToolCall(id="c1", name="memory_read", arguments={})
    provider = ScriptedProvider([("", [call]), ("I checked.", [])])
    ran: List[str] = []
    _install(
        {
            "chat_for_slot": lambda s: (provider, {"model": "m"}),
            "_run_face_tool": lambda n, a: (ran.append(n), {"ok": True, "text": "x"})[1],
        }
    )
    brain.reset_history()

    out = brain.chat("what do you remember")
    check("tool was invoked", ran == ["memory_read"], str(ran))
    check("final reply returned", out == "I checked.", repr(out))
    # The second call must carry the tool outcome in some form.
    second = provider.seen[1]
    carried = any("x" in (m.content or "") for m in second) or any(
        getattr(m, "tool_call_id", None) for m in second
    )
    check("tool result reached the model", carried)


def test_streaming_with_tools() -> None:
    print("\nstreaming chat (brain.chat_streaming)")
    from rau.face import brain

    call = ToolCall(id="c1", name="start_hard_task", arguments={"goal": "dig"})
    provider = ScriptedProvider([("Let me look.", [call]), ("Started on it.", [])])
    _install(
        {
            "chat_for_slot": lambda s: (provider, {"model": "m"}),
            "_run_face_tool": lambda n, a: {"ok": True, "id": "job1"},
        }
    )
    brain.reset_history()

    tokens: List[str] = []
    out = brain.chat_streaming("dig into this", on_token=tokens.append)
    spoken = "".join(tokens).strip()
    check("tokens streamed", len(tokens) > 1, f"{len(tokens)} tokens")
    check("pre-tool prose was spoken", "Let me look." in spoken, repr(spoken[:40]))
    # What was said aloud must equal what is remembered, or Rau repeats himself.
    check("spoken == recorded", spoken == out, f"{spoken!r} vs {out!r}")


def test_streaming_cancel() -> None:
    print("\nstreaming cancel (barge-in path)")
    from rau.face import brain

    provider = ScriptedProvider([("one two three four five", [])])
    _install({"chat_for_slot": lambda s: (provider, {"model": "m"})})
    brain.reset_history()

    stop = threading.Event()
    got: List[str] = []

    def on_token(t: str) -> None:
        got.append(t)
        if len(got) == 2:
            stop.set()

    try:
        brain.chat_streaming("x", on_token=on_token, cancel=stop)
        check("cancel raised Cancelled", False, "no exception")
    except brain.Cancelled:
        check("cancel raised Cancelled", True, f"after {len(got)} tokens")


# ── voice ─────────────────────────────────────────────────────────────


def test_voice_timeline() -> None:
    print("\nvoice timeline + honest truncation")
    from rau.voice.session import Utterance

    SR = 24000
    pcm = lambda ms: b"\x00\x00" * int(SR * ms / 1000)  # noqa: E731

    u = Utterance()
    u.add("First.", pcm(1000))
    u.add("Second.", pcm(1000))
    u.add("Third.", pcm(1000))

    check("timeline totals 3s", abs(u.total_ms - 3000) < 1, f"{u.total_ms}ms")
    check("cut at 0ms keeps nothing", u.heard_text(0) == "")
    check("cut mid-first keeps nothing", u.heard_text(400) == "")
    check("past first midpoint keeps one", u.heard_text(600) == "First.")
    check("past second keeps two", u.heard_text(1600) == "First. Second.")
    check("overrun keeps all", u.heard_text(99999) == "First. Second. Third.")


def test_voice_sentences() -> None:
    print("\nvoice sentence chunking")
    from rau.voice.tts_stream import SentenceBuffer

    buf = SentenceBuffer()
    released: List[str] = []
    for tok in ["Sure", " — ", "let me ", "look. ", "One ", "moment. ", "Done"]:
        released += buf.push(tok)

    # Sub-MIN_CHARS sentences ("One moment.") are no longer shipped as their
    # own clipped TTS request — they merge with what follows instead.
    check("released mid-stream", len(released) == 1, str(released))
    check("first is a whole sentence", released[0] == "Sure — let me look.", released[0])
    check("tail flushes", buf.flush() == "One moment. Done")


# ── deep work ─────────────────────────────────────────────────────────


def test_jobs() -> None:
    print("\njob registry")
    from rau.agent import orchestrator as o
    from rau import state

    def quick(job):
        time.sleep(0.05)
        state.update_job(job.id, state="done", result="ok")

    o._run_subagent = quick
    started = [o.start_job(f"g{i}") for i in range(3)]
    check("three started", all(r.get("ok") for r in started))
    time.sleep(0.5)

    jobs = {j["id"]: j for j in o.list_jobs()}
    done = [started[i]["id"] for i in range(3) if jobs[started[i]["id"]]["state"] == "done"]
    check("all three completed", len(done) == 3, f"{len(done)}/3")

    snap = state.status_snapshot()
    ht = snap.get("hard_task") or {}
    check(
        "derived hard_task view intact",
        {"id", "goal", "state", "progress", "result"} <= set(ht),
        str(sorted(ht)),
    )


def main() -> int:
    print("=" * 62)
    print("Rau agent-plumbing regression")
    print("=" * 62)
    for fn in (
        test_blocking_chat,
        test_tool_loop,
        test_streaming_with_tools,
        test_streaming_cancel,
        test_voice_timeline,
        test_voice_sentences,
        test_jobs,
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a crash is a failure, not a stop
            check(f"{fn.__name__} raised", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 62)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
