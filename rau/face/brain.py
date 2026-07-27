"""Face talking brain — multi-turn, soul-backed, skills + escalation tools."""
from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from rau.agent import compaction
from rau.agent import orchestrator
from rau.agent import tools as agent_tools
from rau.agent.danger import classify_tool
from rau.events import BUS
from rau.activity import ACTIVITY
from rau.face import choreography, panels, props, web
from rau.games.kittens import session as kittens
from rau.games.kittens import tools as kittens_tools
from rau.identity.store import load_soul
from rau.memory.store import append_diary, recent_context
from rau.providers.base import (
    Message,
    ReasoningDelta,
    StreamDone,
    TextDelta,
    tool_result_text,
)
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
    panels.LIST_PANELS_TOOL,
    panels.UPDATE_PANEL_TOOL,
    panels.CLOSE_PANEL_TOOL,
    panels.PRESENT_PANEL_TOOL,
    panels.COMMISSION_PANEL_TOOL,
    web.BROWSE_WEB_TOOL,
    # Deal and clear only — playing cards is the player half's job.
    kittens_tools.START_GAME_TOOL,
    kittens_tools.END_GAME_TOOL,
]

#: The face model is chosen for latency, so its window is held far below what
#: the model would accept: a 100k-token prompt makes the face slow and
#: expensive long before it makes it forgetful.
FACE_CONTEXT_BUDGET = 12000
#: Tool output is clamped harder here than for a worker. Six rounds of the
#: transport default would outgrow the whole face budget inside a single turn,
#: and nothing folds a turn that is still being spoken.
FACE_TOOL_RESULT_LIMIT = 3000
#: Voice turns keep a leaner diary excerpt so prefill stays short.
VOICE_MEMORY_CHARS = 1000
CHAT_MEMORY_CHARS = 2500
#: Default voice tool surface — conversational + room + browse. Heavy
#: file/shell/hard-task schemas join on round 2+ or explicit deep-work intent.
VOICE_SLIM_TOOL_NAMES = frozenset(
    {
        "memory_write",
        "memory_read",
        "body_choreography",
        "move_object",
        # The whole panel surface stays on round 0: "make me a dashboard of
        # this" and "change that number" are ordinary spoken requests, and
        # making them wait for round 2 is what made them feel unreachable.
        "show_panel",
        "list_panels",
        "update_panel",
        "close_panel",
        "present_panel",
        "commission_panel",
        "browse_web",
        "use_skill",
        "list_skills",
        "set_goal",
        "clear_goal",
        "goal_note",
        # "let's play" deals on round 0. Playing cards mid-hand is the player
        # half's job, not the talker's — so play_kittens_card stays off this set.
        "start_kittens",
        "end_kittens",
    }
)
_DEEP_WORK_MARKERS = (
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
    "edit ",
    "plan ",
    "grill",
    "shell",
    "run ",
    "file",
    # A visual request is usually a deep-work request wearing a friendly hat —
    # the numbers have to be found before anything can be drawn.
    "dashboard",
    "chart",
    "graph",
    "plot",
    "visuali",
)
VOICE_TOOL_OPENER = (
    "## Voice turn\n"
    "Before any tool call, speak one short clause first "
    '(e.g. "One sec—", "Looking…"). Never sit silent while tools run. '
    "Do not use thinking fillers as padding."
)
#: Tools that mean real computer work — the avatar walks to the desk.
#: Body/room visuals (choreography, props, panels) are excluded; browse_web
#: already brackets itself with browse_started / browse_finished.
DESK_WORK_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "run_shell",
        "memory_write",
        "memory_read",
        "use_skill",
        "list_skills",
        "start_hard_task",
        "cancel_hard_task",
        "redirect_hard_task",
        # Commissioning is deep work under a friendlier name, so he walks over
        # and sets it going. The other wall tools stay excluded with show_panel.
        "commission_panel",
        "set_goal",
        "clear_goal",
        "goal_note",
    }
)
DESK_WORK_MOTION: Dict[str, str] = {
    "run_shell": "type",
    "read_file": "type",
    "write_file": "type",
    "edit_file": "type",
    "memory_read": "search",
    "memory_write": "type",
    "use_skill": "type",
    "list_skills": "type",
    "start_hard_task": "type",
    "cancel_hard_task": "type",
    "redirect_hard_task": "type",
    "commission_panel": "type",
}
DESK_WORK_WATCHDOG_MS = 90_000

