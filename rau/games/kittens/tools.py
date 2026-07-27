"""
How Rau reaches the table.

Three tools, shaped the same way the panel tools are: closed vocabularies, no
free-form state, and a refusal that teaches. An illegal move comes back with the
enumerated legal moves attached, so the model's next attempt is a copy rather
than another guess — the same reason `panels.show_panel` returns the exact field
it disliked instead of "invalid".

`play_kittens_card` is one tool with a `move` discriminator rather than eight
small ones. During a game the model is choosing between moves, not between
capabilities, and a single tool means the choice is a single enum it has already
been handed the legal values for.
"""
from __future__ import annotations

from typing import Any, Dict, List

from rau.games.kittens import deck as deck_mod, session
from rau.games.kittens.engine import RAU

MOVES: List[str] = [
    "play",
    "combo",
    "draw",
    "nope",
    "pass_nope",
    "give_favor",
    "take_from_discard",
    "insert_kitten",
    "concede",
]

START_GAME_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "start_kittens",
        "description": (
            "Deal a game of Exploding Kittens between you and them, and put the "
            "table up on screen. Use this when they ask to play, or when you "
            "offer and they say yes. They take the first turn. Once it is dealt, "
            "the state of the table is in front of you every turn — play it "
            "properly, play to win, and talk while you do."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

PLAY_CARD_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "play_kittens_card",
        "description": (
            "Make your move in the game on the table. Your hand and the exact "
            "legal moves are listed for you each turn — pick one of those and "
            "pass its arguments unchanged. Playing a card does not end your "
            "turn; only drawing or Skip does. Say one short line in your own "
            "voice with the move, never the rules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "move": {
                    "type": "string",
                    "enum": MOVES,
                    "description": "Which kind of move you are making.",
                },
                "card": {
                    "type": "string",
                    "enum": list(deck_mod.ALL_CARDS),
                    "description": "For play, give_favor, take_from_discard.",
                },
                "cards": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(deck_mod.ALL_CARDS)},
                    "description": (
                        "For combo: two or three matching cards, or five different ones."
                    ),
                },
                "named_card": {
                    "type": "string",
                    "enum": list(deck_mod.ALL_CARDS),
                    "description": (
                        "For a three-of-a-kind combo: the card you are demanding "
                        "from their hand. You are guessing — you cannot see it."
                    ),
                },
                "index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "For insert_kitten: where the defused kitten goes back. "
                        "0 is the very top of the deck."
                    ),
                },
            },
            "required": ["move"],
            "additionalProperties": False,
        },
    },
}

END_GAME_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "end_kittens",
        "description": (
            "Clear the table and put the game away. Use it when they say they "
            "are done, or when a finished game has been sitting there a while. "
            "Conceding mid-game is `play_kittens_card` with move=concede."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

TOOLS: List[Dict[str, Any]] = [START_GAME_TOOL, PLAY_CARD_TOOL, END_GAME_TOOL]
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)


def run_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a game tool. Never raises; a bad move is a result, not an error."""
    if not isinstance(args, dict):
        args = {}

    if name == "start_kittens":
        if session.active():
            return {
                "ok": False,
                "error": "there is already a game on the table",
                "code": "game_in_progress",
                "state": session.state(),
            }
        view = session.start()
        record = session.tally()
        return {
            "ok": True,
            "summary": "Dealt. They go first.",
            "state": view,
            "record": record or None,
        }

    if name == "end_kittens":
        session.end("rau cleared the table")
        return {"ok": True, "summary": "Table cleared."}

    if name == "play_kittens_card":
        if not session.active():
            return {
                "ok": False,
                "error": "there is no game on the table — deal one first",
                "code": "no_game",
            }
        result = session.apply_move(RAU, args)
        if not result.get("ok"):
            return result
        return {"ok": True, "summary": _describe(args), "state": result.get("state")}

    return {"ok": False, "error": f"unknown tool {name}", "code": "unknown_tool"}


def _describe(args: Dict[str, Any]) -> str:
    move = str(args.get("move") or "")
    if move == "play":
        return f"Played {deck_mod.label(str(args.get('card')))}."
    if move == "combo":
        cards = args.get("cards") or []
        return f"Played {len(cards)} cards as a set."
    if move == "draw":
        return "Drew a card."
    if move == "nope":
        return "Noped it."
    if move == "pass_nope":
        return "Let it stand."
    if move == "give_favor":
        return f"Handed over {deck_mod.label(str(args.get('card')))}."
    if move == "take_from_discard":
        return f"Took {deck_mod.label(str(args.get('card')))} off the pile."
    if move == "insert_kitten":
        return "Put the kitten back."
    if move == "concede":
        return "Conceded."
    return move
