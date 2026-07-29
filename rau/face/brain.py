"""Face talking brain — multi-turn, soul-backed, skills + escalation tools."""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

from rau.agent import compaction
from rau.agent import orchestrator
from rau.agent import tools as agent_tools
from rau.agent.danger import classify_tool
from rau.events import BUS
from rau.activity import ACTIVITY
from rau.face import choreography, panels, props, web
from rau.face.phrases import phrase, tool_label, trace_summary, voice_checkin
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
from rau.skills.runtime import PreparedTurn, prepare_turn, use_skill_tool
from rau import state

# Chess is an optional extra: the rules come from `python-chess`, which a default
# install does not have. Kittens is hand-written and always there, so it is
# imported plainly above — this one cannot be, because a missing wheel would take
# the whole face down with it and cost him every conversation, not just the game.
# Absent simply means he has no board, which `binary.py` already treats as an
# ordinary state of the world rather than a fault.
chess_session: Any
chess_tools: Any
try:
    from rau.games.chess import session as chess_session
    from rau.games.chess import tools as chess_tools
except ImportError:  # pragma: no cover — exercised by the no-extra install
    chess_session = None
    chess_tools = None

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

if chess_tools is not None:
    # Set the board up, clear it, and the two things that are decisions rather
    # than moves. The moves themselves are Stockfish's and arrive through the
    # pump, so `chess_move` here can only resign or settle a draw. Offered only
    # when there is something to play on: a tool he cannot honour is worse than
    # no tool, because he will promise a game and then fail to produce one.
    FACE_TOOLS.extend(
        [
            chess_tools.START_GAME_TOOL,
            chess_tools.CHESS_MOVE_TOOL,
            chess_tools.END_GAME_TOOL,
        ]
    )

#: The face model is chosen for latency, so its window is held far below what
#: the model would accept: a 100k-token prompt makes the face slow and
#: expensive long before it makes it forgetful.
FACE_CONTEXT_BUDGET = 12000
#: Tool output is clamped harder here than for a worker. A long foreground run
#: can now make twenty calls, so a single result must not consume the context
#: the remaining calls need.
FACE_TOOL_RESULT_LIMIT = 3000
#: Foreground work stays conversational and bounded. This is an execution
#: budget, not a model-round budget: providers may request several calls in one
#: response, and only calls actually run count.
MAX_FACE_TOOL_CALLS = 20
#: One final tool-free provider pass turns accumulated evidence into an answer.
MAX_FACE_MODEL_ROUNDS = MAX_FACE_TOOL_CALLS + 1
#: During a long spoken run, provide an evidence-based update at this cadence
#: if the model itself has not said anything useful between tool rounds.
VOICE_CHECKIN_EVERY_CALLS = 4
#: These are internal/embodied actions, not work the user needs narrated.
#: Their activity remains visible in the inspector, but no generated progress
#: sentence is allowed onto the voice token stream.
VOICE_SILENT_TOOL_NAMES = frozenset({"body_choreography"})
#: Voice turns keep a leaner diary excerpt so prefill stays short.
VOICE_MEMORY_CHARS = 1000
CHAT_MEMORY_CHARS = 2500
#: Hyper is deliberately a different product surface, not merely a faster
#: socket. Its tiny output and recent-turn window keep prefill/decode short and
#: make the exchange feel like conversational tiki-taka.
HYPER_MAX_TOKENS = 96
HYPER_HISTORY_MESSAGES = 4
HYPER_HISTORY_CHARS = 1600
#: An upstream model can finish after emitting reasoning but before emitting
#: user-visible prose. Give it fresh, tool-free attempts before the face falls
#: back locally. Retrying here keeps one bad completion from turning into a
#: repeated stock phrase in chat or voice.
EMPTY_REPLY_RETRIES = 2
HYPER_CONVERSATION_PROMPT = """## Hyper conversation
This is delicate, rapid tiki-taka conversation. Answer immediately and stay
with the human cadence of the exchange.
- Usually answer in one short, natural sentence; use two only when warmth or clarity needs it.
- Be attentive, gentle, and specific. Prefer a small question or observation that keeps the exchange moving.
- Do not plan, analyze aloud, recap, lecture, browse, use tools, or begin work.
- Use only the few recent lines supplied below. Do not reach for older memory or invent missing context.
- If the request needs research, tools, or careful multi-step reasoning, say briefly that Normal mode is the place for it.
Never mention tokens, prompts, latency, or this policy."""