_soul_cache: Optional[str] = None
_soul_mtime: float = -1.0
_static_instructions: Optional[str] = None


def clear_prompt_caches() -> None:
    """Drop cached soul/static prompt fragments (tests / soul rewrite)."""
    global _soul_cache, _soul_mtime, _static_instructions
    _soul_cache = None
    _soul_mtime = -1.0
    _static_instructions = None

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
#: One face turn at a time. A typed turn and a spoken turn running their model
#: calls concurrently would braid two replies into one history, so the second
#: caller gets a clear busy answer instead of a parallel turn.
_face_turn_lock = threading.Lock()
#: Guards the diary_deferred hand-off on a StreamingReply: a barge-in and a
#: normal playback end can race to commit the same reply, and exactly one of
#: them may write the diary.
_deferred_diary_lock = threading.Lock()

#: What the second of two concurrent face turns hears.
BUSY_REPLY = "One moment — I'm still answering the last one."

#: How long a system-originated turn waits for the face turn in flight before
#: it, too, settles for the busy answer. A user turn bounces immediately; a
#: deep-work result landing mid-reply has no user to re-ask, so it waits.
SYSTEM_TURN_WAIT_SEC = 30.0

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


def _face_max_tokens(slot: Dict[str, Any]) -> int:
    from rau.resources import current_profile

    return min(
        int(slot.get("max_tokens") or 512),
        int(current_profile()["face_max_tokens"]),
    )


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
    try:
        threading.Thread(
            target=_fold_history,
            args=(snapshot, budget),
            daemon=True,
            name="rau-face-compact",
        ).start()
    except Exception:
        # A thread that never started will never reach _fold_history's finally.
        _compacting.release()


def _cached_soul() -> str:
    """Disk-backed soul with mtime cache — avoids re-reading every turn."""
    global _soul_cache, _soul_mtime
    from rau.paths import SOUL_MD

    try:
        mtime = SOUL_MD.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _soul_cache is None or mtime != _soul_mtime:
        _soul_cache = load_soul()
        _soul_mtime = mtime
    return _soul_cache


def _cached_static_instructions() -> str:
    """Soul-adjacent instructions that do not change with mood/memory/room."""
    global _static_instructions
    if _static_instructions is None:
        from rau.heartbeat.presence import SPEECH_HABITS_PROMPT

        _static_instructions = "\n".join(
            [
                "You have always-available skills. Prefer tools over guessing. "
                "Escalate multi-step work with start_hard_task. Only you speak.",
                SPEECH_HABITS_PROMPT,
                choreography.PROMPT,
            ]
        )
    return _static_instructions


def _wants_deep_tools(user_text: str) -> bool:
    lower = (user_text or "").lower()
    return any(marker in lower for marker in _DEEP_WORK_MARKERS)


def _tools_for_turn(*, voice: bool, round_idx: int, user_text: str) -> List[Dict[str, Any]]:
    if not voice:
        return FACE_TOOLS
    if round_idx > 0 or _wants_deep_tools(user_text):
        return FACE_TOOLS
    return [
        tool
        for tool in FACE_TOOLS
        if tool.get("function", {}).get("name") in VOICE_SLIM_TOOL_NAMES
    ]


