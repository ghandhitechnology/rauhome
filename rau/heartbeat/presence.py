"""Adaptive presence heartbeat — soft initiate with social backoff.

Also owns lived-time awareness: durable last-contact, sticky mood, human
absence phrasing, real heartbeat activity, and session-boundary cues.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from rau.events import BUS
from rau.memory.store import recent_context
from rau.paths import PRESENCE_FILE, ensure_dirs
from rau.providers.registry import load_settings
from rau import state

_thread: Optional[threading.Thread] = None
_stop = threading.Event()

#: Soft re-entry: notice the pause, don't restart the friendship.
REENTRY_SOFT_SEC = 15 * 60
#: Hard re-entry: clear live chat history; treat as coming back after a stretch.
REENTRY_HARD_SEC = 2 * 3600

#: Mood intensity half-life (~6h wall clock).
MOOD_HALF_LIFE_SEC = 6 * 3600
MOOD_IDLE_THRESHOLD = 0.15
HEARTBEAT_EVENTS_CAP = 20

MOOD_LABELS = frozenset(
    {
        "idle",
        "curious",
        "happy",
        "excited",
        "sad",
        "scared",
        "amazed",
        "love",
        "determined",
        "thinking",
        "sleep",
    }
)

SPEECH_HABITS_PROMPT = """## Speech habits
Sound like a person thinking, not a script.
Occasionally use a brief filler or self-correction when it fits: "음…", "그…", "아니 — 그러니까 —".
Keep it sparse: at most one disfluency per reply unless startled or emotional.
Never use SSML, asterisks, or stage directions — write exactly what you would say."""

_lock = threading.Lock()
#: Gap seconds snapshotted for the in-flight user turn (None = not begun).
_active_gap_sec: Optional[float] = None
#: "none" | "soft" | "hard" | "first"
_active_tier: str = "none"
#: Heartbeat events eligible to mention on this re-entry turn.
_active_heartbeat_events: List[Dict[str, Any]] = []
#: Monotonic stamp of the open turn, for abandonment recovery below.
_active_started_at: float = 0.0

#: How long a turn may stay open before the next contact treats it as dead.
#:
#: A turn is opened by `note_user_reply` — at the hub, in the voice session, in
#: the host pipeline — and closed by `brain`, which is a different module on a
#: different thread. Every path that opens one without reaching the brain (a
#: provider that will not load, a worker killed mid-flight, a caller nobody has
#: written yet) would otherwise pin the re-entry state forever: the user comes
#: back after a day and is greeted as though they never left, because the tier
#: is still cached from a turn that died last Tuesday.
#:
#: Rather than hunt every such path, the state expires. Generous enough to
#: cover a long reply read aloud in full, short enough that a wedged turn costs
#: one greeting rather than all of them.
TURN_MAX_SEC = 180.0


def format_absence(seconds: float) -> str:
    """Human phrase for how long the user has been away."""
    if seconds < 0:
        return "unknown"
    if seconds < 45:
        return "just now"
    if seconds < 90:
        return "about a minute"
    if seconds < 45 * 60:
        mins = max(1, int(round(seconds / 60)))
        return f"{mins} minute{'s' if mins != 1 else ''}"
    if seconds < 90 * 60:
        return "about an hour"
    if seconds < 24 * 3600:
        hours = max(1, int(round(seconds / 3600)))
        return f"about {hours} hour{'s' if hours != 1 else ''}"
    days = max(1, int(round(seconds / 86400)))
    if days == 1:
        return "about a day"
    return f"about {days} days"


def _tier_for_gap(gap_sec: Optional[float]) -> str:
    if gap_sec is None:
        return "first"
    if gap_sec < 0:
        return "first"
    if gap_sec >= REENTRY_HARD_SEC:
        return "hard"
    if gap_sec >= REENTRY_SOFT_SEC:
        return "soft"
    return "none"


def gap_since_last_user(now: Optional[float] = None) -> Optional[float]:
    """Seconds since last user contact, or None if never."""
    p = state.presence()
    last = float(p.get("last_user_ts") or 0)
    if last <= 0:
        return None
    return max(0.0, (now if now is not None else time.time()) - last)


def _default_mood() -> Dict[str, Any]:
    return {"label": "idle", "intensity": 0.0, "updated_at": 0.0}


def get_mood() -> Dict[str, Any]:
    p = state.presence()
    mood = p.get("mood")
    if not isinstance(mood, dict):
        return _default_mood()
    label = str(mood.get("label") or "idle").lower()
    if label not in MOOD_LABELS:
        label = "idle"
    try:
        intensity = float(mood.get("intensity") or 0.0)
    except (TypeError, ValueError):
        intensity = 0.0
    try:
        updated_at = float(mood.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0
    return {
        "label": label,
        "intensity": max(0.0, min(1.0, intensity)),
        "updated_at": updated_at,
    }


def _set_mood(label: str, intensity: float, updated_at: Optional[float] = None) -> None:
    lab = (label or "idle").lower()
    if lab not in MOOD_LABELS:
        lab = "idle"
    state.update_presence(
        mood={
            "label": lab,
            "intensity": max(0.0, min(1.0, float(intensity))),
            "updated_at": float(updated_at if updated_at is not None else time.time()),
        }
    )


def decay_mood(now: Optional[float] = None) -> Dict[str, Any]:
    """Decay sticky mood toward idle using wall-clock half-life."""
    mood = get_mood()
    t = now if now is not None else time.time()
    updated = float(mood.get("updated_at") or 0.0)
    intensity = float(mood.get("intensity") or 0.0)
    label = str(mood.get("label") or "idle")
    if updated <= 0 or intensity <= 0:
        if label != "idle" and intensity < MOOD_IDLE_THRESHOLD:
            _set_mood("idle", 0.0, updated or t)
            return get_mood()
        return mood
    elapsed = max(0.0, t - updated)
    if elapsed <= 0:
        return mood
    new_intensity = intensity * (0.5 ** (elapsed / MOOD_HALF_LIFE_SEC))
    if new_intensity < MOOD_IDLE_THRESHOLD:
        _set_mood("idle", 0.0, t)
    else:
        _set_mood(label, new_intensity, t)
    return get_mood()


def note_mood(label: str, intensity: float = 0.7) -> Dict[str, Any]:
    """Record a fresh mood from a real reply emotion (or gap nudge)."""
    lab = (label or "idle").lower()
    if lab not in MOOD_LABELS:
        lab = "idle"
    if lab == "idle":
        _set_mood("idle", 0.0)
    else:
        _set_mood(lab, intensity)
    try:
        save_presence()
    except OSError:
        pass
    return get_mood()


def apply_reply_mood(text: str) -> Tuple[str, str]:
    """Parse optional emotion tag; sticky mood updates only when a tag is present."""
    from rau.face import brain

    clean, tag = brain.extract_emotion(text)
    if tag:
        emo = tag.lower()
        if emo not in MOOD_LABELS:
            emo = "curious"
        note_mood(emo, 0.7 if emo != "idle" else 0.0)
    else:
        emo = get_mood()["label"] or "idle"
        if emo == "idle":
            emo = "curious"
    state.set_emotion(emo, clean)
    return clean, emo


def _gap_mood_nudge(tier: str) -> None:
    """Slight intensity shift on soft/hard return — no invented story."""
    mood = decay_mood()
    if tier == "soft":
        if mood["label"] == "idle" or mood["intensity"] < 0.25:
            note_mood("curious", 0.35)
        else:
            note_mood(mood["label"], min(1.0, mood["intensity"] + 0.05))
    elif tier == "hard":
        note_mood("curious", 0.3)


def get_heartbeat_events() -> List[Dict[str, Any]]:
    p = state.presence()
    raw = p.get("heartbeat_events")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        kind = str(item.get("kind") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not kind or not summary or ts <= 0:
            continue
        out.append({"kind": kind, "summary": summary[:500], "ts": ts})
    return out


def append_heartbeat_event(
    kind: str, summary: str, ts: Optional[float] = None
) -> None:
    """Record a real heartbeat action (nudge / task progress)."""
    k = (kind or "").strip()
    s = (summary or "").strip()
    if not k or not s:
        return
    events = get_heartbeat_events()
    # Dedupe identical consecutive summaries.
    if events and events[-1].get("kind") == k and events[-1].get("summary") == s[:500]:
        return
    events.append(
        {
            "kind": k,
            "summary": s[:500],
            "ts": float(ts if ts is not None else time.time()),
        }
    )
    if len(events) > HEARTBEAT_EVENTS_CAP:
        events = events[-HEARTBEAT_EVENTS_CAP:]
    state.update_presence(heartbeat_events=events)
    try:
        save_presence()
    except OSError:
        pass


def save_presence() -> None:
    ensure_dirs()
    p = state.presence()
    last_ts = float(p.get("last_user_ts") or 0)
    mood = get_mood()
    payload: Dict[str, Any] = {
        "last_user_ts": last_ts,
        "last_user_at": (
            datetime.fromtimestamp(last_ts).isoformat(timespec="seconds")
            if last_ts > 0
            else None
        ),
        "mood": mood,
        "heartbeat_events": get_heartbeat_events(),
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{PRESENCE_FILE.name}.", suffix=".tmp", dir=PRESENCE_FILE.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, PRESENCE_FILE)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load_presence() -> Dict[str, Any]:
    """Load durable presence into process state. Safe if file missing."""
    ensure_dirs()
    if not PRESENCE_FILE.exists():
        return {"loaded": False}
    try:
        data = json.loads(PRESENCE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"loaded": False, "error": "unreadable"}
    if not isinstance(data, dict):
        return {"loaded": False, "error": "unreadable"}
    try:
        last_ts = float(data.get("last_user_ts") or 0)
    except (TypeError, ValueError):
        last_ts = 0.0
    if last_ts <= 0:
        at = data.get("last_user_at")
        if isinstance(at, str) and at.strip():
            try:
                last_ts = datetime.fromisoformat(at.strip()).timestamp()
            except ValueError:
                last_ts = 0.0
    updates: Dict[str, Any] = {}
    if last_ts > 0:
        updates["last_user_ts"] = last_ts
    mood = data.get("mood")
    if isinstance(mood, dict):
        # Per-field guards, like get_mood: one corrupt value must not make the
        # whole presence file unloadable (and take the hub down with it).
        try:
            intensity = float(mood.get("intensity") or 0.0)
        except (TypeError, ValueError):
            intensity = 0.0
        try:
            updated_at = float(mood.get("updated_at") or 0.0)
        except (TypeError, ValueError):
            updated_at = 0.0
        updates["mood"] = {
            "label": str(mood.get("label") or "idle").lower(),
            "intensity": intensity,
            "updated_at": updated_at,
        }
    events = data.get("heartbeat_events")
    if isinstance(events, list):
        updates["heartbeat_events"] = events
    if updates:
        state.update_presence(**updates)
    decay_mood()
    return {"loaded": True, "last_user_ts": last_ts}


def begin_user_turn() -> Tuple[Optional[float], str]:
    """
    Snapshot absence for this turn (before last_user_ts is overwritten).

    Returns (gap_sec or None if never contacted, tier).
    Idempotent within a turn until end_user_turn().
    """
    global _active_gap_sec, _active_tier, _active_heartbeat_events
    global _active_started_at
    with _lock:
        if _active_gap_sec is not None:
            if time.monotonic() - _active_started_at <= TURN_MAX_SEC:
                return (
                    None if _active_gap_sec < 0 else _active_gap_sec,
                    _active_tier,
                )
            # The previous turn was opened and never closed. Treat it as dead
            # and snapshot fresh, or its tier outlives it and every future
            # re-entry is judged against a gap that stopped being true.
            BUS.emit(
                "presence_turn_abandoned",
                tier=_active_tier,
                age_sec=round(time.monotonic() - _active_started_at, 1),
            )
            _active_gap_sec = None
            _active_tier = "none"
            _active_heartbeat_events = []
        decay_mood()
        gap = gap_since_last_user()
        tier = _tier_for_gap(gap)
        _active_gap_sec = -1.0 if gap is None else float(gap)
        _active_tier = tier
        _active_started_at = time.monotonic()
        # Snapshot events from before this contact (last_user_ts still old).
        last_user = float(state.presence().get("last_user_ts") or 0)
        if tier in ("soft", "hard", "first"):
            _active_heartbeat_events = [
                e
                for e in get_heartbeat_events()
                if float(e.get("ts") or 0) > last_user
            ]
        else:
            _active_heartbeat_events = []
        state.update_presence(
            reentry_pending=tier in ("soft", "hard", "first"),
            reentry_tier=tier,
            gap_sec=_active_gap_sec,
        )
        if tier in ("soft", "hard"):
            _gap_mood_nudge(tier)
        if tier == "hard":
            # Live thread is a frozen mid-session — diary/soul keep continuity.
            from rau.face import brain

            brain.reset_history()
        return (None if gap is None else gap, tier)


def end_user_turn() -> None:
    """Clear one-shot re-entry flags; consume mentioned heartbeat events."""
    global _active_gap_sec, _active_tier, _active_heartbeat_events
    global _active_started_at
    with _lock:
        tier = _active_tier
        consumed = list(_active_heartbeat_events)
        _active_gap_sec = None
        _active_started_at = 0.0
        _active_tier = "none"
        _active_heartbeat_events = []
        state.update_presence(reentry_pending=False, reentry_tier="none", gap_sec=0.0)
        if tier in ("soft", "hard", "first") and consumed:
            consumed_ts = {float(e.get("ts") or 0) for e in consumed}
            remaining = [
                e
                for e in get_heartbeat_events()
                if float(e.get("ts") or 0) not in consumed_ts
            ]
            state.update_presence(heartbeat_events=remaining)
            try:
                save_presence()
            except OSError:
                pass


def active_gap() -> Tuple[Optional[float], str]:
    with _lock:
        if _active_gap_sec is None:
            return None, "none"
        gap = None if _active_gap_sec < 0 else _active_gap_sec
        return gap, _active_tier


def active_heartbeat_events() -> List[Dict[str, Any]]:
    with _lock:
        return list(_active_heartbeat_events)


def time_context_block() -> str:
    """Markdown block for the face system prompt: clock + absence."""
    now = datetime.now()
    clock = now.strftime("%A, %Y-%m-%d %H:%M")
    gap, tier = active_gap()
    # If begin_user_turn hasn't run yet, fall back to live gap (read-only).
    if _active_gap_sec is None:
        gap = gap_since_last_user()
        tier = _tier_for_gap(gap)

    lines = [
        "## Now",
        f"Local time: {clock}.",
    ]
    if gap is None:
        lines.append("You have not spoken with them yet in a remembered session.")
        lines.append(
            "This is a beginning — meet them freshly. Do not pretend a prior chat "
            "just happened."
        )
    else:
        lines.append(f"Time since you last heard from them: {format_absence(gap)}.")
        if tier == "none":
            lines.append("Same ongoing session — continue naturally.")
        elif tier == "soft":
            lines.append(
                "There has been a pause. You may notice it lightly if it fits; "
                "do not over-apologize or restart the friendship from zero."
            )
        else:  # hard
            lines.append(
                "They are returning after a real stretch away. Acknowledge the gap "
                "naturally once (warm, brief — not needy). Do not continue a mid-thread "
                "thought as if no time passed; live history was cleared for a clean re-entry. "
                "Diary/memory still hold what mattered."
            )
    return "\n".join(lines)


def mood_context_block() -> str:
    """Markdown block: sticky mood for this turn."""
    mood = get_mood()
    label = mood["label"]
    intensity = float(mood["intensity"])
    lines = ["## Mood"]
    if label == "idle" or intensity < MOOD_IDLE_THRESHOLD:
        lines.append("Baseline calm. No strong leftover feeling.")
    else:
        lines.append(
            f"You are carrying a light {label} feeling (intensity ~{intensity:.2f}). "
            "Let it color tone lightly — do not announce or narrate the mood meta."
        )
    return "\n".join(lines)


def between_sessions_block() -> str:
    """Real heartbeat actions during absence — never invent solitude."""
    gap, tier = active_gap()
    if _active_gap_sec is None:
        tier = _tier_for_gap(gap_since_last_user())
    if tier not in ("soft", "hard", "first"):
        return ""
    events = active_heartbeat_events()
    lines = ["## While they were away"]
    if not events:
        lines.append(
            "You have no recorded heartbeat actions from this stretch. "
            "Do not invent what you did alone. Acknowledge the gap only if it fits."
        )
        return "\n".join(lines)
    lines.append(
        "These are real things you did (heartbeat). You may briefly mention "
        "one of them once — do not invent anything else:"
    )
    for e in events[-8:]:
        when = datetime.fromtimestamp(float(e["ts"])).strftime("%H:%M")
        lines.append(f"- [{e['kind']} @ {when}] {e['summary']}")
    return "\n".join(lines)


def note_user_reply() -> None:
    """Mark user activity. Snapshots absence first, then persists contact time."""
    begin_user_turn()
    now = time.time()
    state.update_presence(misses=0, last_user_ts=now, muted_until=0.0)
    try:
        save_presence()
    except OSError:
        pass


def note_no_reply() -> None:
    settings = load_settings()
    threshold = int(settings.get("presence_backoff_after_misses") or 2)
    p = state.presence()
    misses = int(p.get("misses") or 0) + 1
    muted_until = 0.0
    if misses >= threshold:
        # back off for a while
        muted_until = time.time() + 30 * 60
        misses = 0
    state.update_presence(misses=misses, muted_until=muted_until)


def can_initiate() -> bool:
    p = state.presence()
    if time.time() < float(p.get("muted_until") or 0):
        return False
    snap = state.status_snapshot()
    if not snap.get("listening"):
        return False
    if snap.get("face_busy"):
        return False
    ht = snap.get("hard_task") or {}
    if ht.get("state") in ("running", "awaiting_confirm"):
        return False
    # don't spam
    if time.time() - float(p.get("last_initiate_ts") or 0) < 20 * 60:
        return False
    last_user = float(p.get("last_user_ts") or 0)
    # Never initiate before the first human turn (avoids boot chatter)
    if last_user <= 0:
        return False
    # need some silence after last user
    if time.time() - last_user < 12 * 60:
        return False
    return True


def maybe_nudge() -> None:
    from rau.permissions import heartbeat_nudge_allowed

    if not heartbeat_nudge_allowed():
        return
    if not can_initiate():
        return
    ctx = recent_context(2000)
    if "task" not in ctx.lower() and "friend" not in ctx.lower() and len(ctx) < 40:
        # still allow rare ambient hello
        if random.random() > 0.15:
            return
    gap = gap_since_last_user() or 0.0
    ago = format_absence(gap)
    line = (
        f"Hey — I'm still here. It's been {ago} since we last talked. "
        "Want to pick something up, or should I keep quiet a bit?"
    )
    state.update_presence(last_initiate_ts=time.time())
    append_heartbeat_event("nudge", line)
    BUS.emit("presence_nudge", text=line)
    state.push_control({"action": "speak", "text": line})


def heartbeat_loop() -> None:
    while not _stop.is_set():
        _heartbeat_tick()
        _stop.wait(90)


def start_heartbeat() -> None:
    load_presence()
    from rau.scheduler import SCHEDULER

    SCHEDULER.register_timer(
        "presence", _heartbeat_tick, interval_sec=90.0, initial_delay_sec=2.0
    )


def stop_heartbeat() -> None:
    from rau.scheduler import SCHEDULER

    SCHEDULER.unregister_timer("presence")


def _heartbeat_tick() -> None:
    try:
        maybe_nudge()
        ht = state.get_hard_task()
        if ht.get("state") == "running":
            progress = str(ht.get("progress") or "still working")
            BUS.emit("hard_task_progress", progress=progress, id=ht.get("id"))
            gap = gap_since_last_user()
            if gap is not None and gap >= REENTRY_SOFT_SEC:
                append_heartbeat_event("task_progress", progress)
    except Exception:
        pass