_EMPTY_REPLY_PROMPT = """

## User-visible answer required
The previous attempt ended without any user-visible answer. Respond to the
latest user message now with non-empty natural language. Be specific to what
they said. Do not output a generic acknowledgement, do not use tools, and do
not discuss this retry instruction."""
_EMPTY_REPLY_EN = (
    "My answer dropped out before it reached you. Could you try that once more?",
    "That response came back blank. Say the last part again and I’ll take another pass.",
    "I lost the reply on my side. Could you repeat what you just said?",
)
_EMPTY_REPLY_KO = (
    "답변이 전달되기 전에 사라졌어요. 방금 말을 한 번만 다시 해 줄래요?",
    "응답이 비어 버렸어요. 마지막 부분을 다시 말해 주면 바로 이어갈게요.",
    "제 쪽에서 답변을 놓쳤어요. 방금 한 말을 한 번만 다시 들려주세요.",
)
_empty_reply_lock = threading.Lock()
_empty_reply_index = 0

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
        # Same rule for the board: he may set it up or put it away on round 0.
        # Playing it is the pump's job, and resigning is rare enough to wait
        # for a turn where he is not also deciding whether to speak.
        "start_chess",
        "end_chess",
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
    "You may use up to 20 foreground tool calls when the request genuinely "
    "needs them. Before any tool call sequence, briefly say what you are checking. "
    "During a long run, check in after roughly every four calls with one "
    "specific fact about what is complete and what you are checking next. "
    "Keep working after the check-in. Never use empty waiting filler."
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
# Assistant placeholders reserved by in-flight turns. Keeping the slot in
# `_history` preserves ordering when a provider/tool is slow and a newer turn
# preempts it, while snapshots hide the empty internal marker from providers.
_pending_stream_messages: set[int] = set()
# Held for the duration of a fold, so a fast exchange cannot start a second
# summarizer on top of the one already thinking.
_compacting = threading.Lock()
# Foreground conversation is newest-turn-wins. A generation that is already
# inside third-party I/O cannot always be force-killed safely, so preemption is
# cooperative: the old turn is invalidated immediately, its next callback/tool
# boundary stops it, and its stale result is never emitted into the new turn.
# Deep-work workers are intentionally outside this controller.
class _ForegroundTurn:
    def __init__(self, cascade_cancel: Optional[threading.Event] = None) -> None:
        self.cancel = threading.Event()
        self.cascade_cancel = cascade_cancel

    def preempt(self) -> None:
        self.cancel.set()
        # Voice owns TTS/playback cancellation through its turn event. Cascading
        # here makes a typed follow-up stop stale audio too, not just its LLM.
        if self.cascade_cancel is not None:
            self.cascade_cancel.set()


_foreground_condition = threading.Condition()
_active_foreground_turn: Optional[_ForegroundTurn] = None
#: Guards the diary_deferred hand-off on a StreamingReply: a barge-in and a
#: normal playback end can race to commit the same reply, and exactly one of
#: them may write the diary.
_deferred_diary_lock = threading.Lock()

#: Floor on the gap between `chat_delta` broadcasts. The event bus evicts the
#: oldest item from a slow subscriber's queue, so a per-token firehose would
#: lose text on exactly the client that most needs it. Every delta therefore
#: carries the whole reply so far, and they are throttled to a rate a browser
#: can actually paint.
DELTA_INTERVAL_SEC = 0.06


def _begin_foreground_turn(
    *,
    user_priority: bool,
    cascade_cancel: Optional[threading.Event] = None,
) -> _ForegroundTurn:
    """
    Claim foreground response priority.

    User turns immediately supersede whatever was answering before them.
    System-originated speech (for example a completed Deep Work result) waits
    for an idle gap, but never stops or cancels the background worker itself.
    """
    global _active_foreground_turn
    claim = _ForegroundTurn(cascade_cancel)
    with _foreground_condition:
        if user_priority:
            previous = _active_foreground_turn
            if previous is not None:
                previous.preempt()
            _active_foreground_turn = claim
            return claim
        while _active_foreground_turn is not None:
            _foreground_condition.wait()
        _active_foreground_turn = claim
        return claim


def _end_foreground_turn(claim: _ForegroundTurn) -> None:
    global _active_foreground_turn
    with _foreground_condition:
        if _active_foreground_turn is claim:
            _active_foreground_turn = None
            _foreground_condition.notify_all()


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