def _system_prompt(extra: str = "", *, voice: bool = False) -> str:
    from rau.heartbeat.presence import (
        between_sessions_block,
        mood_context_block,
        time_context_block,
    )

    soul = _cached_soul()
    ht = state.get_hard_task()
    hard = ""
    if ht.get("state") in ("running", "awaiting_confirm"):
        hard = (
            f"\n\nInner hard task status: {ht.get('state')} — goal: {ht.get('goal')}. "
            "You may chat lightly and mention you are still on it. "
            "Do not invent a second speaker."
        )
    mem = recent_context(VOICE_MEMORY_CHARS if voice else CHAT_MEMORY_CHARS)
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
            "\n" + _cached_static_instructions(),
            "\n" + props.prompt_fragment(),
            "\n" + panels.prompt_fragment(),
            "\n" + web.prompt_fragment(),
        ]
    )
    # Only while a game is on the table. Between games it costs nothing, and
    # during one it is the difference between an opponent and a card shuffler.
    game = kittens.prompt_fragment()
    if game:
        parts.append("\n" + game)
    if voice:
        parts.append("\n" + VOICE_TOOL_OPENER)
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
            return orchestrator.start_hard_task(
                str(args.get("goal") or ""),
                origin_turn_id=choreography.current_turn_id() or None,
            )
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
    if name in kittens_tools.TOOL_NAMES:
        # A game of cards moves cards. Nothing here touches the filesystem, the
        # network, or anything a confirmation would be protecting.
        return kittens_tools.run_tool(name, args)
    if name == "browse_web":
        # Reads the open web, so it is gated like the other outward-facing
        # tools rather than treated as a local visual like the room ones.
        decision = tool_decision("room", name, args)
        if decision == "deny":
            return deny_result(name, reason="room is in read-only mode")
        return web.browse_web(args)
    if name == "show_panel":
        # The markup never runs anywhere it could reach this app — see
        # rau/face/panels.py for the two barriers that make that true. The rest
        # of the wall tools inherit that reasoning: they only ever move panels
        # around, and none of them reach the filesystem or the network.
        return panels.show_panel(args)
    if name == "list_panels":
        return {"ok": True, "panels": panels.list_panels()}
    if name == "update_panel":
        return panels.update_panel(args)
    if name == "close_panel":
        if room_mode == "readonly":
            # Unlike the others this one destroys something, permanently.
            return deny_result(name, reason="room is in read-only mode")
        return panels.close_panel(str(args.get("panel_id") or ""))
    if name == "present_panel":
        return panels.present_panel(str(args.get("panel_id") or ""))
    if name == "commission_panel":
        if room_mode == "readonly":
            return deny_result(
                name, reason="room is in read-only mode — cannot start deep work"
            )
        return panels.commission(
            str(args.get("goal") or ""),
            origin_turn_id=choreography.current_turn_id() or None,
        )
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


def _desk_tool_start(name: str, args: Dict[str, Any]) -> Optional[str]:
    """Tell the room he is working at the computer. None when not desk work."""
    if name not in DESK_WORK_TOOLS:
        return None
    activity_id = f"tool_{uuid.uuid4().hex[:12]}"
    detail = ""
    if name == "run_shell":
        detail = str(args.get("command") or "")
    elif name in ("read_file", "write_file", "edit_file"):
        detail = str(args.get("path") or "")
    elif name in ("memory_write", "set_goal", "goal_note", "start_hard_task", "redirect_hard_task"):
        detail = str(args.get("text") or args.get("goal") or "")
    elif name == "use_skill":
        detail = str(args.get("name") or "")
    BUS.emit(
        "tool_started",
        activity_id=activity_id,
        turn_id=choreography.current_turn_id() or "",
        name=name,
        motion=DESK_WORK_MOTION.get(name, "type"),
        detail=detail[:200],
        watchdog_ms=DESK_WORK_WATCHDOG_MS,
    )
    return activity_id


def _desk_tool_finish(
    activity_id: Optional[str], *, name: str, ok: bool
) -> None:
    if not activity_id:
        return
    BUS.emit(
        "tool_finished",
        activity_id=activity_id,
        turn_id=choreography.current_turn_id() or "",
        name=name,
        ok=bool(ok),
    )


