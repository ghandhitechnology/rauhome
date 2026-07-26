"""Face talking brain — multi-turn, soul-backed, skills + escalation tools."""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from rau.agent import compaction
from rau.agent import orchestrator
from rau.agent import tools as agent_tools
from rau.agent.danger import classify_tool
from rau.events import BUS
from rau.face import choreography, panels, props, web
from rau.identity.store import load_soul
from rau.memory.store import append_diary, recent_context
from rau.providers.base import Message, StreamDone, TextDelta, tool_result_text
from rau.providers.registry import chat_for_slot, load_settings
from rau.skills import goals as goal_store
from rau.skills.loader import skills_public
from rau.skills.runtime import prepare_turn, use_skill_tool
from rau import state

FACE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_hard_task",
            "description": "Start silent deep work / computer / MCP work in the background. One at a time.",
            "parameters": {
                "type": "object",
                "properties": {"goal": {"type": "string"}},
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_hard_task",
            "description": "Cancel the current hard task.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "redirect_hard_task",
            "description": "Cancel current hard task and start a new goal.",
            "parameters": {
                "type": "object",
                "properties": {"goal": {"type": "string"}},
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": "Load a full always-available skill by name (grill-me, plan, read, write, goal, shell, search, remember, computer, summarize).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List always-available skills.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": "Set the active long-running goal.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_goal",
            "description": "Clear the active goal.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "goal_note",
            "description": "Append a progress note to the active goal.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file under the project root.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write a whole UTF-8 text file under the project root. For a "
                "file that already exists prefer edit_file — this replaces "
                "everything, and overwriting needs a confirmation the face "
                "cannot ask for."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact string in a file you have read this session. "
                "old_string must appear exactly once unless replace_all is set; "
                "include surrounding lines to make it unique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command in the project root.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Persist a note to today's diary.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_read",
            "description": "Read recent diary context.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    choreography.BODY_CHOREOGRAPHY_TOOL,
    props.MOVE_OBJECT_TOOL,
    panels.SHOW_PANEL_TOOL,
    web.BROWSE_WEB_TOOL,
]

#: The face model is chosen for latency, so its window is held far below what
#: the model would accept: a 100k-token prompt makes the face slow and
#: expensive long before it makes it forgetful.
FACE_CONTEXT_BUDGET = 12000
#: Tool output is clamped harder here than for a worker. Six rounds of the
#: transport default would outgrow the whole face budget inside a single turn,
#: and nothing folds a turn that is still being spoken.
FACE_TOOL_RESULT_LIMIT = 3000

_history: List[Message] = []
# Voice turns and typed turns can now land concurrently (the WS voice session
# runs on its own thread while /api/chat is served from the threadpool), so
# every mutation of _history goes through this.
_history_lock = threading.RLock()
# Assistant placeholders reserved by in-flight streaming turns. Keeping the
# slot in `_history` preserves ordering when a provider is slow and another
# turn starts, while snapshots hide the empty internal marker from providers.
_pending_stream_messages: set[int] = set()
# Held for the duration of a fold, so a fast exchange cannot start a second
# summarizer on top of the one already thinking.
_compacting = threading.Lock()

#: Floor on the gap between `chat_delta` broadcasts. The event bus evicts the
#: oldest item from a slow subscriber's queue, so a per-token firehose would
#: lose text on exactly the client that most needs it. Every delta therefore
#: carries the whole reply so far, and they are throttled to a rate a browser
#: can actually paint.
DELTA_INTERVAL_SEC = 0.06


class _TurnBroadcast:
    """
    Emits `chat_started` / `chat_delta` / `chat_done` for one face turn.

    Deltas are cumulative on purpose: a dropped intermediate event costs a
    frame of smoothness rather than a hole in the text that phrase-anchored
    body cues are matched against.
    """

    def __init__(self, turn_id: str, user_text: str) -> None:
        self.turn_id = turn_id
        self._seen: List[str] = []
        self._sent_len = -1
        self._next_at = 0.0
        BUS.emit("chat_started", turn_id=turn_id, text=user_text)

    @property
    def text(self) -> str:
        return "".join(self._seen)

    def token(self, token: str) -> None:
        self._seen.append(token)
        now = time.monotonic()
        if now < self._next_at:
            return
        self._next_at = now + DELTA_INTERVAL_SEC
        self.flush()

    def flush(self) -> None:
        text = self.text
        if len(text) == self._sent_len:
            return
        self._sent_len = len(text)
        BUS.emit("chat_delta", turn_id=self.turn_id, text=text)

    def done(self, spoken: str) -> None:
        self.flush()
        BUS.emit("chat_done", turn_id=self.turn_id, text=spoken)

    def error(self, detail: str) -> None:
        choreography.cancel_turn(self.turn_id, "error")
        BUS.emit("chat_error", turn_id=self.turn_id, detail=str(detail)[:500])

    def cancelled(self, heard: str) -> None:
        choreography.cancel_turn(self.turn_id, "interrupted")
        BUS.emit("chat_done", turn_id=self.turn_id, text=heard, interrupted=True)


def reset_history() -> None:
    with _history_lock:
        _history.clear()
        _pending_stream_messages.clear()


def _append_history(*msgs: Message) -> None:
    with _history_lock:
        _history.extend(msgs)


def snapshot_history() -> List[Message]:
    with _history_lock:
        return [m for m in _history if id(m) not in _pending_stream_messages]


def _reserve_stream_turn(user_text: str) -> Tuple[Message, List[Message]]:
    """Atomically reserve a history position for one streaming response."""
    user = Message(role="user", content=user_text)
    pending = Message(role="assistant", content="")
    with _history_lock:
        _history.append(user)
        messages = [m for m in _history if id(m) not in _pending_stream_messages]
        _history.append(pending)
        _pending_stream_messages.add(id(pending))
    return pending, messages


def _finish_stream_turn(pending: Message, spoken: str) -> Optional[Message]:
    """Replace an exact streaming placeholder without touching another turn."""
    committed = Message(role="assistant", content=spoken)
    result: Optional[Message] = None
    with _history_lock:
        for i, message in enumerate(_history):
            if message is pending:
                if spoken:
                    _history[i] = committed
                    result = committed
                else:
                    _history.pop(i)
                break
        _pending_stream_messages.discard(id(pending))
    return result


def _context_budget() -> int:
    return int(load_settings().get("face_context_budget") or FACE_CONTEXT_BUDGET)


def _fold_history(snapshot: List[Message], budget: int) -> None:
    """
    Summarize the front of `snapshot` and splice the result back in.

    Only the prefix it was handed is rewritten, and only if that prefix is
    still the one it read — so a turn that lands while the summarizer is
    thinking keeps its place at the end, and a reset or a barge-in rewrite
    discards the stale fold instead of resurrecting what it replaced.
    """
    try:
        folded = compaction.compact(
            snapshot, compaction.provider_summarizer("dream"), budget=budget
        )
        with _history_lock:
            prefix = _history[: len(snapshot)]
            if len(prefix) == len(snapshot) and all(
                a is b for a, b in zip(prefix, snapshot)
            ):
                _history[: len(snapshot)] = folded
    finally:
        _compacting.release()


def _maybe_compact_history() -> None:
    """
    Fold the oldest turns into a summary once the window fills up.

    Call this only where a turn has just ended. Summarizing costs a model call
    and it runs off the turn thread for that reason — paid inline it would
    stall the first token of a reply that is being spoken out loud.
    """
    budget = _context_budget()
    snapshot = snapshot_history()
    if not compaction.should_compact(snapshot, budget):
        return
    if not _compacting.acquire(blocking=False):
        return
    threading.Thread(
        target=_fold_history,
        args=(snapshot, budget),
        daemon=True,
        name="rau-face-compact",
    ).start()


def truncate_last_assistant(spoken: str) -> None:
    """
    Rewrite the last assistant turn to only what the user actually heard.

    Used after a barge-in: if we keep the full generated text, the model
    believes it said things that never reached the speaker and will not
    repeat them.
    """
    with _history_lock:
        for i in range(len(_history) - 1, -1, -1):
            if _history[i].role == "assistant":
                _history[i] = Message(role="assistant", content=spoken)
                return


def _system_prompt(extra: str = "") -> str:
    from rau.heartbeat.presence import (
        SPEECH_HABITS_PROMPT,
        between_sessions_block,
        mood_context_block,
        time_context_block,
    )

    soul = load_soul()
    ht = state.get_hard_task()
    hard = ""
    if ht.get("state") in ("running", "awaiting_confirm"):
        hard = (
            f"\n\nInner hard task status: {ht.get('state')} — goal: {ht.get('goal')}. "
            "You may chat lightly and mention you are still on it. "
            "Do not invent a second speaker."
        )
    mem = recent_context(2500)
    life = between_sessions_block()
    parts = [
        soul,
        hard,
        "\n" + time_context_block(),
        "\n" + mood_context_block(),
    ]
    if life:
        parts.append("\n" + life)
    parts.extend(
        [
            "\n## Recent memory excerpt\n" + (mem or "(empty)"),
            "\nYou have always-available skills. Prefer tools over guessing. "
            "Escalate multi-step work with start_hard_task. Only you speak.",
            "\n" + SPEECH_HABITS_PROMPT,
            "\n" + choreography.PROMPT,
            "\n" + props.prompt_fragment(),
            "\n" + panels.prompt_fragment(),
            "\n" + web.prompt_fragment(),
        ]
    )
    if extra:
        parts.append("\n" + extra)
    return "\n".join(parts)


def _run_face_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    from rau.permissions import deny_result, mode_for, tool_decision

    room_mode = mode_for("room")

    if name in ("start_hard_task", "redirect_hard_task"):
        if room_mode == "readonly":
            return deny_result(
                name, reason="room is in read-only mode — cannot start deep work"
            )
        if name == "start_hard_task":
            return orchestrator.start_hard_task(str(args.get("goal") or ""))
        return orchestrator.redirect_hard_task(str(args.get("goal") or ""))
    if name == "cancel_hard_task":
        return orchestrator.cancel_hard_task()
    if name == "use_skill":
        return use_skill_tool(str(args.get("name") or ""))
    if name == "list_skills":
        return {"ok": True, "skills": skills_public()}
    if name == "body_choreography":
        # Local, visual and reversible — nothing here leaves the machine, so it
        # never needs the confirmation the face has nowhere to wait for.
        return choreography.submit_plan(args)
    if name == "move_object":
        # Rearranging his own room: visual, local, and undoable by asking.
        return props.move_object(args)
    if name == "browse_web":
        # Reads the open web, so it is gated like the other outward-facing
        # tools rather than treated as a local visual like the room ones.
        decision = tool_decision("room", name, args)
        if decision == "deny":
            return deny_result(name, reason="room is in read-only mode")
        return web.browse_web(args)
    if name == "show_panel":
        # The markup never runs anywhere it could reach this app — see
        # rau/face/panels.py for the two barriers that make that true.
        return panels.show_panel(args)
    if name in ("set_goal", "clear_goal", "goal_note"):
        if room_mode == "readonly":
            return deny_result(name, reason="room is in read-only mode")
        if name == "set_goal":
            goal = goal_store.set_goal(str(args.get("text") or ""))
            if goal.get("ok") is False:
                return goal
            return {"ok": True, "goal": goal}
        if name == "clear_goal":
            return goal_store.clear_goal()
        return goal_store.add_note(str(args.get("text") or ""))
    if name in (
        "read_file",
        "write_file",
        "edit_file",
        "run_shell",
        "memory_write",
        "memory_read",
    ):
        decision = tool_decision("room", name, args)
        if decision == "deny":
            return deny_result(name)
        if decision == "confirm":
            # The face has nowhere to park a turn while it waits for a yes.
            # Auto mode still escalates to deep work; bypass runs below.
            needs_confirm, summary = classify_tool(name, args)
            return {
                "ok": False,
                "error": "needs confirmation",
                "summary": summary,
                "hint": (
                    "This needs the user's explicit yes, which only deep work can "
                    "ask for. Call start_hard_task with this as the goal instead."
                ),
            }
        return agent_tools.run_tool(name, args)
    return {"ok": False, "error": "unknown"}


def _record_tool_round(
    messages: List[Message],
    result: Any,
    system_extra: str,
    on_tool: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
) -> None:
    """
    Run one round of tool calls, appending the assistant/tool turns it produces.

    The assistant turn carries every call of the round at once: a provider only
    accepts a result whose call sits in the turn directly above it, so the
    results follow as their own `tool` turns rather than as narrated prose.
    """
    messages.append(
        Message(
            role="assistant",
            content=result.content,
            tool_calls=list(result.tool_calls),
        )
    )
    for tc in result.tool_calls:
        tr = _run_face_tool(tc.name, tc.arguments)
        if on_tool:
            on_tool(tc.name, tc.arguments, tr)
        if tc.name == "use_skill" and tr.get("ok") and tr.get("prompt"):
            # A freshly loaded skill only steers the next round from the system
            # prompt; left in the tool result it reads as trivia.
            messages[0] = Message(
                role="system",
                content=_system_prompt((system_extra + "\n\n" + str(tr["prompt"])).strip()),
            )
        messages.append(
            Message(
                role="tool",
                content=tool_result_text(tr, FACE_TOOL_RESULT_LIMIT),
                tool_call_id=tc.id,
                name=tc.name,
            )
        )


def _call_face(provider, slot, messages):
    return provider.chat(
        messages,
        model=slot.get("model") or "deepseek-v4-flash",
        max_tokens=int(slot.get("max_tokens") or 512),
        temperature=float(slot.get("temperature") or 0.9),
        tools=FACE_TOOLS,
        effort=str(slot.get("effort") or "medium"),
    )


def chat(user_text: str, *, turn_id: Optional[str] = None) -> str:
    """
    Non-streaming face reply (handles skills + tools).

    `turn_id` names the turn any `body_choreography` call is scoped to. Callers
    that need it up front (the hub, so it can answer with it) pass their own;
    everything else gets one generated here, so no path can produce a reply the
    model was unable to choreograph.
    """
    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    turn = turn_id or choreography.new_turn_id()
    broadcast = _TurnBroadcast(turn, user_text)
    # Snapshot absence before history is used (idempotent if note_user_reply ran).
    begin_user_turn()

    try:
        prep = prepare_turn(user_text)
        if prep.immediate_reply and (prep.activate == [] or "goal" in prep.activate):
            # Meta commands like /skills, /effort and /goal — hub/pipeline own the
            # chat log, and there is no model turn to choreograph.
            append_diary("user", user_text)
            append_diary("rau", prep.immediate_reply)
            broadcast.done(prep.immediate_reply)
            return prep.immediate_reply

        provider, slot = chat_for_slot("face")
        turn_text = prep.user_text
        _append_history(Message(role="user", content=turn_text))
        messages = [
            Message(role="system", content=_system_prompt(prep.system_extra))
        ] + snapshot_history()

        spoken = ""
        try:
            with choreography.turn_scope(turn):
                for _ in range(6):
                    result = _call_face(provider, slot, messages)
                    if result.tool_calls:
                        _record_tool_round(messages, result, prep.system_extra)
                        continue
                    spoken = (result.content or "").strip()
                    break
        except Exception as exc:
            broadcast.error(str(exc))
            raise

        if not spoken:
            spoken = "Okay. I'm with you."
        from rau.heartbeat.presence import apply_reply_mood

        spoken, _ = apply_reply_mood(spoken)
        _append_history(Message(role="assistant", content=spoken))
        _maybe_compact_history()
        append_diary("user", user_text)
        append_diary("rau", spoken)
        broadcast.done(spoken)
        return spoken
    finally:
        end_user_turn()


class Cancelled(Exception):
    """A cancelled stream plus the exact history slot that belongs to it."""

    def __init__(
        self,
        pending: Optional[Message] = None,
        generated: str = "",
        user_text: str = "",
        turn_id: str = "",
    ) -> None:
        super().__init__("streaming turn cancelled")
        self.pending = pending
        self.generated = generated
        self.user_text = user_text
        self.turn_id = turn_id


class StreamingReply(str):
    """String-compatible reply carrying its exact committed history message."""

    history_message: Optional[Message]
    user_text: str
    diary_deferred: bool
    turn_id: str

    def __new__(
        cls,
        value: str,
        history_message: Optional[Message],
        user_text: str,
        diary_deferred: bool,
        turn_id: str = "",
    ):
        obj = str.__new__(cls, value)
        obj.history_message = history_message
        obj.user_text = user_text
        obj.diary_deferred = diary_deferred
        obj.turn_id = turn_id
        return obj


def finish_interrupted_turn(
    turn: Cancelled | StreamingReply,
    heard: str,
) -> None:
    """Commit only audible prose for a cancelled stream, in its original slot."""
    marker = (
        turn.pending if isinstance(turn, Cancelled) else turn.history_message
    )
    if marker is None:
        if isinstance(turn, StreamingReply) and turn.diary_deferred:
            append_diary("user", turn.user_text)
            if heard:
                append_diary("rau", heard)
            turn.diary_deferred = False
        return

    note = Message(
        role="system",
        content=(
            "(You were interrupted here — the user began speaking before you "
            "finished. Do not repeat what you already said. Acknowledge them "
            "naturally and respond to what they actually asked.)"
        ),
    )
    assistant = Message(role="assistant", content=heard)
    finished = False
    with _history_lock:
        for i, message in enumerate(_history):
            if message is marker:
                _history[i : i + 1] = [assistant, note] if heard else [note]
                finished = True
                break
        _pending_stream_messages.discard(id(marker))

    if not finished:
        return
    append_diary("user", turn.user_text)
    if heard:
        append_diary("rau", heard)
    if isinstance(turn, StreamingReply):
        turn.diary_deferred = False
    _maybe_compact_history()


def commit_streamed_turn(reply: StreamingReply) -> None:
    """Commit deferred voice diary entries once playback finishes normally."""
    if not reply.diary_deferred:
        return
    append_diary("user", reply.user_text)
    append_diary("rau", str(reply))
    reply.diary_deferred = False
    _maybe_compact_history()


def chat_streaming(
    user_text: str,
    *,
    on_token: Callable[[str], None],
    on_tool: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
    cancel: Optional[threading.Event] = None,
    defer_diary: bool = False,
    turn_id: Optional[str] = None,
) -> str:
    """
    Streaming face turn that keeps full tool access.

    Same six-round loop as `chat()` — the only differences are that prose is
    handed to `on_token` as it arrives and that `cancel` is honoured between
    tokens and rounds. Tool plumbing never reaches `on_token`; only assistant
    prose does, or Rau would read protocol out loud.

    `turn_id` scopes any `body_choreography` the model calls, and is echoed on
    every `chat_*` event so a client can tie a plan to the text it anchors to.

    Returns everything generated. The caller is responsible for trimming the
    history to what was actually spoken if it cancelled (see
    `truncate_last_assistant`).
    """
    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    turn = turn_id or choreography.new_turn_id()
    broadcast = _TurnBroadcast(turn, user_text)
    begin_user_turn()

    def stop() -> bool:
        return cancel is not None and cancel.is_set()

    def emit(token: str) -> None:
        broadcast.token(token)
        on_token(token)

    try:
        prep = prepare_turn(user_text)
        if prep.immediate_reply and (prep.activate == [] or "goal" in prep.activate):
            on_token(prep.immediate_reply)
            broadcast.done(prep.immediate_reply)
            if defer_diary:
                return StreamingReply(prep.immediate_reply, None, user_text, True, turn)
            append_diary("user", user_text)
            append_diary("rau", prep.immediate_reply)
            return prep.immediate_reply

        provider, slot = chat_for_slot("face")
        pending, history = _reserve_stream_turn(prep.user_text)
        messages = [
            Message(role="system", content=_system_prompt(prep.system_extra))
        ] + history

        # Every token handed to on_token was actually spoken aloud, including the
        # "let me look that up" said before a tool fires. Blocking chat() throws
        # that prose away because it never reaches the user; here it must be
        # remembered, or Rau will not know he already acknowledged the request.
        heard: List[str] = []

        try:
            with choreography.turn_scope(turn):
                for _ in range(6):
                    if stop():
                        raise Cancelled(pending, "".join(heard).strip(), user_text, turn)

                    chunks: List[str] = []
                    result = None
                    for event in provider.stream_turn(
                        messages,
                        model=slot.get("model") or "deepseek-v4-flash",
                        max_tokens=int(slot.get("max_tokens") or 512),
                        temperature=float(slot.get("temperature") or 0.9),
                        tools=FACE_TOOLS,
                        effort=str(slot.get("effort") or "medium"),
                    ):
                        if stop():
                            raise Cancelled(
                                pending, "".join(heard).strip(), user_text, turn
                            )
                        if isinstance(event, TextDelta):
                            chunks.append(event.text)
                            heard.append(event.text)
                            emit(event.text)
                        elif isinstance(event, StreamDone):
                            result = event.result
                    if result is None:
                        break

                    if result.tool_calls:
                        _record_tool_round(messages, result, prep.system_extra, on_tool)
                        continue

                    if not chunks and result.content:
                        # Provider returned prose only in the terminal event.
                        heard.append(result.content)
                        emit(result.content)
                    break
        except Cancelled:
            broadcast.cancelled("".join(heard).strip())
            raise
        except Exception as exc:
            # A provider can fail after yielding prose. Preserve that partial reply
            # in the reserved slot; an empty failure must not leave a ghost turn.
            _finish_stream_turn(pending, "".join(heard).strip())
            broadcast.error(str(exc))
            raise

        spoken = "".join(heard).strip()
        if not spoken:
            spoken = "Okay. I'm with you."
            emit(spoken)
        from rau.heartbeat.presence import apply_reply_mood

        spoken, _ = apply_reply_mood(spoken)
        history_message = _finish_stream_turn(pending, spoken)
        if not defer_diary:
            _maybe_compact_history()
        if not defer_diary:
            append_diary("user", user_text)
            append_diary("rau", spoken)
        broadcast.done(spoken)
        return StreamingReply(spoken, history_message, user_text, defer_diary, turn)
    finally:
        end_user_turn()


def chat_stream(user_text: str) -> Generator[str, None, str]:
    # Skills/tools path is non-stream for reliability
    if user_text.strip().startswith("/") or any(
        k in user_text.lower()
        for k in (
            "research",
            "look up",
            "computer",
            "open ",
            "send ",
            "fix this",
            "deep",
            "cancel",
            "stop working",
            "read ",
            "write ",
            "plan ",
            "grill",
        )
    ):
        text = chat(user_text)
        yield text
        return text

    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    begin_user_turn()
    try:
        prep = prepare_turn(user_text)
        provider, slot = chat_for_slot("face")
        _append_history(Message(role="user", content=prep.user_text))
        messages = [
            Message(role="system", content=_system_prompt(prep.system_extra))
        ] + snapshot_history()
        accum: List[str] = []
        try:
            for token in provider.chat_stream(
                messages,
                model=slot.get("model") or "deepseek-v4-flash",
                max_tokens=int(slot.get("max_tokens") or 512),
                temperature=float(slot.get("temperature") or 0.9),
                effort=str(slot.get("effort") or "medium"),
            ):
                accum.append(token)
                yield token
        except Exception:
            # undo last user append then full chat
            with _history_lock:
                if _history and _history[-1].role == "user":
                    _history.pop()
            end_user_turn()
            text = chat(user_text)
            yield text
            return text

        spoken = "".join(accum).strip() or "Okay."
        from rau.heartbeat.presence import apply_reply_mood

        spoken, _ = apply_reply_mood(spoken)
        _append_history(Message(role="assistant", content=spoken))
        _maybe_compact_history()
        append_diary("user", user_text)
        append_diary("rau", spoken)
        return spoken
    finally:
        end_user_turn()


def extract_emotion(text: str) -> Tuple[str, Optional[str]]:
    match = re.search(
        r"\[(HAPPY|CURIOUS|EXCITED|SAD|SCARED|AMAZED|LOVE|DETERMINED|IDLE)\]",
        text,
        re.I,
    )
    if match:
        tag = match.group(1).upper()
        clean = text.replace(match.group(0), "").strip()
        return clean, tag
    return text, None


def weave_result(goal: str, result: str) -> str:
    prompt = (
        f"Your silent inner work finished.\nGoal: {goal}\nResult:\n{result}\n\n"
        "Speak to your friend as yourself — brief, natural, no mention of agents or tools teams."
    )
    return chat(prompt)