def _hyper_history(messages: List[Message]) -> List[Message]:
    """Return a tiny, prose-only tail for latency-first conversation."""
    remaining = HYPER_HISTORY_CHARS
    selected: List[Message] = []
    for message in reversed(messages):
        if message.role not in ("user", "assistant"):
            continue
        content = str(message.content or "").strip()
        if not content:
            continue
        if len(content) > remaining:
            # The newest end of a spoken turn normally carries the live
            # question/qualification. Mark the missing prefix explicitly.
            content = "…" + content[-max(0, remaining - 1) :]
        selected.append(Message(role=message.role, content=content))
        remaining -= len(content)
        if remaining <= 0 or len(selected) >= HYPER_HISTORY_MESSAGES:
            break
    selected.reverse()
    return selected


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
                a is b for a, b in zip(prefix, snapshot, strict=True)
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


def _system_prompt(
    extra: str = "", *, voice: bool = False, hyper: bool = False
) -> str:
    from rau.language import response_language_instruction
    from rau.heartbeat.presence import (
        SPEECH_HABITS_PROMPT,
        between_sessions_block,
        mood_context_block,
        time_context_block,
    )

    soul = _cached_soul()
    if hyper:
        # No diary read, room scan, panel inventory, tool instructions, active
        # goal, or between-session reconstruction on the latency path. The
        # small soul keeps Rau recognizable; the live history supplies the
        # immediate conversational thread.
        return "\n\n".join(
            [
                soul,
                SPEECH_HABITS_PROMPT,
                HYPER_CONVERSATION_PROMPT,
                response_language_instruction(),
            ]
        )

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
        "\n" + response_language_instruction(),
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
    # Only one game is ever on the table, so at most one of these is non-empty.
    if chess_session is not None:
        board = chess_session.prompt_fragment()
        if board:
            parts.append("\n" + board)
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
    if chess_tools is not None and name in chess_tools.TOOL_NAMES:
        # Likewise a board. The one thing here that is irreversible — resigning
        # — is irreversible inside a game he is playing for fun, which is not
        # the kind of irreversible the confirmation gate exists for.
        return chess_tools.run_tool(name, args)
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


def _tool_activity_label(name: str) -> str:
    return tool_label(name)


class _TurnTrace:
    """
    Public-safe account of observable work.

    This deliberately does not reconstruct chain-of-thought. It summarizes
    only provider-visible reasoning availability plus tools that actually ran
    and their success/failure status, so every provider gets useful activity
    summaries even when it returns no readable reasoning trace.
    """

    def __init__(self) -> None:
        self.provider_reasoning = False
        self.tools: List[Tuple[str, bool]] = []
        self.spoken_checkins = 0
        self.budget_reached = False

    def record_tool(self, name: str, ok: bool) -> None:
        self.tools.append((name, ok))

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    def details(self) -> Dict[str, Any]:
        counts = Counter(name for name, _ok in self.tools)
        return {
            "tool_calls": self.tool_count,
            "succeeded": sum(1 for _name, ok in self.tools if ok),
            "failed": sum(1 for _name, ok in self.tools if not ok),
            "tools": [
                {"name": name, "count": count}
                for name, count in counts.most_common()
            ],
            "provider_reasoning_available": self.provider_reasoning,
            "spoken_checkins": self.spoken_checkins,
            "tool_budget_reached": self.budget_reached,
        }

    def summary(self, *, final: bool = False, interrupted: bool = False) -> str:
        counts = Counter(name for name, _ok in self.tools)
        actions = ", ".join(
            f"{_tool_activity_label(name).lower()} ×{count}"
            if count > 1
            else _tool_activity_label(name).lower()
            for name, count in counts.most_common(4)
        )
        return trace_summary(
            tool_count=self.tool_count,
            actions=actions,
            failures=sum(1 for _name, ok in self.tools if not ok),
            final=final,
            interrupted=interrupted,
            provider_reasoning=self.provider_reasoning,
        )


def _voice_tool_checkin(completed: int, next_tool: str) -> str:
    return voice_checkin(completed, _tool_activity_label(next_tool))


def _history_with_trace(spoken: str, trace: _TurnTrace) -> str:
    """Carry completed work into follow-up turns without speaking the metadata."""
    if trace.tool_count <= 0:
        return spoken
    return (
        spoken
        + "\n\n(Internal continuity note, not spoken: "
        + trace.summary(final=True)
        + ")"
    )