def _record_tool_round(
    messages: List[Message],
    result: Any,
    system_extra: str,
    on_tool: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
    *,
    voice: bool = False,
    skill_prompts: Optional[List[str]] = None,
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
            reasoning=str(getattr(result, "reasoning", "") or ""),
            reasoning_details=getattr(result, "reasoning_details", None),
        )
    )
    for tc in result.tool_calls:
        turn_id = choreography.current_turn_id() or None
        label = {
            "read_file": "Reading a file",
            "write_file": "Writing a file",
            "edit_file": "Editing a file",
            "run_shell": "Running a command",
            "browse_web": "Browsing the web",
            "start_hard_task": "Starting deep work",
            "body_choreography": "Planning movement",
            "start_kittens": "Dealing a game",
            "end_kittens": "Clearing the table",
            "show_panel": "Making something to look at",
            "list_panels": "Looking at the wall",
            "update_panel": "Changing a panel",
            "close_panel": "Taking a panel down",
            "present_panel": "Putting a panel up on screen",
            "commission_panel": "Sending someone to build a panel",
        }.get(tc.name, f"Using {tc.name.replace('_', ' ')}")
        public_span = ACTIVITY.start(
            "tool",
            label,
            source="face",
            turn_id=turn_id,
            details={"tool": tc.name, "arguments": tc.arguments},
            # Preserve the established choreography ordering: the plan event
            # reaches the body first, while the tool span is still persisted
            # synchronously before execution.
            broadcast=tc.name != "body_choreography",
        )
        activity_id = _desk_tool_start(tc.name, tc.arguments)
        try:
            tr = _run_face_tool(tc.name, tc.arguments)
        except Exception as exc:
            _desk_tool_finish(activity_id, name=tc.name, ok=False)
            if tc.name == "body_choreography":
                ACTIVITY.announce(public_span["id"])
            ACTIVITY.finish(
                public_span["id"],
                status="failed",
                summary=f"{label} failed",
                details={"tool": tc.name, "error": str(exc)},
            )
            raise
        _desk_tool_finish(activity_id, name=tc.name, ok=bool(tr.get("ok", True)))
        if tc.name == "body_choreography":
            ACTIVITY.announce(public_span["id"])
        ok = bool(tr.get("ok", True))
        ACTIVITY.finish(
            public_span["id"],
            status="completed" if ok else "failed",
            summary=(
                str(tr.get("summary") or "Finished")
                if ok
                else str(tr.get("error") or "Tool failed")
            ),
            details={
                "tool": tc.name,
                "ok": ok,
                "result": tr,
            },
        )
        if on_tool:
            on_tool(tc.name, tc.arguments, tr)
        if tc.name == "use_skill" and tr.get("ok") and tr.get("prompt"):
            # A freshly loaded skill only steers the next round from the system
            # prompt; left in the tool result it reads as trivia. Skills loaded
            # earlier this turn accumulate rather than replacing each other.
            if skill_prompts is not None:
                skill_prompts.append(str(tr["prompt"]))
            loaded = skill_prompts if skill_prompts is not None else [str(tr["prompt"])]
            messages[0] = Message(
                role="system",
                content=_system_prompt(
                    (system_extra + "".join("\n\n" + p for p in loaded)).strip(),
                    voice=voice,
                ),
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
        max_tokens=_face_max_tokens(slot),
        temperature=float(slot.get("temperature") or 0.9),
        tools=FACE_TOOLS,
        effort=str(slot.get("effort") or "medium"),
    )


def _journal_table_chat(user_text: str, reply: str) -> None:
    """While a hand is on, both halves need to see the banter."""
    if not kittens.active():
        return
    from rau.games.kittens import journal as kittens_journal

    kittens_journal.record("user", "user_chat", user_text)
    kittens_journal.record("rau", "rau_chat", reply)
    # He has just answered them properly. Hold the proactive table talk back
    # for a beat so the next thing they hear is not him talking over himself.
    from rau.games.kittens import banter as kittens_banter

    kittens_banter.note_user_chat()


def chat(
    user_text: str,
    *,
    turn_id: Optional[str] = None,
    _wait_for_turn: bool = False,
) -> str:
    """
    Non-streaming face reply (handles skills + tools).

    `turn_id` names the turn any `body_choreography` call is scoped to. Callers
    that need it up front (the hub, so it can answer with it) pass their own;
    everything else gets one generated here, so no path can produce a reply the
    model was unable to choreograph.

    `_wait_for_turn` is for system-originated turns (see weave_result): they
    block on the turn in flight for up to SYSTEM_TURN_WAIT_SEC instead of
    bouncing straight to BUSY_REPLY.
    """
    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    turn = turn_id or choreography.new_turn_id()
    broadcast = _TurnBroadcast(turn, user_text)
    # Snapshot absence before history is used (idempotent if note_user_reply ran).
    begin_user_turn()
    if _wait_for_turn:
        acquired = _face_turn_lock.acquire(timeout=SYSTEM_TURN_WAIT_SEC)
    else:
        acquired = _face_turn_lock.acquire(blocking=False)
    if not acquired:
        broadcast.done(BUSY_REPLY)
        end_user_turn()
        return BUSY_REPLY

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
                skill_prompts: List[str] = []
                for _ in range(6):
                    result = _call_face(provider, slot, messages)
                    if result.tool_calls:
                        _record_tool_round(
                            messages,
                            result,
                            prep.system_extra,
                            skill_prompts=skill_prompts,
                        )
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
        _journal_table_chat(user_text, spoken)
        broadcast.done(spoken)
        return spoken
    finally:
        end_user_turn()
        _face_turn_lock.release()


