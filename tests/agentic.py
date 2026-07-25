"""
Acceptance tests for the agentic upgrades.

Deliberately independent of the implementation agents' own scratch checks: this
asserts the behaviour that was asked for, against the public surface, so a
capability that was reported as done but does not actually work shows up here.

Anything not built yet reports SKIP rather than crashing the run, so this is
useful mid-flight as well as at the end.

    python tests/agentic.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS: List[str] = []
FAIL: List[str] = []
SKIP: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'ok  ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, why: str) -> None:
    SKIP.append(name)
    print(f"  [skip] {name} — {why}")


# ── 1. tool-call protocol ─────────────────────────────────────────────


def test_protocol() -> None:
    print("\n1. tool-call protocol")
    from rau.providers.base import Message, ToolCall, messages_to_openai

    if "tool_calls" not in Message.__dataclass_fields__:
        skip("Message carries tool calls", "Message not extended yet")
        return

    call = ToolCall(id="call_1", name="read_file", arguments={"path": "x.py"})
    convo = [
        Message(role="system", content="be helpful"),
        Message(role="user", content="read x.py"),
        Message(role="assistant", content="", tool_calls=[call]),
        Message(role="tool", content='{"ok":true}', tool_call_id="call_1", name="read_file"),
        Message(role="assistant", content="Done."),
    ]

    # Old two-arg construction must still work — it is used all over the repo.
    legacy = Message(role="user", content="plain")
    check("legacy Message still constructs", legacy.content == "plain")

    wire = messages_to_openai(convo)
    assistant = next((m for m in wire if m.get("tool_calls")), None)
    check("assistant turn carries tool_calls", assistant is not None)

    tool_msg = next((m for m in wire if m.get("role") == "tool"), None)
    check("emits a real role=tool message", tool_msg is not None)
    if tool_msg:
        check(
            "tool message references its call id",
            tool_msg.get("tool_call_id") == "call_1",
            str(tool_msg.get("tool_call_id")),
        )
    if assistant:
        ids = [tc.get("id") for tc in assistant["tool_calls"]]
        check("call id pairs exactly", ids == ["call_1"], str(ids))
        fn = assistant["tool_calls"][0].get("function") or {}
        args_ok = isinstance(fn.get("arguments"), str)
        check("arguments serialized as a JSON string", args_ok, type(fn.get("arguments")).__name__)

    # No fake "Tool ... result:" prose should survive anywhere.
    blob = json.dumps(wire)
    check("no faked tool prose remains", "Tool read_file result:" not in blob)

    from rau.providers.anthropic_compat import _to_anthropic_messages

    system, anth = _to_anthropic_messages(convo)
    check("system extracted for anthropic", "be helpful" in system)
    flat = json.dumps(anth)
    check("anthropic emits tool_use", "tool_use" in flat)
    check("anthropic emits tool_result", "tool_result" in flat)
    # The merge step must not have fused the tool turn into its neighbour.
    for m in anth:
        if isinstance(m.get("content"), list):
            kinds = [b.get("type") for b in m["content"] if isinstance(b, dict)]
            if "tool_result" in kinds and "tool_use" in kinds:
                check("tool_use and tool_result never share a turn", False, str(kinds))
                break
    else:
        check("tool_use and tool_result never share a turn", True)


# ── 2. context compaction ─────────────────────────────────────────────


def test_compaction() -> None:
    print("\n2. context compaction")
    try:
        from rau.agent import compaction
    except ImportError:
        skip("compaction module", "rau/agent/compaction.py not built yet")
        return

    from rau.providers.base import Message

    for fn in ("should_compact", "compact"):
        if not hasattr(compaction, fn):
            skip(f"compaction.{fn}", "not exported")
            return

    long_convo = [Message(role="system", content="you are Rau")]
    long_convo.append(Message(role="user", content="GOAL: find the memory leak"))
    for i in range(60):
        long_convo.append(Message(role="assistant", content=f"step {i} " + "x" * 400))
        long_convo.append(Message(role="user", content=f"reply {i} " + "y" * 400))

    small = [Message(role="system", content="s"), Message(role="user", content="hi")]
    check("short conversation is left alone", not compaction.should_compact(small, 100000))
    check("long conversation triggers", compaction.should_compact(long_convo, 8000))

    summarized: List[str] = []

    def fake_summary(text: str) -> str:
        summarized.append(text)
        return "EARLIER: goal was to find the memory leak; tried steps 0-40."

    def run_compact(convo, summarize):
        """Tolerate a reasonable signature, but assert hard on behaviour."""
        import inspect

        params = inspect.signature(compaction.compact).parameters
        if "budget" in params:
            return compaction.compact(convo, summarize, budget=8000)
        if "max_tokens" in params:
            return compaction.compact(convo, summarize, max_tokens=8000)
        return compaction.compact(convo, summarize)

    out = run_compact(long_convo, fake_summary)
    check("compaction shrinks the conversation", len(out) < len(long_convo), f"{len(long_convo)} -> {len(out)}")
    check("system message survives", out and out[0].role == "system", out[0].role if out else "empty")
    joined = " ".join(m.content or "" for m in out)
    check("original goal survives compaction", "memory leak" in joined)
    check("recent turns kept verbatim", "step 59" in joined)

    # A failing summarizer must degrade, not take down a live conversation.
    def broken(_text: str) -> str:
        raise RuntimeError("summarizer down")

    try:
        degraded = run_compact(long_convo, broken)
        check("failed summarizer degrades gracefully", len(degraded) <= len(long_convo))
    except Exception as e:  # noqa: BLE001
        check("failed summarizer degrades gracefully", False, f"raised {type(e).__name__}")

    # A tool pair split across the cut is a hard 400 from both providers.
    if hasattr(compaction, "find_cut_point") and "tool_calls" in Message.__dataclass_fields__:
        from rau.providers.base import ToolCall

        paired = [Message(role="system", content="s")]
        for i in range(40):
            tc = ToolCall(id=f"c{i}", name="read_file", arguments={})
            paired.append(Message(role="assistant", content="", tool_calls=[tc]))
            paired.append(Message(role="tool", content="r", tool_call_id=f"c{i}", name="read_file"))
        cut = compaction.find_cut_point(paired)
        after = paired[cut:]
        orphan = any(
            m.role == "tool"
            and not any(
                (p.tool_calls or []) and any(c.id == m.tool_call_id for c in p.tool_calls)
                for p in after[: after.index(m)]
            )
            for m in after
            if m.role == "tool"
        )
        check("cut never orphans a tool result", not orphan, f"cut at {cut}")


# ── 3. edit tool + sandbox ────────────────────────────────────────────


def test_edit_and_sandbox() -> None:
    print("\n3. edit tool + path containment")
    try:
        from rau.agent import edit
    except ImportError:
        skip("edit module", "rau/agent/edit.py not built yet")
        return

    import shutil
    import tempfile

    if not hasattr(edit, "edit_file"):
        skip("edit.edit_file", "not exported")
        return

    # Must live under the repo root: the tool contains edits to ROOT by design,
    # so a scratch dir in /var/folders would be refused for the right reason.
    tmp = Path(tempfile.mkdtemp(dir=Path(__file__).resolve().parent.parent))
    target = tmp / "sample.py"
    target.write_text("alpha = 1\nbeta = 2\nalpha = 1\n")

    # Editing is gated on having read the file first; satisfy that gate.
    for marker in ("note_read", "mark_read", "record_read"):
        if hasattr(edit, marker):
            getattr(edit, marker)(target)
            break

    r = edit.edit_file(str(target), "beta = 2", "beta = 3")
    ok = r.get("ok") if isinstance(r, dict) else bool(r)
    check("single unambiguous edit applies", bool(ok), str(r)[:80])
    check("file actually changed", "beta = 3" in target.read_text())

    r = edit.edit_file(str(target), "nowhere_at_all", "x")
    failed = not (r.get("ok") if isinstance(r, dict) else True)
    check("zero-match is rejected", failed, str(r)[:80])

    r = edit.edit_file(str(target), "alpha = 1", "alpha = 9")
    ambiguous_rejected = not (r.get("ok") if isinstance(r, dict) else True)
    check("ambiguous multi-match is rejected", ambiguous_rejected, str(r)[:90])

    r = edit.edit_file(str(target), "alpha = 1", "alpha = 9", replace_all=True)
    ok = r.get("ok") if isinstance(r, dict) else bool(r)
    check("replace_all resolves ambiguity", bool(ok), str(r)[:60])

    try:
        from rau.agent import sandbox
    except ImportError:
        skip("sandbox module", "rau/agent/sandbox.py not built yet")
        return

    guard = None
    for fn in ("resolve_in_root", "safe_path", "resolve_within_root", "contain_path", "check_path"):
        if hasattr(sandbox, fn) or hasattr(edit, fn):
            guard = getattr(sandbox, fn, None) or getattr(edit, fn)
            break
    if guard is None:
        skip("path containment", "no recognisable guard function")
        return

    def blocked(p: str) -> bool:
        try:
            result = guard(p)
            return result is None or result is False
        except Exception:
            return True

    check("blocks .. traversal", blocked("../../../../etc/passwd"))
    check("blocks absolute escape", blocked("/etc/passwd"))

    link = tmp / "escape"
    try:
        link.symlink_to("/etc")
        check("blocks symlink escape", blocked(str(link / "passwd")))
    except OSError:
        skip("symlink escape", "could not create symlink here")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 4. nested subagents ───────────────────────────────────────────────


def test_nested_jobs() -> None:
    print("\n4. nested subagents")
    from rau.agent import orchestrator as o
    from rau import state

    if not hasattr(o, "start_job"):
        skip("job registry", "start_job missing")
        return

    import inspect

    sig = inspect.signature(o.start_job)
    if "parent_id" not in sig.parameters and "parent" not in sig.parameters:
        skip("nested spawning", "start_job takes no parent")
        return
    key = "parent_id" if "parent_id" in sig.parameters else "parent"

    live: Dict[str, bool] = {}

    def hold(job):
        live[job.id] = True
        for _ in range(200):
            if job.cancel.is_set():
                break
            time.sleep(0.01)
        live[job.id] = False

    o._run_subagent = hold

    parent = o.start_job("parent research")
    check("parent starts", bool(parent.get("ok")), str(parent)[:70])
    time.sleep(0.1)

    kids = [o.start_job(f"sub-question {i}", **{key: parent["id"]}) for i in range(2)]
    check("children spawn under a parent", all(k.get("ok") for k in kids), str([k.get("ok") for k in kids]))
    time.sleep(0.2)

    jobs = {j["id"]: j for j in o.list_jobs()}
    child_ids = [k["id"] for k in kids if k.get("ok")]
    if child_ids:
        linked = all(jobs.get(c, {}).get("parent_id") == parent["id"] for c in child_ids)
        check("parent_id exposed on children", linked)

    # Depth must be bounded — unbounded nesting is a fork bomb with a bill.
    if child_ids:
        deep = o.start_job("too deep", **{key: child_ids[0]})
        check("depth is capped", not deep.get("ok"), str(deep.get("error"))[:60])

    o.cancel_job(parent["id"])
    time.sleep(0.4)
    jobs = {j["id"]: j for j in o.list_jobs()}
    orphans = [c for c in child_ids if jobs.get(c, {}).get("state") in ("running", "awaiting_confirm")]
    check("cancelling a parent kills its children", not orphans, f"{len(orphans)} still running")

    snap = state.status_snapshot()
    ht = snap.get("hard_task") or {}
    check(
        "derived hard_task view still intact",
        {"id", "goal", "state", "progress", "result"} <= set(ht),
        str(sorted(ht)),
    )
    o.cancel_all()


# ── 5. the face is gated too ──────────────────────────────────────────


def test_face_gate() -> None:
    print("\n5. face tool gate")
    from rau.face import brain
    from rau.paths import ROOT

    names = [t["function"]["name"] for t in brain.FACE_TOOLS]
    check("face can edit, not just overwrite", "edit_file" in names)

    victim = ROOT / "identity" / "soul.md"
    before = victim.read_text() if victim.exists() else None

    def gated(tool: str, args: Dict[str, Any]) -> bool:
        return brain._run_face_tool(tool, args).get("error") == "needs confirmation"

    # The face cannot park a turn waiting for a yes, so anything the classifier
    # flags has to be refused here rather than run unprompted.
    check(
        "overwriting an existing file is refused",
        gated("write_file", {"path": str(victim), "content": "PWNED"}),
    )
    check(
        "a dangerous shell command is refused",
        gated("run_shell", {"command": "rm -rf /tmp/anything"}),
    )
    check("reading is still allowed", not gated("read_file", {"path": "README.md"}))
    check("diary writes are still allowed", not gated("memory_write", {"text": "note"}))

    after = victim.read_text() if victim.exists() else None
    check("soul.md survived the attempt", before == after)


def main() -> int:
    print("=" * 62)
    print("Rau agentic-upgrade acceptance")
    print("=" * 62)
    for fn in (
        test_protocol,
        test_compaction,
        test_edit_and_sandbox,
        test_nested_jobs,
        test_face_gate,
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a crash is a failure, not a stop
            check(f"{fn.__name__} raised", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 62)
    print(f"{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    if SKIP:
        print("skipped: " + ", ".join(SKIP))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
