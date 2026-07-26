"""
Things in the room Rau can pick up and put somewhere else.

The point is not that an object teleports when the model asks for it. The point
is that asking produces an *errand*: he walks over, crouches, takes the weight,
carries it across the room and sets it down. The renderer owns that performance;
this module owns what is true — which objects exist, where they may go, and
where each one is now.

Closed-world for the same reason `choreography` is: the model names an object
and a place from fixed lists, never coordinates, so the worst a bad call can do
is fail validation.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from rau.events import BUS
from rau.face import choreography

#: Objects light enough to carry. Mirrors `PROPS` in web/src/clawd/props.ts.
PROPS: Dict[str, Dict[str, str]] = {
    "mug": {"label": "the mug", "home": "desk"},
    "books": {"label": "the stack of books", "home": "floor_left"},
    "box": {"label": "the cardboard box", "home": "floor_far_left"},
    "plant": {"label": "the potted plant", "home": "floor_mid"},
}

#: Places an object can rest. Mirrors `PROP_SPOTS` in web/src/clawd/props.ts.
#: Each is a surface with a height, so a mug on the desk sits on the desk and a
#: mug on the floor sits on the floor.
SPOTS: Dict[str, Dict[str, Any]] = {
    "desk": {"label": "the desk"},
    "shelf": {"label": "the lower shelf"},
    "sill": {"label": "the window sill"},
    "rug": {"label": "the rug"},
    "floor_far_left": {"label": "the far left of the floor"},
    "floor_left": {"label": "the floor by the radiator"},
    "floor_mid": {"label": "the middle of the floor"},
    "floor_right": {"label": "the floor by the shelf"},
}

PROP_IDS: Tuple[str, ...] = tuple(PROPS)
SPOT_IDS: Tuple[str, ...] = tuple(SPOTS)

#: How long the renderer is given to walk over, lift, carry and set down.
#: Generous: the errand is a performance and must not be cut off half way.
ERRAND_TIMEOUT_MS = 30_000

_lock = threading.RLock()
_layout: Dict[str, str] = {name: spec["home"] for name, spec in PROPS.items()}


def layout() -> Dict[str, str]:
    """Where every object is right now."""
    with _lock:
        return dict(_layout)


def reset_layout() -> Dict[str, str]:
    """Put everything back where it started."""
    with _lock:
        _layout.clear()
        _layout.update({name: spec["home"] for name, spec in PROPS.items()})
        out = dict(_layout)
    BUS.emit("prop_layout", layout=out)
    return out


def describe_layout() -> str:
    """One line per object, for the system prompt."""
    current = layout()
    return "\n".join(
        f"- {PROPS[name]['label']} is on {SPOTS[spot]['label']}"
        for name, spot in sorted(current.items())
        if spot in SPOTS
    )


MOVE_OBJECT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "move_object",
        "description": (
            "Pick something up and put it somewhere else in your room. You "
            "will actually walk over, lift it, carry it across and set it "
            "down — it takes a few seconds, so do it because it makes sense, "
            "not for decoration. Say what you are doing naturally if it is "
            "worth mentioning; never narrate this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "object": {
                    "type": "string",
                    "enum": list(PROP_IDS),
                    "description": "Which object to move.",
                },
                "to": {
                    "type": "string",
                    "enum": list(SPOT_IDS),
                    "description": "Where to put it down.",
                },
            },
            "required": ["object", "to"],
            "additionalProperties": False,
        },
    },
}


def move_object(
    args: Dict[str, Any], *, turn_id: Optional[str] = None
) -> Dict[str, Any]:
    """Validate and publish one errand."""
    # The turn scope exists so callers do not have to thread the id through by
    # hand; reading it here means a caller that forgets still produces an event
    # a client can tie to the reply it belongs to.
    turn_id = turn_id or choreography.current_turn_id()
    if not isinstance(args, dict):
        return {"ok": False, "error": "arguments must be an object", "code": "malformed"}

    unknown = set(args) - {"object", "to"}
    if unknown:
        return {
            "ok": False,
            "error": f"unknown field(s): {', '.join(sorted(unknown))}",
            "code": "unknown_field",
        }

    name = args.get("object")
    if not isinstance(name, str) or name not in PROPS:
        return {
            "ok": False,
            "error": f"unknown object — choose from {', '.join(PROP_IDS)}",
            "code": "unknown_object",
        }

    spot = args.get("to")
    if not isinstance(spot, str) or spot not in SPOTS:
        return {
            "ok": False,
            "error": f"unknown place — choose from {', '.join(SPOT_IDS)}",
            "code": "unknown_spot",
        }

    with _lock:
        origin = _layout.get(name, PROPS[name]["home"])
        if origin == spot:
            return {
                "ok": False,
                "error": f"{PROPS[name]['label']} is already on {SPOTS[spot]['label']}",
                "code": "already_there",
                "at": spot,
            }
        # Committed here rather than when the renderer finishes: the model's
        # next turn must read the room as it will be, and a browser that is
        # closed mid-errand should not leave the object in limbo.
        _layout[name] = spot
        snapshot = dict(_layout)

    errand_id = f"errand_{uuid.uuid4().hex[:12]}"
    BUS.emit(
        "prop_move",
        errand_id=errand_id,
        turn_id=turn_id or "",
        object=name,
        **{"from": origin},
        to=spot,
        layout=snapshot,
        timeout_ms=ERRAND_TIMEOUT_MS,
        created=time.time(),
    )
    return {
        "ok": True,
        "errand_id": errand_id,
        "object": name,
        "from": origin,
        "to": spot,
        "note": "You are carrying it there now; it takes a few seconds.",
    }


def prompt_fragment() -> str:
    """What the face model is told about its own room."""
    lines: List[str] = [
        "## Things in your room",
        "You can pick these up and move them with `move_object`. Doing so is a "
        "real errand — you walk over, lift it, carry it and put it down — so it "
        "is worth doing when it means something and not otherwise.",
        describe_layout(),
        f"Places: {', '.join(SPOTS[s]['label'] for s in SPOT_IDS)}.",
    ]
    return "\n".join(lines)
