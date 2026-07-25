"""
Model-authored body choreography.

The face model gets one tool, `body_choreography`, with which it can stage the
avatar for the reply it is about to speak: pick an existing motion, aim the
gaze, send itself to a station in the room, and anchor each of those to an
exact phrase of the reply.

Everything here is deliberately closed-world. The model chooses from the same
enums the renderer already ships, never raw rig parameters and never a motion
of its own devising, so a bad plan is a validation error rather than a
character that falls apart on screen. Plans are addressed by the turn id the
server generated for the turn in flight — the model cannot name another
session, and it cannot outlive its own turn.
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from rau.events import BUS

#: Clips the renderer knows. Mirrors `MOTIONS` in web/src/clawd/motions.ts —
#: the frontend test suite asserts the two lists have not drifted apart.
MOTIONS: Tuple[str, ...] = (
    "idle",
    "walk",
    "wave",
    "type",
    "bounce",
    "think",
    "sleep",
    "talk",
    "celebrate",
    "startle",
    "gaze",
    "listen",
    "nod",
    "perk",
    "recoil",
    "shrug",
    "stretch",
    "shuffle",
)

#: Places in the room. Mirrors `STATIONS` in web/src/clawd/room.ts.
STATIONS: Tuple[str, ...] = ("window", "plant", "centre", "desk", "shelf")

#: Semantic gaze targets. The renderer turns each into an eye aim; the model
#: never gets to write eye coordinates.
GAZE_TARGETS: Tuple[str, ...] = (
    "user",
    "away",
    "room",
    "floor",
    "up",
    "screen",
    "window",
)

ANCHORS: Tuple[str, ...] = ("reply_start", "phrase", "reply_end")

MAX_CUES = 8
MAX_PHRASE_CHARS = 80
MAX_OCCURRENCE = 8
MIN_HOLD_MS = 250
MAX_HOLD_MS = 8_000
#: A plan may not choreograph more than two minutes of a single turn.
MAX_PLAN_MS = 120_000

#: Defaults, when the model gives a cue no hold of its own. Walking somewhere
#: needs longer than a gesture, and a gesture needs longer than a glance.
DEFAULT_HOLD_STATION_MS = 2_500
DEFAULT_HOLD_MOTION_MS = 1_500
DEFAULT_HOLD_GAZE_MS = 1_200


BODY_CHOREOGRAPHY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "body_choreography",
        "description": (
            "Stage your body for the reply you are about to speak. Call this "
            "BEFORE you speak, at most once per turn, and only when the "
            "movement genuinely adds something — most turns need no plan at "
            "all. Each cue picks a motion, a place to look, and/or somewhere "
            "in the room to stand, and is anchored either to the start of the "
            "reply, to the end of it, or to an exact phrase you then have to "
            "use verbatim in what you say. Never mention this tool out loud."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cues": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_CUES,
                    "description": "Ordered cues, at most 8.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "anchor": {
                                "type": "string",
                                "enum": list(ANCHORS),
                                "description": (
                                    "When the cue fires: as the reply begins, "
                                    "as an exact phrase becomes audible, or "
                                    "once the reply is finished."
                                ),
                            },
                            "phrase": {
                                "type": "string",
                                "maxLength": MAX_PHRASE_CHARS,
                                "description": (
                                    "Required for anchor=phrase. Must appear "
                                    "word-for-word in your reply."
                                ),
                            },
                            "occurrence": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_OCCURRENCE,
                                "description": (
                                    "Which occurrence of a repeated phrase to "
                                    "fire on. Defaults to the first."
                                ),
                            },
                            "motion": {
                                "type": "string",
                                "enum": list(MOTIONS),
                                "description": "Clip to play.",
                            },
                            "gaze": {
                                "type": "string",
                                "enum": list(GAZE_TARGETS),
                                "description": "Where to look.",
                            },
                            "station": {
                                "type": "string",
                                "enum": list(STATIONS),
                                "description": "Where in the room to stand.",
                            },
                            "hold_ms": {
                                "type": "integer",
                                "minimum": MIN_HOLD_MS,
                                "maximum": MAX_HOLD_MS,
                                "description": (
                                    "How long this cue keeps the body before "
                                    "autonomous behaviour resumes."
                                ),
                            },
                        },
                        "required": ["anchor"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["cues"],
            "additionalProperties": False,
        },
    },
}


#: Prompt fragment appended to the face system prompt. Kept next to the schema
#: so the rules the model is told match the rules it is judged by.
PROMPT = (
    "## Your body\n"
    "You are drawn as a small character in a room, and `body_choreography` is "
    "how you move on purpose. Call it before you speak, never after, and never "
    "more than once per turn. Anchor a cue to `reply_start`, to `reply_end`, "
    "or to a `phrase` you then say word-for-word — an anchor phrase you do not "
    "actually speak simply never fires. Keep it rare and keep it small: one or "
    "two cues on a turn where movement means something, and nothing at all on "
    "an ordinary turn. Never read the plan out loud, never describe the tool, "
    "and never narrate your own gestures."
)


# ── turn scoping ──────────────────────────────────────────────────────
#
# A plan belongs to the turn the server is running, and only the server knows
# that id. The face brain runs a whole turn — provider stream, tool rounds and
# all — on a single thread, so a thread local is exactly the right scope: two
# concurrent turns (a typed one and a spoken one) each see their own.

_local = threading.local()


def new_turn_id() -> str:
    return f"turn_{uuid.uuid4().hex[:12]}"


def current_turn_id() -> Optional[str]:
    return getattr(_local, "turn_id", None)


@contextmanager
def turn_scope(turn_id: str) -> Iterator[str]:
    """Bind a server-generated turn id for the duration of one face turn."""
    previous = getattr(_local, "turn_id", None)
    _local.turn_id = turn_id
    try:
        yield turn_id
    finally:
        _local.turn_id = previous


# ── validation ────────────────────────────────────────────────────────


class PlanError(ValueError):
    """A rejected plan, carrying the machine-readable reason and cue index."""

    def __init__(self, code: str, message: str, cue: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.cue = cue

    def as_result(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "ok": False,
            "error": self.message,
            "code": self.code,
        }
        if self.cue is not None:
            result["cue"] = self.cue
        return result


def _default_hold(cue: Dict[str, Any]) -> int:
    if cue.get("station"):
        return DEFAULT_HOLD_STATION_MS
    if cue.get("motion"):
        return DEFAULT_HOLD_MOTION_MS
    return DEFAULT_HOLD_GAZE_MS


def _validate_cue(raw: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlanError("malformed_cue", "each cue must be an object", index)

    unknown = set(raw) - {
        "anchor",
        "phrase",
        "occurrence",
        "motion",
        "gaze",
        "station",
        "hold_ms",
    }
    if unknown:
        raise PlanError(
            "unknown_field",
            f"unknown cue field(s): {', '.join(sorted(unknown))}",
            index,
        )

    anchor = raw.get("anchor")
    if not isinstance(anchor, str) or anchor not in ANCHORS:
        raise PlanError(
            "malformed_anchor",
            f"anchor must be one of {', '.join(ANCHORS)}",
            index,
        )

    cue: Dict[str, Any] = {"anchor": anchor}

    phrase = raw.get("phrase")
    occurrence = raw.get("occurrence")
    if anchor == "phrase":
        if not isinstance(phrase, str) or not phrase.strip():
            raise PlanError(
                "missing_phrase", "anchor=phrase needs a non-empty phrase", index
            )
        phrase = phrase.strip()
        if len(phrase) > MAX_PHRASE_CHARS:
            raise PlanError(
                "phrase_too_long",
                f"phrase must be at most {MAX_PHRASE_CHARS} characters",
                index,
            )
        cue["phrase"] = phrase
        if occurrence is None:
            cue["occurrence"] = 1
        else:
            if isinstance(occurrence, bool) or not isinstance(occurrence, int):
                raise PlanError(
                    "malformed_occurrence", "occurrence must be an integer", index
                )
            if not 1 <= occurrence <= MAX_OCCURRENCE:
                raise PlanError(
                    "malformed_occurrence",
                    f"occurrence must be between 1 and {MAX_OCCURRENCE}",
                    index,
                )
            cue["occurrence"] = occurrence
    else:
        # A phrase on a reply_start/reply_end cue is a contradiction, not a
        # harmless extra: whichever of the two the model meant, half of what it
        # asked for would silently not happen.
        if phrase is not None or occurrence is not None:
            raise PlanError(
                "conflicting_controls",
                "phrase/occurrence only apply to anchor=phrase",
                index,
            )

    for field, allowed, code in (
        ("motion", MOTIONS, "unknown_motion"),
        ("gaze", GAZE_TARGETS, "unknown_gaze"),
        ("station", STATIONS, "unknown_station"),
    ):
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or value not in allowed:
            raise PlanError(
                code,
                f"unknown {field} '{value}' — choose from {', '.join(allowed)}",
                index,
            )
        cue[field] = value

    if not any(key in cue for key in ("motion", "gaze", "station")):
        raise PlanError(
            "empty_cue",
            "a cue must set at least one of motion, gaze or station",
            index,
        )

    hold = raw.get("hold_ms")
    if hold is None:
        cue["hold_ms"] = _default_hold(cue)
    else:
        if isinstance(hold, bool) or not isinstance(hold, (int, float)):
            raise PlanError("malformed_hold", "hold_ms must be a number", index)
        hold = int(hold)
        if not MIN_HOLD_MS <= hold <= MAX_HOLD_MS:
            raise PlanError(
                "hold_out_of_range",
                f"hold_ms must be between {MIN_HOLD_MS} and {MAX_HOLD_MS}",
                index,
            )
        cue["hold_ms"] = hold

    return cue


def validate_cues(raw_cues: Any) -> List[Dict[str, Any]]:
    """Normalise a model-supplied cue list, or raise `PlanError`."""
    if not isinstance(raw_cues, list):
        raise PlanError("malformed_plan", "cues must be an array")
    if not raw_cues:
        raise PlanError("empty_plan", "a plan needs at least one cue")
    if len(raw_cues) > MAX_CUES:
        raise PlanError(
            "too_many_cues", f"a plan may hold at most {MAX_CUES} cues"
        )

    cues: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()
    total = 0
    for index, raw in enumerate(raw_cues):
        cue = _validate_cue(raw, index)
        key: Tuple[Any, ...]
        if cue["anchor"] == "phrase":
            key = ("phrase", cue["phrase"].casefold(), cue["occurrence"])
        else:
            key = (cue["anchor"],)
        if key in seen:
            raise PlanError(
                "duplicate_anchor",
                "two cues cannot fire on the same anchor",
                index,
            )
        seen.add(key)
        total += cue["hold_ms"]
        if total > MAX_PLAN_MS:
            raise PlanError(
                "plan_too_long",
                f"total hold must not exceed {MAX_PLAN_MS} ms",
                index,
            )
        cues.append(cue)
    return cues


# ── the tool ──────────────────────────────────────────────────────────


def submit_plan(args: Dict[str, Any], *, turn_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Run one `body_choreography` call.

    Returns `{ok, plan_id, accepted_cues}` and broadcasts the plan to every
    mounted avatar, or a structured validation error that the model can read
    and correct on its next round.
    """
    turn = turn_id or current_turn_id()
    if not turn:
        return {
            "ok": False,
            "error": "no turn is in flight to choreograph",
            "code": "no_turn",
        }
    if not isinstance(args, dict):
        return PlanError("malformed_plan", "arguments must be an object").as_result()

    unknown = set(args) - {"cues"}
    if unknown:
        return PlanError(
            "unknown_field",
            f"unknown plan field(s): {', '.join(sorted(unknown))}",
        ).as_result()

    try:
        cues = validate_cues(args.get("cues"))
    except PlanError as error:
        return error.as_result()

    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    BUS.emit(
        "body_plan",
        turn_id=turn,
        plan_id=plan_id,
        cues=cues,
        expires_ms=MAX_PLAN_MS,
        created=time.time(),
    )
    return {"ok": True, "plan_id": plan_id, "accepted_cues": len(cues)}


def cancel_turn(turn_id: str, reason: str = "cancelled") -> None:
    """Drop any unfired cues for a turn that was interrupted or superseded."""
    if not turn_id:
        return
    BUS.emit("body_cancel", turn_id=turn_id, reason=str(reason)[:120])
