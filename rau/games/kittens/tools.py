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

Tool results always carry `rau_view` (or `seat_view` for Rau from `apply_move`),
never the human's seat — private outcomes like a See the Future peek land in the
summary and `state` of the same tool call that earned them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from rau.games.kittens import deck as deck_mod, session
from rau.games.kittens import view as view_mod
from rau.games.kittens.deck import EXPLODING_KITTEN, SEE_THE_FUTURE
from rau.games.kittens.engine import PHASE_DEFUSE, PHASE_NOPE, PHASE_OVER, RAU

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


def _rau_state() -> Optional[Dict[str, Any]]:
    game = session.current()
    return view_mod.rau_view(game) if game else None


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
                "state": _rau_state(),
            }
        session.start()
        record = session.tally()
        return {
            "ok": True,
            "summary": "Dealt. They go first.",
            "state": _rau_state(),
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
        game = session.current()
        hand_before = list(game.hands[RAU]) if game else []
        result = session.apply_move(RAU, args)
        if not result.get("ok"):
            return result
        state = result.get("state") or {}
        return {
            "ok": True,
            "summary": _describe(args, state, hand_before=hand_before),
            "state": state,
        }

    return {"ok": False, "error": f"unknown tool {name}", "code": "unknown_tool"}


def _gained_cards(before: List[str], after: List[str]) -> List[str]:
    """Cards in `after` that are not explained by `before` (multiset difference)."""
    remaining = list(before)
    gained: List[str] = []
    for card in after:
        if card in remaining:
            remaining.remove(card)
        else:
            gained.append(card)
    return gained


def _peek_clause(state: Dict[str, Any]) -> str:
    known = list(state.get("known_top") or [])
    if not known:
        return ""
    peeked = ", ".join(deck_mod.label(c) for c in known)
    return f" Top of the deck (in order): {peeked}."


def _describe(
    args: Dict[str, Any],
    state: Optional[Dict[str, Any]] = None,
    *,
    hand_before: Optional[List[str]] = None,
) -> str:
    """
    What happened, in prose the model can use on the next thought.

    `state` is Rau's seat view after the move. Private outcomes that landed in
    that view (a peek, a drawn card, a stolen card) are named here so he does
    not have to wait for the next system-prompt rebuild.
    """
    state = state or {}
    move = str(args.get("move") or "")
    # See the Future names the peek itself; other moves only remind if a prior
    # peek is still valid in this seat view.
    remind_peek = True
    if move == "play":
        card = str(args.get("card") or "")
        label = deck_mod.label(card)
        if card == SEE_THE_FUTURE:
            remind_peek = False
            pending = state.get("pending") or {}
            pending_cards = pending.get("cards") or []
            if state.get("phase") == PHASE_NOPE and SEE_THE_FUTURE in pending_cards:
                return f"Played {label}. Waiting to see if they Nope it."
            known = list(state.get("known_top") or [])
            if known:
                peeked = ", ".join(deck_mod.label(c) for c in known)
                return f"Played {label}. Top of the deck (in order): {peeked}."
            return f"Played {label}. Top of the deck: (empty)."
        summary = f"Played {label}."
    elif move == "combo":
        cards = args.get("cards") or []
        summary = f"Played {len(cards)} cards as a set."
        pending = state.get("pending") or {}
        if state.get("phase") == PHASE_NOPE and pending:
            summary = f"{summary} Waiting to see if they Nope it."
        elif hand_before is not None:
            gained = _gained_cards(hand_before, list(state.get("hand") or []))
            # Combo discards the played set; anything still "gained" was stolen
            # or demanded into the hand when the window resolved in this call.
            if gained:
                got = ", ".join(deck_mod.label(c) for c in gained)
                summary = f"{summary} Got {got}."
    elif move == "draw":
        if state.get("phase") == PHASE_OVER:
            summary = "Drew the Exploding Kitten — and that ended it."
        elif state.get("phase") == PHASE_DEFUSE:
            summary = "Drew the Exploding Kitten and used a Defuse. Put it back."
        elif hand_before is not None:
            gained = _gained_cards(hand_before, list(state.get("hand") or []))
            gained = [c for c in gained if c != EXPLODING_KITTEN]
            if len(gained) == 1:
                summary = f"Drew {deck_mod.label(gained[0])}."
            else:
                summary = "Drew a card."
        else:
            summary = "Drew a card."
    elif move == "nope":
        summary = "Noped it."
    elif move == "pass_nope":
        # Letting their card stand may resolve a steal into our hand.
        if hand_before is not None:
            gained = _gained_cards(hand_before, list(state.get("hand") or []))
            if gained:
                got = ", ".join(deck_mod.label(c) for c in gained)
                summary = f"Let it stand. Received {got}."
            else:
                summary = "Let it stand."
        else:
            summary = "Let it stand."
    elif move == "give_favor":
        summary = f"Handed over {deck_mod.label(str(args.get('card')))}."
    elif move == "take_from_discard":
        summary = f"Took {deck_mod.label(str(args.get('card')))} off the pile."
    elif move == "insert_kitten":
        summary = "Put the kitten back."
    elif move == "concede":
        summary = "Conceded."
    else:
        summary = move

    if remind_peek:
        summary = summary.rstrip(".") + "." + _peek_clause(state)
    return summary