def _force_tool_free_close(messages: List[Message], tool_count: int) -> None:
    """Tell the final provider pass to turn evidence into an actual answer."""
    if not messages or messages[0].role != "system":
        return
    suffix = (
        "\n\n## Finish this turn now\n"
        f"You have completed {tool_count} foreground tool calls. Tools are now "
        "unavailable. Give the user the best complete answer supported by the "
        "results above. State any unresolved limitation plainly. Do not mention "
        "the internal call budget or ask to keep waiting."
    )
    messages[0] = Message(role="system", content=messages[0].content + suffix)


def _empty_retry_messages(messages: List[Message], attempt: int) -> List[Message]:
    """Return a fresh prompt that insists on prose after an empty completion."""
    retried = list(messages)
    if retried and retried[0].role == "system":
        retried[0] = Message(
            role="system",
            content=(
                retried[0].content
                + _EMPTY_REPLY_PROMPT
                + f"\nThis is recovery attempt {attempt + 1}."
            ),
        )
    return retried


def _local_empty_reply(user_text: str) -> str:
    """Last-resort text that never repeats on adjacent empty turns."""
    global _empty_reply_index
    choices = (
        _EMPTY_REPLY_KO
        if re.search(r"[가-힣]", user_text or "")
        else _EMPTY_REPLY_EN
    )
    with _empty_reply_lock:
        reply = choices[_empty_reply_index % len(choices)]
        _empty_reply_index += 1
    return reply


