"""
What each audience is shown, which for chess is very nearly everything.

`kittens/view.py` is a long file because Exploding Kittens is a game of hidden
information: the engine holds both hands and the exact order of the draw pile,
and that module exists to cut the truth down before it can leave the process.
Chess is perfect information. Both players are looking at the same board, and
there is nothing here to redact, so almost all of that file has no counterpart
and this one collapses to shape rather than secrecy.

Three cuts remain, and they are about attention rather than fairness:

* `browser_view` — the wire format. The client stays dumb: it renders a position
  and sends a from-square and a to-square, and the server decides whether that
  was a move. There is deliberately no `legal_moves` field, so a legal-move
  highlight cannot be added by accident downstream.

* `talker_fragment` — what the face half sees while chatting. The position in
  prose and the shared journal, and an explicit reminder that his player half
  makes the moves. A talker holding a move menu is exactly the confusion this
  feature is built to avoid.

* `coarse_read` — the only thing `player` and `banter` are ever allowed to know
  about the evaluation: a bucket word, a swing described in English, recent SAN,
  material, and roughly where the game is. Centipawns, depth and the principal
  variation stop at the engine layer. If a future edit threads a score through
  here it will be visibly wrong against this docstring, which is the point of
  saying so.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import chess

from rau.games.chess.board import (
    PHASE_OVER,
    PHASE_THINKING,
    RAU,
    USER,
    ChessGame,
)

#: Rough piece values, for a material count a person would say out loud. Not an
#: evaluation — the king is absent and nothing is weighted by position.
_VALUES: Dict[int, int] = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}

#: Ply at which the opening is over for the purposes of anything he says.
OPENING_PLY = 16

#: Men left on the board below which this is an endgame. Matches the same
#: threshold `timing.py` uses to shorten his think.
ENDGAME_MEN = 12

_BUCKET_WORDS: Dict[str, str] = {
    "winning": "you are winning this comfortably",
    "better": "you are better here",
    "level": "it is about even",
    "worse": "you are worse here",
    "losing": "you are losing this",
}


# ---------------------------------------------------------------- the wire


def browser_view(game: ChessGame) -> Dict[str, Any]:
    """
    The board as the page renders it. One view — nobody is hiding anything.

    Everything factual comes out of `game.snapshot()` in one locked read rather
    than field by field. The pump pushes moves from its own thread, and a view
    assembled a getter at a time can hand the page a FEN from before the move and
    a `turn` from after it.

    Two keys are added on top. The phase is promoted to `thinking` from `player`,
    not read off the board — a pause is something he is doing, not something true
    about the position, and keeping it out of `board.py` means a reload cannot
    resume into a stare. The log is the feed beside the board.
    """
    from rau.games.chess import player

    state: Dict[str, Any] = game.snapshot()
    if state["phase"] != PHASE_OVER and player.thinking_on(game):
        state["phase"] = PHASE_THINKING

    thinking = state["phase"] == PHASE_THINKING
    state["thinking"] = {"hover": player.current_hover()} if thinking else None
    # There is no `legal_moves` key and there should not be one. The user asked
    # for a board without hints; the client selects two squares and finds out
    # from the server whether that was a move.
    state["log"] = [{"seat": e.seat, "text": e.text, "at": e.at} for e in game.log[-12:]]
    return state


# --------------------------------------------------------------- the model


def _material(board: chess.Board) -> Tuple[int, int]:
    """(white, black) in pawns, the way you count it by looking at the table."""
    white = 0
    black = 0
    for piece in board.piece_map().values():
        value = _VALUES.get(piece.piece_type, 0)
        if piece.color == chess.WHITE:
            white += value
        else:
            black += value
    return white, black


def _stage(board: chess.Board) -> str:
    if len(board.piece_map()) < ENDGAME_MEN:
        return "endgame"
    if len(board.move_stack) < OPENING_PLY:
        return "opening"
    return "middlegame"


def _swing_phrase(swing: float) -> str:
    """The last move's effect, in words. No numbers reach the model from here."""
    size = abs(swing)
    if size < 0.3:
        return "Nothing much moved on that one."
    if swing > 0:
        if size >= 2.0:
            return "That swung hard your way."
        if size >= 0.8:
            return "That went your way."
        return "That helped you a little."
    if size >= 2.0:
        return "That swung hard against you."
    if size >= 0.8:
        return "That went against you."
    return "That cost you a little."


def _check_clause(game: ChessGame) -> str:
    if not game.check_square():
        return ""
    # The side to move is the side in check.
    return "They are in check." if game.turn_seat() == USER else "You are in check."


def _position_lines(game: ChessGame) -> list:
    board = game.board
    mine, theirs = _material(board)
    if game.rau_color == "black":
        mine, theirs = theirs, mine
    recent = " ".join(game.moves[-6:]) if game.moves else ""
    lines = [
        "## The game of chess on the table",
        "",
        f"You have {game.rau_color}, they have {game.user_color}.",
        f"Moves so far: {len(game.moves)}. It is the {_stage(board)}.",
        f"Recently: {recent or '(nothing yet)'}",
        f"Material: you {mine}, them {theirs}.",
    ]
    check = _check_clause(game)
    if check:
        lines.append(check)
    if game.offer:
        who = "You have" if game.offer.get("by") == RAU else "They have"
        lines.append(f"{who} offered a draw. It is still on the table.")
    return lines


def coarse_read(game: ChessGame, read: Optional[Dict[str, Any]] = None) -> str:
    """
    The position as his talking half is allowed to know it.

    `read` is `session.last_read()` — a bucket word and a swing in pawns, and
    nothing else ever came out of the engine. The swing is spent here on an
    English phrase and never printed, so there is no number in this string for a
    model to read back across the table.
    """
    data = read or {}
    bucket = str(data.get("bucket") or "level")
    swing = float(data.get("swing") or 0.0)

    lines = _position_lines(game)
    if game.phase == PHASE_OVER:
        won = game.winner == RAU
        lines.append("")
        lines.append(
            f"{'You won' if won else 'They beat you' if game.winner == USER else 'It was a draw'}. "
            f"{game.over_reason}"
        )
        return "\n".join(lines) + "\n"

    lines.append("")
    lines.append(f"Where you stand: {_BUCKET_WORDS.get(bucket, _BUCKET_WORDS['level'])}.")
    lines.append(_swing_phrase(swing))
    return "\n".join(lines) + "\n"


def talker_fragment(game: ChessGame, seat: str = RAU) -> str:
    """
    The board as the face talker sees it — position and journal, no move menu.

    He can offer a draw, resign, or clear the table, and that is the whole of his
    agency here. The moves are made by the other half of him.
    """
    from rau.games.chess import journal

    if game.phase == PHASE_OVER:
        won = game.winner == seat
        drawn = game.winner is None
        lines = [
            "\n## The chess game",
            f"{'A draw' if drawn else 'You won' if won else 'You lost'}. {game.over_reason}",
            "The board is finished. React to it in your own voice, then let it go.",
        ]
    else:
        lines = _position_lines(game)
        lines.append("")
        lines.append(
            "It is your move." if game.turn_seat() == seat else "It is their move. Wait, and talk."
        )
        lines.append("")
        lines.append(
            "Your player half moves the pieces at this board. You talk across it — "
            "react, needle, compliment a good move. You cannot push a piece "
            "yourself; chess_move is for resigning and draws, and start_chess and "
            "end_chess are the rest of what you have."
        )

    history = journal.tail()
    if history:
        lines.append("")
        lines.append(history.strip())
    return "\n".join(lines) + "\n"


__all__ = ["browser_view", "coarse_read", "talker_fragment"]
