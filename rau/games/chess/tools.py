"""
How Rau reaches the board.

Three tools, shaped the way the kittens tools are: closed vocabularies, no
free-form state, and a refusal that teaches rather than one that says invalid.

The interesting one is `chess_move`, and what it cannot do. Its vocabulary is
resign, offer a draw, accept a draw, decline a draw — and no way at all to push
a piece. That is not an oversight in the schema. Stockfish plays this game and
the model performs it, and putting a from-square and a to-square in front of him
would be handing back the exact ability the whole feature is arranged to take
away. The inversion is enforced here, in the tool definition, and not merely by
everyone remembering it.

`start_chess` checks for the engine binary before it sets anything up, so a
machine without Stockfish gets him saying he has no board rather than a pump
that crashes two seconds later against a missing path.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rau.games.chess import session
from rau.games.chess import view as view_mod

#: Everything he may do at a board. Conspicuously not "move".
MOVES: List[str] = ["resign", "offer_draw", "accept_draw", "decline_draw"]

COLORS: List[str] = ["white", "black", "random"]

START_GAME_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "start_chess",
        "description": (
            "Set up a game of chess between you and them, and put the board up "
            "on screen. Use this when they ask to play, or when you offer and "
            "they say yes. Leave the colour alone unless they ask for a side — "
            "by default the two of you swap colours each new game, the way "
            "people at a real board do. Once the board is out you will see the "
            "position every turn; the moves take care of themselves, so your "
            "job across the board is to talk."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "color": {
                    "type": "string",
                    "enum": COLORS,
                    "description": (
                        "Which side you take, only if they asked. Omit it to "
                        "alternate colours from the last game."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

CHESS_MOVE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "chess_move",
        "description": (
            "The things you can do at the board that are not moves: resign, "
            "offer a draw, or answer one they offered. You do not push pieces "
            "with this and there is no way to — that half of you plays without "
            "asking. Resign only when the position is genuinely lost and you "
            "mean it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "move": {
                    "type": "string",
                    "enum": MOVES,
                    "description": "Which of them you are doing.",
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
        "name": "end_chess",
        "description": (
            "Put the board away. Use it when they say they are done, or when a "
            "finished game has been sitting there a while. Resigning a game "
            "still in progress is chess_move with move=resign — that is a "
            "different thing and it goes in the record."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}

TOOLS: List[Dict[str, Any]] = [START_GAME_TOOL, CHESS_MOVE_TOOL, END_GAME_TOOL]
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)


def _state() -> Optional[Dict[str, Any]]:
    game = session.current()
    return view_mod.browser_view(game) if game else None


def run_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a board tool. Never raises; a refused move is a result, not an error."""
    if not isinstance(args, dict):
        args = {}

    if name == "start_chess":
        from rau.games.chess import binary

        if binary.found() is None:
            # He declines in character. There is no half-strength fallback worth
            # having: a chess opponent who cannot see the board is not one.
            return {
                "ok": False,
                "error": "can't — there's no engine on this machine to play through",
                "code": "no_engine",
            }
        if session.active():
            return {
                "ok": False,
                "error": "there's already a board out",
                "code": "game_in_progress",
                "state": _state(),
            }
        colour = str(args.get("color") or "").strip().lower()
        if colour and colour not in COLORS:
            return {
                "ok": False,
                "error": f"pick a side: {', '.join(COLORS)}",
                "code": "malformed",
            }
        # No colour asked for means alternate from the last finished game.
        state = session.start(rau_color=colour or None)
        opener = "He opens." if state.get("rau_color") == "white" else "They open."
        return {
            "ok": True,
            "summary": f"Board is out. You have {state.get('rau_color')}. {opener}",
            "state": state,
            "record": session.tally() or None,
        }

    if name == "end_chess":
        session.end("rau put the board away")
        return {"ok": True, "summary": "Board put away."}

    if name == "chess_move":
        if not session.active():
            return {
                "ok": False,
                "error": "there's no board out — set one up first",
                "code": "no_game",
            }
        move = str(args.get("move") or "")
        if move not in MOVES:
            return {
                "ok": False,
                "error": f"not one of yours: {', '.join(MOVES)}",
                "code": "malformed",
            }
        from rau.games.chess.board import RAU

        result = session.apply_move(RAU, {"move": move})
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "summary": _SUMMARIES[move],
            "state": result.get("state"),
        }

    return {"ok": False, "error": f"unknown tool {name}", "code": "unknown_tool"}


_SUMMARIES: Dict[str, str] = {
    "resign": "Resigned. That one is theirs.",
    "offer_draw": "Offered them a draw. Waiting to hear.",
    "accept_draw": "Took the draw.",
    "decline_draw": "Waved the draw off. Still playing.",
}


__all__ = ["TOOLS", "TOOL_NAMES", "run_tool"]