def _retry_empty_blocking_reply(
    provider: Any,
    slot: Dict[str, Any],
    messages: List[Message],
    *,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Any:
    """Retry a reasoning-only/empty blocking completion with thinking minimized."""
    last = None
    for attempt in range(EMPTY_REPLY_RETRIES):
        if should_stop is not None and should_stop():
            return last
        last = provider.chat(
            _empty_retry_messages(messages, attempt),
            model=slot.get("model") or "deepseek-v4-flash",
            max_tokens=min(_face_max_tokens(slot), 512),
            temperature=min(
                1.2,
                max(0.2, float(slot.get("temperature") or 0.9) + 0.1 * attempt),
            ),
            tools=None,
            effort="minimal",
        )
        if str(getattr(last, "content", "") or "").strip():
            return last
    return last


def _record_tool_round(
    messages: List[Message],
    result: Any,
    system_extra: str,
    on_tool: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None,
    *,
    voice: bool = False,
    skill_prompts: Optional[List[str]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    max_calls: Optional[int] = None,
    assistant_content: Optional[str] = None,
) -> bool:
    """
    Run one round of tool calls, appending the assistant/tool turns it produces.

    The assistant turn carries every call of the round at once: a provider only
    accepts a result whose call sits in the turn directly above it, so the
    results follow as their own `tool` turns rather than as narrated prose.
    """
    messages.append(
        Message(
            role="assistant",
            content=(
                result.content
                if assistant_content is None
                else assistant_content
            ),
            tool_calls=list(result.tool_calls),
            reasoning=str(getattr(result, "reasoning", "") or ""),
            reasoning_details=getattr(result, "reasoning_details", None),
        )
    )
    executed = 0
    for tc in result.tool_calls:
        # Do not start another foreground action after a newer user turn has
        # arrived. A tool already in flight is allowed to settle below, because
        # arbitrary side-effecting calls are not safely killable.
        if should_stop is not None and should_stop():
            return False
        if max_calls is not None and executed >= max(0, max_calls):
            # Pair every provider-requested call even when it exceeds the
            # foreground budget. The model sees a truthful "not run" result
            # and can close cleanly without an orphaned tool-call protocol.
            messages.append(
                Message(
                    role="tool",
                    content=tool_result_text(
                        {
                            "ok": False,
                            "error": "foreground tool-call budget reached",
                            "summary": "not executed",
                        },
                        FACE_TOOL_RESULT_LIMIT,
                    ),
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )
            continue
        turn_id = choreography.current_turn_id() or None
        label = _tool_activity_label(tc.name)
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
                summary=phrase("failed_suffix", label=label),
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
                str(tr.get("summary") or phrase("finished"))
                if ok
                else str(tr.get("error") or phrase("tool_failed"))
            ),
            details={
                "tool": tc.name,
                "ok": ok,
                "result": tr,
            },
        )
        if on_tool:
            on_tool(tc.name, tc.arguments, tr)
        executed += 1
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
        # Quarantine this completed result from the superseding turn and skip
        # every remaining call in the stale round.
        if should_stop is not None and should_stop():
            return False
    return True


def _call_face(provider, slot, messages, *, tools):
    return provider.chat(
        messages,
        model=slot.get("model") or "deepseek-v4-flash",
        max_tokens=_face_max_tokens(slot),
        temperature=float(slot.get("temperature") or 0.9),
        tools=tools,
        effort=str(slot.get("effort") or "medium"),
    )


def _journal_table_chat(user_text: str, reply: str) -> None:
    """While a game is on, both halves need to see the banter."""
    if kittens.active():
        from rau.games.kittens import journal as kittens_journal

        kittens_journal.record("user", "user_chat", user_text)
        kittens_journal.record("rau", "rau_chat", reply)
        # He has just answered them properly. Hold the proactive table talk back
        # for a beat so the next thing they hear is not him talking over himself.
        from rau.games.kittens import banter as kittens_banter

        kittens_banter.note_user_chat()

    if chess_session is not None and chess_session.active():
        from rau.games.chess import journal as chess_journal

        chess_journal.record("user", "user_chat", user_text)
        chess_journal.record("rau", "rau_chat", reply)
        from rau.games.chess import banter as chess_banter

        chess_banter.note_user_chat()


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

    `_wait_for_turn` marks system-originated speech (see weave_result): it waits
    for an idle gap while user turns always supersede older foreground work.
    """
    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    turn = turn_id or choreography.new_turn_id()
    broadcast = _TurnBroadcast(turn, user_text)
    # Snapshot absence before history is used (idempotent if note_user_reply ran).
    begin_user_turn()
    claim = _begin_foreground_turn(user_priority=not _wait_for_turn)

    def stop() -> bool:
        return claim.cancel.is_set()

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
        pending, history = _reserve_stream_turn(turn_text)
        messages = [
            Message(role="system", content=_system_prompt(prep.system_extra))
        ] + history

        spoken = ""
        tools_ran: List[Tuple[str, str]] = []
        trace = _TurnTrace()

        def note_tool(name: str, _args: Dict[str, Any], result: Dict[str, Any]) -> None:
            ok = bool(result.get("ok", True))
            summary = str(
                (result.get("summary") or "ok")
                if ok
                else (result.get("error") or "failed")
            )
            tools_ran.append((name, summary[:80]))
            trace.record_tool(name, ok)

        try:
            with choreography.turn_scope(turn):
                skill_prompts: List[str] = []
                for round_idx in range(MAX_FACE_MODEL_ROUNDS):
                    if stop():
                        raise Cancelled(pending, "", user_text, turn, tools_ran)
                    closing = (
                        len(tools_ran) >= MAX_FACE_TOOL_CALLS
                        or round_idx == MAX_FACE_MODEL_ROUNDS - 1
                    )
                    if closing:
                        _force_tool_free_close(messages, len(tools_ran))
                    result = _call_face(
                        provider,
                        slot,
                        messages,
                        tools=None if closing else FACE_TOOLS,
                    )
                    if result.reasoning or result.reasoning_details:
                        trace.provider_reasoning = True
                    if stop():
                        raise Cancelled(pending, "", user_text, turn, tools_ran)
                    if result.tool_calls and not closing:
                        remaining = MAX_FACE_TOOL_CALLS - len(tools_ran)
                        completed = _record_tool_round(
                            messages,
                            result,
                            prep.system_extra,
                            note_tool,
                            skill_prompts=skill_prompts,
                            should_stop=stop,
                            max_calls=remaining,
                        )
                        if not completed or stop():
                            raise Cancelled(
                                pending, "", user_text, turn, tools_ran
                            )
                        continue
                    spoken = (result.content or "").strip()
                    break
        except Cancelled as cancelled:
            finish_interrupted_turn(cancelled, "")
            broadcast.cancelled("")
            raise
        except Exception as exc:
            _finish_stream_turn(pending, "")
            broadcast.error(str(exc))
            raise

        if not spoken and not stop():
            try:
                retry = _retry_empty_blocking_reply(
                    provider,
                    slot,
                    messages,
                    should_stop=stop,
                )
            except Exception as exc:
                _finish_stream_turn(pending, "")
                broadcast.error(str(exc))
                raise
            if retry is not None:
                if retry.reasoning or retry.reasoning_details:
                    trace.provider_reasoning = True
                spoken = (retry.content or "").strip()
        if stop():
            cancelled = Cancelled(pending, "", user_text, turn, tools_ran)
            finish_interrupted_turn(cancelled, "")
            broadcast.cancelled("")
            raise cancelled
        if not spoken:
            spoken = _local_empty_reply(user_text)
        from rau.heartbeat.presence import apply_reply_mood

        spoken, _ = apply_reply_mood(spoken)
        _finish_stream_turn(pending, _history_with_trace(spoken, trace))
        _maybe_compact_history()
        append_diary("user", user_text)
        append_diary("rau", spoken)
        _journal_table_chat(user_text, spoken)
        broadcast.done(spoken)
        return spoken
    finally:
        end_user_turn()
        _end_foreground_turn(claim)


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
    latency_profile: str = "normal",
) -> str:
    """
    Streaming face turn that keeps full tool access.

    Same twenty-call bounded loop as `chat()` — the only differences are that
    prose is handed to `on_token` as it arrives and that `cancel` is honoured
    between tokens and rounds. Tool plumbing never reaches `on_token`; only
    assistant prose and brief evidence-based voice check-ins do.

    `turn_id` scopes any `body_choreography` the model calls, and is echoed on
    every `chat_*` event so a client can tie a plan to the text it anchors to.

    Returns everything generated. The caller is responsible for committing only
    what was actually spoken if it cancelled (see `finish_interrupted_turn`).
    """
    from rau.heartbeat.presence import begin_user_turn, end_user_turn

    turn = turn_id or choreography.new_turn_id()
    broadcast = _TurnBroadcast(turn, user_text)
    begin_user_turn()
    claim = _begin_foreground_turn(
        user_priority=True,
        cascade_cancel=cancel,
    )

    def stop() -> bool:
        return claim.cancel.is_set() or (cancel is not None and cancel.is_set())

    def emit(token: str) -> None:
        broadcast.token(token)
        on_token(token)

    try:
        hyper = latency_profile == "hyper"
        if hyper and not user_text.lstrip().startswith("/"):
            # Avoid loading always-on skill prompts for a surface that cannot
            # call tools and is intentionally limited to conversation.
            prep = PreparedTurn(user_text=str(user_text or "").strip())
        else:
            prep = prepare_turn(user_text)
            if hyper and prep.activate and not prep.immediate_reply:
                prep = PreparedTurn(
                    user_text=prep.user_text,
                    immediate_reply=(
                        "Hyper is just for quick conversation. Switch to Normal "
                        "and I can use that skill with you."
                    ),
                )
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
        if hyper:
            history = _hyper_history(history)
        messages = [
            Message(
                role="system",
                content=_system_prompt(
                    prep.system_extra,
                    voice=voice,
                    hyper=hyper,
                ),
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
        trace = _TurnTrace()
        approach_span_id: Optional[str] = None
        last_voice_checkin_at = 0

        def ensure_approach_span() -> str:
            nonlocal approach_span_id
            if approach_span_id is None:
                approach_span_id = ACTIVITY.start(
                    "planning",
                    phrase("approach"),
                    source="face",
                    summary=trace.summary(),
                    details=trace.details(),
                    turn_id=turn,
                )["id"]
            return approach_span_id

        def finish_approach(
            *,
            status: str = "completed",
            interrupted: bool = False,
        ) -> None:
            span_id = ensure_approach_span()
            ACTIVITY.finish(
                span_id,
                status=status,
                summary=trace.summary(
                    final=status == "completed",
                    interrupted=interrupted,
                ),
                details=trace.details(),
            )

        def note_tool(name: str, args: Dict[str, Any], result: Dict[str, Any]) -> None:
            nonlocal last_voice_checkin_at
            ok = bool(result.get("ok", True))
            if ok:
                summary = str(result.get("summary") or "ok")
            else:
                summary = str(result.get("error") or "failed")
            tools_ran.append((name, summary[:80]))
            trace.record_tool(name, ok)
            if approach_span_id is not None:
                ACTIVITY.delta(
                    approach_span_id,
                    summary=trace.summary(),
                    details=trace.details(),
                )
            # Providers may batch many calls into one assistant turn. Keep a
            # spoken run alive even inside that batch, where there is no next
            # model round available to supply its own progress sentence.
            if (
                voice
                and name not in VOICE_SILENT_TOOL_NAMES
                and trace.tool_count - last_voice_checkin_at
                >= VOICE_CHECKIN_EVERY_CALLS
                and not stop()
            ):
                completed_action = _tool_activity_label(name).lower()
                checkin = (
                    f"I’ve completed {trace.tool_count} checks, including "
                    f"{completed_action}. I’m continuing. "
                )
                heard.append(checkin)
                emit_prose(checkin)
                trace.spoken_checkins += 1
                last_voice_checkin_at = trace.tool_count
            # A tool that was already running may finish after preemption. Keep
            # the fact that it ran for history, but never surface its stale
            # result into the newest foreground turn.
            if on_tool and not stop():
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
        answer_visible = False
        try:
            with choreography.turn_scope(turn):
                skill_prompts: List[str] = []
                model_rounds = 1 if hyper else MAX_FACE_MODEL_ROUNDS
                for round_idx in range(model_rounds):
                    if stop():
                        raise Cancelled(
                            pending, "".join(heard).strip(), user_text, turn, tools_ran
                        )

                    chunks: List[str] = []
                    result = None
                    # Once twenty calls have actually run, one final pass gets
                    # no tools and must turn the gathered evidence into prose.
                    closing = (
                        hyper
                        or trace.tool_count >= MAX_FACE_TOOL_CALLS
                        or round_idx == model_rounds - 1
                    )
                    if closing and not hyper:
                        _force_tool_free_close(messages, trace.tool_count)
                    tools = None if closing else _tools_for_turn(
                        voice=voice, round_idx=round_idx, user_text=user_text
                    )
                    for event in provider.stream_turn(
                        messages,
                        model=slot.get("model") or "deepseek-v4-flash",
                        max_tokens=(
                            min(HYPER_MAX_TOKENS, _face_max_tokens(slot))
                            if hyper
                            else _face_max_tokens(slot)
                        ),
                        temperature=float(slot.get("temperature") or 0.9),
                        tools=tools,
                        effort=(
                            "minimal"
                            if hyper
                            else str(slot.get("effort") or "medium")
                        ),
                        latency_profile=latency_profile,
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
                                    phrase("responding"),
                                    source="face",
                                    summary=phrase("composing"),
                                    turn_id=turn,
                                )["id"]
                        elif isinstance(event, ReasoningDelta):
                            trace.provider_reasoning = True
                            if reasoning_span_id is None:
                                reasoning_span_id = ACTIVITY.start(
                                    "reasoning",
                                    phrase("reasoning"),
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
                    if result.reasoning or result.reasoning_details:
                        trace.provider_reasoning = True

                    # A provider using the default blocking stream may only put
                    # prose on StreamDone. It is just as audible as a delta.
                    if not chunks and result.content:
                        chunks.append(result.content)
                        heard.append(result.content)
                        emit_prose(result.content)

                    if result.tool_calls and not closing:
                        assistant_content: Optional[str] = (
                            "".join(chunks) if chunks and not result.content else None
                        )
                        checkin_call = next(
                            (
                                call
                                for call in result.tool_calls
                                if call.name not in VOICE_SILENT_TOOL_NAMES
                            ),
                            None,
                        )
                        round_spoke = bool("".join(chunks).strip())
                        if round_spoke:
                            last_voice_checkin_at = trace.tool_count
                        elif voice and checkin_call is not None and (
                            trace.tool_count == 0
                            or trace.tool_count - last_voice_checkin_at
                            >= VOICE_CHECKIN_EVERY_CALLS
                        ):
                            checkin = _voice_tool_checkin(
                                trace.tool_count,
                                checkin_call.name,
                            )
                            assistant_content = checkin
                            heard.append(checkin + " ")
                            emit_prose(checkin + " ")
                            trace.spoken_checkins += 1
                            last_voice_checkin_at = trace.tool_count

                        remaining = MAX_FACE_TOOL_CALLS - trace.tool_count
                        requested = len(result.tool_calls)
                        completed = _record_tool_round(
                            messages,
                            result,
                            prep.system_extra,
                            note_tool,
                            voice=voice,
                            skill_prompts=skill_prompts,
                            should_stop=stop,
                            max_calls=remaining,
                            assistant_content=assistant_content,
                        )
                        if requested > remaining:
                            trace.budget_reached = True
                        if not completed or stop():
                            raise Cancelled(
                                pending,
                                "".join(heard).strip(),
                                user_text,
                                turn,
                                tools_ran,
                            )
                        # Start the aggregate only after the first tool event.
                        # body_choreography promises its body_plan is the first
                        # event after chat_started; an eager summary would
                        # silently break phrase/body timing in the browser.
                        ensure_approach_span()
                        continue

                    if not chunks and result.content:
                        # Provider returned prose only in the terminal event.
                        heard.append(result.content)
                        emit_prose(result.content)
                    answer_visible = bool(
                        "".join(chunks).strip() or (result.content or "").strip()
                    )
                    break

                # A reasoning-capable provider can end cleanly with thoughts
                # but no visible answer. Retry with tools and thinking disabled
                # before allowing any local recovery text onto the wire.
                if not answer_visible:
                    for attempt in range(EMPTY_REPLY_RETRIES):
                        if stop():
                            raise Cancelled(
                                pending,
                                "",
                                user_text,
                                turn,
                                tools_ran,
                            )
                        retry_chunks: List[str] = []
                        retry_result = None
                        for event in provider.stream_turn(
                            _empty_retry_messages(messages, attempt),
                            model=slot.get("model") or "deepseek-v4-flash",
                            max_tokens=(
                                HYPER_MAX_TOKENS
                                if hyper
                                else min(_face_max_tokens(slot), 512)
                            ),
                            temperature=min(
                                1.2,
                                max(
                                    0.2,
                                    float(slot.get("temperature") or 0.9)
                                    + 0.1 * attempt,
                                ),
                            ),
                            tools=None,
                            effort="minimal",
                            latency_profile=latency_profile,
                        ):
                            if stop():
                                raise Cancelled(
                                    pending,
                                    "".join(heard).strip(),
                                    user_text,
                                    turn,
                                    tools_ran,
                                )
                            if isinstance(event, TextDelta):
                                retry_chunks.append(event.text)
                                heard.append(event.text)
                                emit_prose(event.text)
                                if response_span_id is None:
                                    response_span_id = ACTIVITY.start(
                                        "execution",
                                        phrase("responding"),
                                        source="face",
                                        summary=phrase("composing"),
                                        turn_id=turn,
                                    )["id"]
                            elif isinstance(event, ReasoningDelta):
                                trace.provider_reasoning = True
                                if reasoning_span_id is None:
                                    reasoning_span_id = ACTIVITY.start(
                                        "reasoning",
                                        phrase("reasoning"),
                                        source=getattr(
                                            event,
                                            "provider_format",
                                            "provider",
                                        ),
                                        summary="",
                                        turn_id=turn,
                                    )["id"]
                                ACTIVITY.delta(reasoning_span_id, text=event.text)
                            elif isinstance(event, StreamDone):
                                retry_result = event.result
                        if retry_result is not None and (
                            retry_result.reasoning
                            or retry_result.reasoning_details
                        ):
                            trace.provider_reasoning = True
                        if (
                            not retry_chunks
                            and retry_result is not None
                            and retry_result.content
                        ):
                            heard.append(retry_result.content)
                            emit_prose(retry_result.content)
                        retry_text = "".join(retry_chunks).strip()
                        if not retry_text and retry_result is not None:
                            retry_text = (retry_result.content or "").strip()
                        if retry_text:
                            answer_visible = True
                            break
                if not answer_visible:
                    recovery = _local_empty_reply(user_text)
                    heard.append(recovery)
                    emit_prose(recovery)
                tail = leading_tag.flush()
                if tail:
                    emit(tail)
                if reasoning_span_id is not None:
                    ACTIVITY.finish(reasoning_span_id, summary=phrase("reasoning_done"))
                if response_span_id is not None:
                    ACTIVITY.finish(
                        response_span_id,
                        summary=phrase("response_ready"),
                    )
                finish_approach()
        except Cancelled:
            if reasoning_span_id is not None:
                ACTIVITY.finish(
                    reasoning_span_id,
                    status="cancelled",
                    summary=phrase("reasoning_interrupted"),
                )
            if response_span_id is not None:
                ACTIVITY.finish(
                    response_span_id,
                    status="cancelled",
                    summary=phrase("response_interrupted"),
                )
            finish_approach(status="interrupted", interrupted=True)
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
                    summary=phrase("reasoning_failed"),
                    details={"error": str(exc)},
                )
            if response_span_id is not None:
                ACTIVITY.finish(
                    response_span_id,
                    status="failed",
                    summary=phrase("response_failed"),
                    details={"error": str(exc)},
                )
            finish_approach(status="failed")
            broadcast.error(str(exc))
            raise

        spoken = "".join(heard).strip()
        if not spoken:
            spoken = _local_empty_reply(user_text)
            emit(spoken)
        from rau.heartbeat.presence import apply_reply_mood

        spoken, _ = apply_reply_mood(spoken)
        history_message = _finish_stream_turn(
            pending,
            _history_with_trace(spoken, trace),
        )
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
        _end_foreground_turn(claim)


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
    # A result landing mid-reply waits for an idle gap. A newer user turn may
    # still supersede this narration, but never the Deep Work job that made it.
    return chat(prompt, _wait_for_turn=True)
