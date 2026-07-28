"""
The pause, and what the claw does inside it.

Stockfish answers in a few milliseconds at the depth this feature uses, so
without this module Rau would reply to every move instantly and identically. That
one detail gives the whole thing away faster than any bad line would: a man who
takes the same eighth of a second over a forced recapture and over a position he
is losing is not thinking, and everyone can tell.

So the delay is manufactured, and it is manufactured from the position rather
than from a random number, because the *shape* is what reads as thought. Nothing
to decide is fast. Something just changed is slow. A crowded middlegame is slower
than a bare endgame. The jitter on top is lognormal rather than uniform for the
same reason people are: most turns cluster near the typical length and the tail
is on the long side, never the short one.

The hover script is the visible half of the same lie. He reaches toward a square,
sometimes toward the wrong one, sometimes sits back and looks at nothing, and
lands on the piece he plays a beat before he plays it. One time in four the last
thing he looks at is not the piece he moves — he considered something else and
changed his mind, which is the single cheapest thing that makes the pause look
occupied rather than merely long.

This module is pure. No engine, no clock, no disk, and `MoveChoice` is imported
for typing only, so the entire performance can be tested by handing it a board
and a `random.Random(7)` — no subprocess, no Stockfish on the test machine, and
the same seed gives the same theatre twice.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

import chess

if TYPE_CHECKING:  # runtime import would drag the Stockfish wrapper in here
    from rau.games.chess.engine import MoveChoice

#: Nothing may be shorter than this: below it the move looks like it arrived
#: before the user let go of their own piece.
FLOOR_SEC = 0.3

#: Nor longer. Past twenty seconds the user assumes he has crashed.
CEIL_SEC = 20.0

#: Spread of the lognormal jitter. Small enough that the bands still read as
#: distinct, large enough that two identical positions are not identical turns.
JITTER_SIGMA = 0.22

#: Bands from the contract, in seconds.
BAND_FORCED = (0.3, 0.8)
BAND_BOOK = (0.4, 1.2)
BAND_RECAPTURE = (0.8, 2.0)
BAND_STARE = (6.0, 18.0)
BAND_CROWDED = (4.0, 12.0)
BAND_ENDGAME = (2.0, 5.0)
BAND_ORDINARY = (2.0, 6.0)

#: A position with more than this many legal moves has enough to look at that
#: taking a while over it is credible.
CROWDED_MOVES = 30

#: Fewer men than this and there is simply less board to read.
ENDGAME_MEN = 12

#: How far into the game "book" can plausibly reach.
BOOK_PLY = 8

#: Swing past this and something happened worth staring at.
STARE_SWING = 1.5

#: Not an opening book — a list of moves that are unremarkable in the first four
#: moves of a game. It exists only to decide whether he answers quickly, so the
#: cost of it being wrong is half a second of pause on a move that deserved two,
#: and that is a fair trade against carrying a real book around.
BOOK_MOVES = frozenset(
    {
        "e4", "d4", "Nf3", "c4", "g3", "b3", "d3",
        "e5", "c5", "e6", "c6", "d5", "d6", "g6", "b6",
        "Nf6", "Nc6", "Nbd7", "Bb5", "Bc4", "Be2", "Bg2", "Bb4",
        "Bg7", "Be7", "Bg4", "Bf5", "a3", "a6", "h3", "h6",
        "exd5", "cxd5", "exd4", "cxd4", "Nxd4", "Nxe5", "O-O",
    }
)

#: The claw never lingers on a square for less than this — anything shorter
#: reads as a twitch rather than a look.
MIN_DWELL = 0.08

#: Fraction of the delay the hovers are allowed to fill. The remainder is the
#: beat of stillness before the piece actually moves, which is what makes the
#: move land rather than merely continue.
HOVER_FILL = (0.55, 0.85)

#: How often the last square he looks at is the one he plays from.
COMMIT_CHANCE = 0.75

#: How often an earlier step is nothing at all — sat back, looking at the whole
#: board.
SIT_BACK_CHANCE = 0.33


@dataclass(frozen=True)
class HoverStep:
    """One beat of the claw. `square` of None means he sat back."""

    square: Optional[str]
    dwell: float


@dataclass(frozen=True)
class ThinkPlan:
    delay: float
    hovers: List[HoverStep]


def _last_move_target(board: chess.Board) -> Optional[int]:
    """
    The square the user's piece just landed on, or None.

    A board rebuilt from a FEN after a restart has an empty move stack, so this
    degrades to "there was no last move" rather than raising in the middle of
    his first turn back.
    """
    try:
        return board.peek().to_square
    except (IndexError, AttributeError):
        return None


def _band(board: chess.Board, choice: "MoveChoice") -> Tuple[float, float]:
    """
    Which of the contract's cases this position falls into.

    They overlap — a forced recapture in an endgame is three of them at once —
    so the order below is the judgement, not the table.

    Forcedness comes first: it removes the thing he would be thinking about, and
    it does that even when the position is terrible. The long stare comes second,
    above book, because a swing that size in the first eight plies means the
    opening stopped being an opening — somebody gambited or somebody hung
    something, and answering a real surprise out of the book is the tell this
    whole module exists to avoid. Everything after that is texture.
    """
    legal = board.legal_moves.count()
    if legal <= 1:
        return BAND_FORCED
    if abs(choice.swing) > STARE_SWING:
        return BAND_STARE
    if board.ply() < BOOK_PLY and choice.san in BOOK_MOVES:
        return BAND_BOOK
    if choice.is_capture and choice.move.to_square == _last_move_target(board):
        # Taking back on the square they just took on. Deliberating over it
        # would read as not having seen it coming. It is also rarely a surprise:
        # if the recapture was available, the swing above stayed small.
        return BAND_RECAPTURE
    if legal > CROWDED_MOVES:
        return BAND_CROWDED
    if len(board.piece_map()) < ENDGAME_MEN:
        return BAND_ENDGAME
    return BAND_ORDINARY


def _delay(board: chess.Board, choice: "MoveChoice", *, rng: random.Random) -> float:
    low, high = _band(board, choice)
    raw = rng.uniform(low, high) * rng.lognormvariate(0.0, JITTER_SIGMA)
    return round(max(FLOOR_SEC, min(CEIL_SEC, raw)), 2)


def _step_count(delay: float, rng: random.Random) -> int:
    """Short pauses get one look. Long ones get room to change his mind."""
    if delay < 1.2:
        return 1
    if delay < 4.0:
        return 2
    return rng.choice((2, 3))


def _hovers(
    board: chess.Board,
    choice: "MoveChoice",
    delay: float,
    *,
    rng: random.Random,
) -> List[HoverStep]:
    home = chess.square_name(choice.move.from_square)
    others = sorted(
        {chess.square_name(m.from_square) for m in board.legal_moves} - {home}
    )

    count = _step_count(delay, rng)
    squares: List[Optional[str]] = []
    for index in range(count):
        last = index == count - 1
        if last:
            if others and rng.random() >= COMMIT_CHANCE:
                # He looked somewhere else last and played anyway.
                squares.append(rng.choice(others))
            else:
                squares.append(home)
        elif not others or rng.random() < SIT_BACK_CHANCE:
            squares.append(None)
        else:
            squares.append(rng.choice(others))

    # Two identical looks in a row is a dropped frame, not a decision.
    for index in range(1, len(squares)):
        if squares[index] is not None and squares[index] == squares[index - 1]:
            squares[index - 1] = None

    # The last look is the longest: that is the one he is committing during.
    weights = [1.0] * (count - 1) + [1.6]
    total = delay * rng.uniform(*HOVER_FILL)
    scale = total / sum(weights)
    steps = [
        HoverStep(square=square, dwell=round(max(MIN_DWELL, weight * scale), 2))
        for square, weight in zip(squares, weights)
    ]

    # Rounding and the dwell floor can both push the script past the pause it is
    # supposed to fit inside. Trim from the last step, which has the most to give.
    overflow = round(sum(step.dwell for step in steps) - delay, 2)
    if overflow > 0:
        trimmed = max(MIN_DWELL, round(steps[-1].dwell - overflow, 2))
        steps[-1] = HoverStep(square=steps[-1].square, dwell=trimmed)
    return steps


def think_plan(
    board: chess.Board,
    choice: "MoveChoice",
    *,
    rng: random.Random,
) -> ThinkPlan:
    """
    How long he takes over this move, and where the claw goes while he takes it.

    `board` is the position before the move — the same one `choice` was picked
    in — because everything here is read off the position he is looking at, not
    the one he leaves behind.
    """
    delay = _delay(board, choice, rng=rng)
    return ThinkPlan(delay=delay, hovers=_hovers(board, choice, delay, rng=rng))