class Cancelled(Exception):
    """A cancelled stream plus the exact history slot that belongs to it."""

    def __init__(
        self,
        pending: Optional[Message] = None,
        generated: str = "",
        user_text: str = "",
        turn_id: str = "",
        tools_ran: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        super().__init__("streaming turn cancelled")
        self.pending = pending
        self.generated = generated
        self.user_text = user_text
        self.turn_id = turn_id
        self.tools_ran = list(tools_ran or [])


class StreamingReply(str):
    """String-compatible reply carrying its exact committed history message."""

    history_message: Optional[Message]
    user_text: str
    diary_deferred: bool
    turn_id: str
    tools_ran: List[Tuple[str, str]]

    def __new__(
        cls,
        value: str,
        history_message: Optional[Message],
        user_text: str,
        diary_deferred: bool,
        turn_id: str = "",
        tools_ran: Optional[List[Tuple[str, str]]] = None,
    ):
        obj = str.__new__(cls, value)
        obj.history_message = history_message
        obj.user_text = user_text
        obj.diary_deferred = diary_deferred
        obj.turn_id = turn_id
        obj.tools_ran = list(tools_ran or [])
        return obj


def _claim_deferred_diary(reply: StreamingReply) -> bool:
    """Take ownership of a deferred diary write, exactly once."""
    with _deferred_diary_lock:
        if not reply.diary_deferred:
            return False
        reply.diary_deferred = False
        return True


def finish_interrupted_turn(
    turn: Cancelled | StreamingReply,
    heard: str,
) -> None:
    """Commit only audible prose for a cancelled stream, in its original slot."""
    marker = (
        turn.pending if isinstance(turn, Cancelled) else turn.history_message
    )
    if marker is None:
        if isinstance(turn, StreamingReply) and _claim_deferred_diary(turn):
            append_diary("user", turn.user_text)
            if heard:
                append_diary("rau", heard)
            _journal_table_chat(turn.user_text, heard)
        return

    # The note rides as a user-role parenthetical, never role="system": the
    # Anthropic encoder hoists every system message into the persistent system
    # prompt, where a one-time "you were interrupted" would steer all later
    # turns.
    note = Message(
        role="user",
        content=(
            "(You were interrupted here — the user began speaking before you "
            "finished. Do not repeat what you already said. Acknowledge them "
            "naturally and respond to what they actually asked.)"
        ),
    )
    # Tools that already ran leave a one-line marker behind, or the next turn
    # has no idea the work happened and may repeat or contradict it.
    tools_ran = list(getattr(turn, "tools_ran", None) or [])
    markers = (
        [
            Message(
                role="user",
                content="\n".join(
                    f"(tool {name} ran: {summary})" for name, summary in tools_ran
                ),
            )
        ]
        if tools_ran
        else []
    )
    assistant = Message(role="assistant", content=heard)
    finished = False
    with _history_lock:
        # The identity scan doubles as the idempotency guard: only the first
        # caller still finds the marker, so a second finish is a no-op.
        for i, message in enumerate(_history):
            if message is marker:
                replacement = ([assistant] if heard else []) + markers + [note]
                _history[i : i + 1] = replacement
                finished = True
                break
        _pending_stream_messages.discard(id(marker))

    if not finished:
        return
    if isinstance(turn, StreamingReply) and not _claim_deferred_diary(turn):
        return
    append_diary("user", turn.user_text)
    if heard:
        append_diary("rau", heard)
    _journal_table_chat(turn.user_text, heard)
    _maybe_compact_history()


def commit_streamed_turn(reply: StreamingReply) -> None:
    """Commit deferred voice diary entries once playback finishes normally."""
    if not _claim_deferred_diary(reply):
        return
    append_diary("user", reply.user_text)
    append_diary("rau", str(reply))
    # Table talk is journaled here — when playback has drained, not when
    # generation ended — so the game record holds only aired words.
    _journal_table_chat(reply.user_text, str(reply))
    _maybe_compact_history()


class _LeadingEmotionTag:
    """
    Holds back the very start of a streamed reply until a leading mood tag is
    resolved, so `[HAPPY]` never reaches `on_token`/TTS. Once the opening is
    known — tag or not — everything else passes through untouched, and the
    raw text still lands in `heard` for `apply_reply_mood` to read the mood
    from at the end of the turn.
    """

    _TAG = re.compile(
        r"\[(HAPPY|CURIOUS|EXCITED|SAD|SCARED|AMAZED|LOVE|DETERMINED|IDLE)\]",
        re.I,
    )
    _LONGEST = len("[DETERMINED]")

    def __init__(self) -> None:
        self._buffer = ""
        self._resolved = False

    def feed(self, token: str) -> str:
        """Return the part of `token` safe to speak right now (maybe empty)."""
        if self._resolved:
            return token
        self._buffer += token
        text = self._buffer
        if not text:
            return ""
        if not text.startswith("["):
            return self._release(text)
        close = text.find("]")
        if close == -1:
            # Still could be a tag — unless it has already grown past the
            # longest one, in which case it is ordinary prose with a bracket.
            if len(text) <= self._LONGEST:
                return ""
            return self._release(text)
        head = text[: close + 1]
        if not self._TAG.fullmatch(head):
            return self._release(text)
        return self._release(text[close + 1 :].lstrip())

    def flush(self) -> str:
        """Release whatever is still buffered at the end of the stream."""
        return self._release(self._buffer)

    def _release(self, text: str) -> str:
        self._buffer = ""
        self._resolved = True
        return text


def chat_streaming(
    user_text: str,
    *,
    on_token: Callable[[str], None],
    on_tool: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
    cancel: Optional[threading.Event] = None,
    defer_diary: bool = False,
    turn_id: Optional[str] = None,
    voice: bool = False,
) -> str:
    """
    Streaming face turn that keeps full tool access.

    Same six-round loop as `chat()` — the only differences are that prose is
    handed to `on_token` as it arrives and that `cancel` is honoured between
    tokens and rounds. Tool plumbing never reaches `on_token`; only assistant
    prose does, or Rau would read protocol out loud.

    `turn_id` scopes any `body_choreography` the model calls, and is echoed on
    every `chat_*` event so a client can tie a plan to the text it anchors to.

    Returns everything generated. The caller is responsible for committing only
    what was actually spoken if it cancelled (see `finish_interrupted_turn`).
    """
    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    turn = turn_id or choreography.new_turn_id()
    broadcast = _TurnBroadcast(turn, user_text)
    begin_user_turn()
    if not _face_turn_lock.acquire(blocking=False):
        # A second face turn would braid its reply into the one being spoken.
        on_token(BUSY_REPLY)
        broadcast.done(BUSY_REPLY)
        end_user_turn()
        return BUSY_REPLY

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
            Message(
                role="system",
                content=_system_prompt(prep.system_extra, voice=voice),
            )
        ] + history

        # Every token handed to on_token was actually spoken aloud, including the
        # "let me look that up" said before a tool fires. Blocking chat() throws
        # that prose away because it never reaches the user; here it must be
        # remembered, or Rau will not know he already acknowledged the request.
        heard: List[str] = []

        # Tools that executed this turn, as (name, one-line summary). If the
        # user barges in, finish_interrupted_turn folds them into history so
        # the next turn knows the work really happened.
        tools_ran: List[Tuple[str, str]] = []

        def note_tool(name: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
            if result.get("ok", True):
                summary = str(result.get("summary") or "ok")
            else:
                summary = str(result.get("error") or "failed")
            tools_ran.append((name, summary[:80]))
            if on_tool:
                on_tool(name, args, result)

        # Strips a leading "[HAPPY]"-style tag before it can be read aloud; the
        # raw text stays in `heard` for apply_reply_mood at the end of the turn.
        leading_tag = _LeadingEmotionTag()

        def emit_prose(token: str) -> None:
            visible = leading_tag.feed(token)
            if visible:
                emit(visible)

        reasoning_span_id: Optional[str] = None
        response_span_id: Optional[str] = None
        try:
            with choreography.turn_scope(turn):
                skill_prompts: List[str] = []
                for round_idx in range(6):
                    if stop():
                        raise Cancelled(
                            pending, "".join(heard).strip(), user_text, turn, tools_ran
                        )

                    chunks: List[str] = []
                    result = None
                    # The last round gets no tools: after five rounds of calls
                    # the model must close in prose, or the reply is nothing
                    # but the "one sec" narration said before each call.
                    closing = round_idx == 5
                    tools = None if closing else _tools_for_turn(
                        voice=voice, round_idx=round_idx, user_text=user_text
                    )
                    for event in provider.stream_turn(
                        messages,
                        model=slot.get("model") or "deepseek-v4-flash",
                        max_tokens=_face_max_tokens(slot),
                        temperature=float(slot.get("temperature") or 0.9),
                        tools=tools,
                        effort=str(slot.get("effort") or "medium"),
                    ):
                        if stop():
                            raise Cancelled(
                                pending, "".join(heard).strip(), user_text, turn, tools_ran
                            )
                        if isinstance(event, TextDelta):
                            chunks.append(event.text)
                            heard.append(event.text)
                            emit_prose(event.text)
                            # Create this only after the first visible token so
                            # activity persistence cannot lengthen TTFT.
                            if response_span_id is None:
                                response_span_id = ACTIVITY.start(
                                    "execution",
                                    "Responding",
                                    source="face",
                                    summary="Composing the response",
                                    turn_id=turn,
                                )["id"]
                        elif isinstance(event, ReasoningDelta):
                            if reasoning_span_id is None:
                                reasoning_span_id = ACTIVITY.start(
                                    "reasoning",
                                    "Reasoning",
                                    source=getattr(
                                        event, "provider_format", "provider"
                                    ),
                                    summary="",
                                    turn_id=turn,
                                )["id"]
                            ACTIVITY.delta(reasoning_span_id, text=event.text)
                        elif isinstance(event, StreamDone):
                            result = event.result
                    if result is None:
                        break

                    if result.tool_calls:
                        _record_tool_round(
                            messages,
                            result,
                            prep.system_extra,
                            note_tool,
                            voice=voice,
                            skill_prompts=skill_prompts,
                        )
                        if not closing:
                            continue
                        # A provider that calls tools with none on the table has
                        # spent the closing round; whatever prose came with the
                        # calls is the close this turn gets.

                    if not chunks and result.content:
                        # Provider returned prose only in the terminal event.
                        heard.append(result.content)
                        emit_prose(result.content)
                    break
                tail = leading_tag.flush()
                if tail:
                    emit(tail)
                if reasoning_span_id is not None:
                    ACTIVITY.finish(reasoning_span_id, summary="Reasoning complete")
                if response_span_id is not None:
                    ACTIVITY.finish(
                        response_span_id,
                        summary="Response ready",
                    )
        except Cancelled:
            if reasoning_span_id is not None:
                ACTIVITY.finish(
                    reasoning_span_id,
                    status="cancelled",
                    summary="Reasoning interrupted",
                )
            if response_span_id is not None:
                ACTIVITY.finish(
                    response_span_id,
                    status="cancelled",
                    summary="Response interrupted",
                )
            broadcast.cancelled("".join(heard).strip())
            raise
        except Exception as exc:
            # A provider can fail after yielding prose. Preserve that partial reply
            # in the reserved slot; an empty failure must not leave a ghost turn.
            if stop():
                # The barge-in and the failure landed together: commit through
                # the interruption path, or the note (and the record of tools
                # that ran) is lost and the next turn repeats itself.
                finish_interrupted_turn(
                    Cancelled(pending, "".join(heard).strip(), user_text, turn, tools_ran),
                    "".join(heard).strip(),
                )
            else:
                _finish_stream_turn(pending, "".join(heard).strip())
            if reasoning_span_id is not None:
                ACTIVITY.finish(
                    reasoning_span_id,
                    status="failed",
                    summary="Reasoning failed",
                    details={"error": str(exc)},
                )
            if response_span_id is not None:
                ACTIVITY.finish(
                    response_span_id,
                    status="failed",
                    summary="Response failed",
                    details={"error": str(exc)},
                )
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
            # Deferred (voice) turns journal when playback drains — see
            # commit_streamed_turn — so a late barge-in cannot leave unaired
            # words in the game record.
            _journal_table_chat(user_text, spoken)
        broadcast.done(spoken)
        return StreamingReply(
            spoken, history_message, user_text, defer_diary, turn, tools_ran=tools_ran
        )
    finally:
        end_user_turn()
        _face_turn_lock.release()


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
    # A result landing mid-reply waits the turn out rather than bouncing off
    # it: the work is done and there is no user to re-ask, so a busy answer
    # here would discard it.
    return chat(prompt, _wait_for_turn=True)
