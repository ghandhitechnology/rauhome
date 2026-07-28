"""
The position, the rules, and what survives a restart.

This is the only module allowed to move a piece. Everything else either reads a
snapshot of it or hands it two squares and finds out. That matters more here than
it does in `kittens/engine.py`, because two threads are always looking at this
object: the HTTP handler carrying the user's move, and the pump carrying Rau's.
Every public method takes the game's own lock, and `board_copy()` exists so that
the one long-running reader — Stockfish, which sits on a position for as much as
a second — never analyses the same `chess.Board` somebody else is about to push
onto.

## Why the saved game is a move list and not just a FEN

A FEN is not the position. It is the position minus its history, and chess has
two rules that live entirely in the history: threefold repetition and the
fifty-move counter's claim. Restore from a FEN alone and a game that was one
shuffle away from a claimable draw comes back unable to claim it, silently, with
nothing in the UI to say why. So `chess_current.json` carries the SAN list and
`resume()` replays it from the start; the FEN is kept alongside as a check, and
is only used as the position when the replay disagrees with it.

## The refusal strings are dialogue

When the user's move is refused, `session.py` hands the message straight to
`player.table_talk` and Rau says it out loud. So they are written as a person
talking across a table, lowercase, no jargon — "there's nothing on e4", not
"origin square is empty". A code goes with each one for the client; the sentence
is for the room.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn

RAU = "rau"
USER = "user"

PHASE_PLAYING = "playing"
PHASE_THINKING = "thinking"
PHASE_OVER = "over"

WHITE = "white"
BLACK = "black"

#: Where the position is parked between processes, and where finished games pile
#: up. Both live under `memories/games/`.
CURRENT_NAME = "chess_current.json"
PGN_NAME = "chess.pgn"

#: How much of the running commentary the wire carries. The full journal is a
#: separate buffer with its own budget; this is the feed beside the board.
LOG_KEEP = 40

_PROMOTIONS: Dict[str, int] = {
    "q": chess.QUEEN,
    "r": chess.ROOK,
    "b": chess.BISHOP,
    "n": chess.KNIGHT,
}

#: The contract fixes this vocabulary, and it has no separate word for the
#: variants the arbiter enforces without anyone claiming. Seventy-five moves is
#: the fifty-move rule going off by itself and fivefold is threefold going off by
#: itself; nobody at the table cares which counter tripped, only that the game is
#: a draw and why.
_REASONS: Dict[chess.Termination, str] = {
    chess.Termination.CHECKMATE: "checkmate",
    chess.Termination.STALEMATE: "stalemate",
    chess.Termination.INSUFFICIENT_MATERIAL: "insufficient material",
    chess.Termination.SEVENTYFIVE_MOVES: "fifty-move rule",
    chess.Termination.FIVEFOLD_REPETITION: "threefold repetition",
    chess.Termination.FIFTY_MOVES: "fifty-move rule",
    chess.Termination.THREEFOLD_REPETITION: "threefold repetition",
}


class IllegalMove(Exception):
    """A move the rules do not allow. Carries a code and a line to say out loud."""

    def __init__(self, message: str, code: str = "illegal_move") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Entry:
    """One line of what happened, for the feed beside the board."""

    seat: str
    text: str
    at: float


def _other(seat: str) -> str:
    return USER if seat == RAU else RAU


class ChessGame:
    """One board, one position, one lock around both."""

    def __init__(
        self,
        *,
        rau_color: str = BLACK,
        elo: int = 1500,
        game_id: Optional[str] = None,
        started_at: Optional[float] = None,
    ) -> None:
        colour = str(rau_color or BLACK).strip().lower()
        if colour not in (WHITE, BLACK):
            colour = BLACK

        self._lock = threading.RLock()
        self.game_id: str = game_id or f"c-{uuid.uuid4().hex[:10]}"
        self.board = chess.Board()
        self.rau_color: str = colour
        self.user_color: str = BLACK if colour == WHITE else WHITE
        self.elo = int(elo)
        self.started_at: float = float(started_at if started_at is not None else time.time())

        self.moves: List[str] = []
        self.last_move: Optional[Dict[str, str]] = None
        self.offer: Optional[Dict[str, str]] = None

        self.result: Optional[str] = None
        self.winner: Optional[str] = None
        self.over_reason: str = ""

        self.log: List[Entry] = []

        #: `can_claim_threefold_repetition` replays the whole move stack, and the
        #: wire view asks for it on a hundred-millisecond heartbeat while the claw
        #: is moving. The answer cannot change without a push, so it is cached
        #: against the ply it was computed at.
        self._claim: Tuple[int, bool] = (-1, False)

        self._note(
            USER if self.user_color == WHITE else RAU,
            "Pieces are set. White to open.",
        )

    # ------------------------------------------------------------------ reading

    @property
    def phase(self) -> str:
        """Only ever playing or over.

        `thinking` is theatre — it belongs to whichever thread is running the
        hover script, and `player.py` owns it. Keeping it off the position means a
        game restored from disk cannot come back mid-stare.
        """
        with self._lock:
            return PHASE_OVER if self.result is not None else PHASE_PLAYING

    def seat_color(self, seat: str) -> str:
        return self.rau_color if seat == RAU else self.user_color

    def turn_seat(self) -> str:
        with self._lock:
            turn = WHITE if self.board.turn == chess.WHITE else BLACK
            return RAU if turn == self.rau_color else USER

    def check_square(self) -> Optional[str]:
        """Where the king under check is standing, for the square the UI lights."""
        with self._lock:
            if not self.board.is_check():
                return None
            square = self.board.king(self.board.turn)
            return chess.square_name(square) if square is not None else None

    def can_claim_draw(self) -> bool:
        """Threefold or fifty moves, available but not forced. The client shows a button."""
        with self._lock:
            if self.result is not None:
                return False
            ply = len(self.board.move_stack)
            at, answer = self._claim
            if at == ply:
                return answer
            answer = (
                self.board.can_claim_threefold_repetition()
                or self.board.can_claim_fifty_moves()
            )
            self._claim = (ply, answer)
            return answer

    def board_copy(self) -> chess.Board:
        """A position nobody else is holding. The only thing the engine may analyse."""
        with self._lock:
            return self.board.copy()

    # ------------------------------------------------------------------- moving

    def play(
        self,
        seat: str,
        from_sq: str,
        to_sq: str,
        promotion: Optional[str] = None,
    ) -> str:
        """
        Push one move and return its SAN. Raises `IllegalMove` and changes nothing.

        Rau's move comes through this door too. Stockfish hands `player.py` a
        `chess.Move`, which is taken apart into two square names and put back
        together here, so there is exactly one piece of code in the process that
        decides whether something is a legal move.
        """
        with self._lock:
            self._require_turn(seat)
            move = self._parse(from_sq, to_sq, promotion)
            san = self.board.san(move)
            self.board.push(move)
            self.moves.append(san)
            self.last_move = {
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
                "san": san,
            }
            # A move answers an outstanding offer by ignoring it, which is how it
            # works over a real board — but only the *opponent's* offer. Your own
            # offer is made and then you move; that is the normal order at a real
            # board, and clearing it here meant an offer made on your own turn
            # evaporated before the other player ever saw it.
            if self.offer and self.offer.get("by") != seat:
                self.offer = None
            self._note(seat, san)
            self._settle()
            return san

    def resign(self, seat: str) -> None:
        with self._lock:
            self._require_live()
            self._end(_other(seat), "resignation")
            self._note(seat, "Resigned.")

    def offer_draw(self, seat: str) -> None:
        with self._lock:
            self._require_live()
            if self.offer and self.offer.get("by") == _other(seat):
                # They offered, and now you are offering back. That is agreement,
                # and refusing it here would leave two people both waiting.
                self._end(None, "draw agreed")
                self._note(seat, "Draw agreed.")
                return
            self.offer = {"by": seat, "kind": "draw"}
            self._note(seat, "Offered a draw.")

    def accept_draw(self, seat: str) -> None:
        with self._lock:
            self._require_live()
            if not self.offer or self.offer.get("by") != _other(seat):
                raise IllegalMove("i haven't offered anything", "no_offer")
            self._end(None, "draw agreed")
            self._note(seat, "Took the draw.")

    def decline_draw(self, seat: str) -> None:
        with self._lock:
            self._require_live()
            if not self.offer or self.offer.get("by") != _other(seat):
                raise IllegalMove("i haven't offered anything", "no_offer")
            self.offer = None
            self._note(seat, "Waved the draw off.")

    def claim_draw(self, seat: str) -> None:
        with self._lock:
            self._require_live()
            if self.board.can_claim_threefold_repetition():
                reason = "threefold repetition"
            elif self.board.can_claim_fifty_moves():
                reason = "fifty-move rule"
            else:
                raise IllegalMove("nothing to claim yet", "no_offer")
            self._end(None, reason)
            self._note(seat, f"Claimed the draw: {reason}.")

    # ------------------------------------------------------------------ private

    def _note(self, seat: str, text: str) -> None:
        self.log.append(Entry(seat=seat, text=text, at=time.time()))
        del self.log[:-LOG_KEEP]

    def _require_live(self) -> None:
        if self.result is not None:
            raise IllegalMove("that one's done", "no_game")

    def _require_turn(self, seat: str) -> None:
        self._require_live()
        if self.turn_seat() != seat:
            raise IllegalMove("it's my move", "not_your_turn")

    def _parse(
        self, from_sq: str, to_sq: str, promotion: Optional[str]
    ) -> chess.Move:
        """Two square names into a move, or the reason it is not one."""
        try:
            origin = chess.parse_square(str(from_sq).strip().lower())
            target = chess.parse_square(str(to_sq).strip().lower())
        except (ValueError, AttributeError):
            raise IllegalMove(
                "that isn't a square on this board", "bad_square"
            ) from None

        piece = self.board.piece_at(origin)
        if piece is None:
            raise IllegalMove(f"there's nothing on {chess.square_name(origin)}", "bad_square")
        if piece.color != self.board.turn:
            raise IllegalMove("wrong colour, that one's mine", "illegal_move")

        promo: Optional[int] = None
        if piece.piece_type == chess.PAWN and chess.square_rank(target) in (0, 7):
            # The client only asks about promotion when the user wants something
            # other than a queen, so an absent one is a queen rather than a refusal.
            promo = _PROMOTIONS.get(str(promotion or "q").strip().lower(), chess.QUEEN)

        move = chess.Move(origin, target, promotion=promo)
        if move in self.board.legal_moves:
            return move

        if move in self.board.pseudo_legal_moves and self.board.is_into_check(move):
            raise IllegalMove("can't — that leaves your king in check", "illegal_move")
        if self.board.is_check():
            raise IllegalMove("you're in check, you have to deal with that", "illegal_move")
        raise IllegalMove("can't — that one doesn't go there", "illegal_move")

    def _settle(self) -> None:
        """Whether that move ended it. Claimable draws are not ends; they are offers."""
        outcome = self.board.outcome(claim_draw=False)
        if outcome is None:
            return
        reason = _REASONS.get(outcome.termination, "the game is over")
        if outcome.winner is None:
            self._end(None, reason)
            return
        won = WHITE if outcome.winner == chess.WHITE else BLACK
        self._end(RAU if won == self.rau_color else USER, reason)

    def _end(self, winner: Optional[str], reason: str) -> None:
        """Result is derived from the winner and his colour, never stored twice."""
        self.winner = winner
        self.over_reason = reason
        self.offer = None
        if winner is None:
            self.result = "1/2-1/2"
        else:
            white_won = self.seat_color(winner) == WHITE
            self.result = "1-0" if white_won else "0-1"

    # -------------------------------------------------------------- persistence

    def save(self) -> None:
        save(self)

    def pgn(self) -> str:
        """The finished game as text, headers and all, generated by the library."""
        with self._lock:
            game = chess.pgn.Game.from_board(self.board)
            game.headers["Event"] = "Chess at Rau's table"
            game.headers["Site"] = "Rau"
            game.headers["Date"] = time.strftime("%Y.%m.%d", time.localtime(self.started_at))
            game.headers["Round"] = "-"
            game.headers["White"] = "Rau" if self.rau_color == WHITE else "Them"
            game.headers["Black"] = "Them" if self.rau_color == WHITE else "Rau"
            # A resignation or an agreed draw is not visible in the move list, so
            # the header has to carry it or the file lies about how it ended.
            game.headers["Result"] = self.result or "*"
            game.headers["Termination"] = self.over_reason or "unfinished"
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        return game.accept(exporter)

    def snapshot(self) -> Dict[str, Any]:
        """
        Everything on the wire that is true about the position.

        `thinking` and `log` are deliberately absent: the first belongs to
        whoever is performing the pause and the second is a feed rather than a
        fact. `view.browser_view` merges both on top of this.
        """
        with self._lock:
            return {
                "game_id": self.game_id,
                "phase": self.phase,
                "fen": self.board.fen(),
                "turn": WHITE if self.board.turn == chess.WHITE else BLACK,
                "rau_color": self.rau_color,
                "user_color": self.user_color,
                "your_turn": self.turn_seat() == USER and self.phase == PHASE_PLAYING,
                "moves": list(self.moves),
                "last_move": dict(self.last_move) if self.last_move else None,
                "check_square": self.check_square(),
                "offer": dict(self.offer) if self.offer else None,
                "result": self.result,
                "winner": self.winner,
                "over_reason": self.over_reason,
                "can_claim_draw": self.can_claim_draw(),
            }


# ------------------------------------------------------------------ on disk


def _games_dir():
    from rau.paths import GAMES_DIR

    return GAMES_DIR


def current_path():
    return _games_dir() / CURRENT_NAME


def pgn_path():
    return _games_dir() / PGN_NAME


def save(game: ChessGame) -> None:
    """
    Park the position, atomically, after every move.

    Broad `except` on purpose, and the same call `kittens/session.py` makes about
    its tally: a game that keeps going and loses its autosave is better than one
    that stops because the disk did. The cost of being wrong is a restart landing
    on the previous move.
    """
    with game._lock:  # noqa: SLF001 — persistence is part of this module
        data = {
            "fen": game.board.fen(),
            "moves": list(game.moves),
            "rau_color": game.rau_color,
            "started_at": game.started_at,
            "elo": game.elo,
            "game_id": game.game_id,
        }
    try:
        directory = _games_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / CURRENT_NAME
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(target)
    except Exception:
        pass


def resume() -> Optional[ChessGame]:
    """
    The game that was on the table when the process stopped, or None.

    The move list is replayed from the standard start rather than the FEN being
    loaded, because the repetition and fifty-move history live in the stack and a
    FEN throws both away. The stored FEN is the check on that replay: if the two
    disagree — a hand-edited file, a version of this code that numbered something
    differently — the FEN wins, because it is what was actually on the board.

    **Never raises.** Every failure is the same answer: there is no game to come
    back to. This runs on the boot path and on the first press of play, and a
    file half-written when the machine lost power is a normal thing to find on a
    disk — it must cost you a resumed game, not the ability to start one.
    """
    try:
        return _rebuild()
    except Exception:
        # Deliberately broad. Truncated JSON, a FEN with seven ranks, an elo
        # someone typed a word into — they fail in different places and all mean
        # the same thing here. The unreadable file goes, so the next boot is not
        # the same disappointment.
        discard_saved()
        return None


def _rebuild() -> Optional[ChessGame]:
    """The body of `resume`, which is allowed to throw so `resume` cannot."""
    path = current_path()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None

    game = ChessGame(
        rau_color=str(data.get("rau_color") or BLACK),
        elo=int(data.get("elo") or 1500),
        game_id=str(data.get("game_id") or "") or None,
        started_at=float(data.get("started_at") or 0.0) or None,
    )
    game.log.clear()

    moves = [str(m) for m in (data.get("moves") or [])]
    fen = str(data.get("fen") or "")
    try:
        for san in moves:
            move = game.board.parse_san(san)
            game.board.push(move)
            game.moves.append(san)
            game.last_move = {
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
                "san": san,
            }
    except ValueError:
        game.moves = list(moves)
        game.last_move = None
        game.board = chess.Board(fen) if fen else chess.Board()
    else:
        if fen and game.board.fen() != fen:
            game.board = chess.Board(fen)
            game.last_move = None

    game._settle()  # noqa: SLF001 — a position saved on its last move is already over
    if game.result is not None:
        # Nothing to come back to. Leaving the file would make it come back again
        # on the next boot, so it goes.
        discard_saved()
        return None
    game._note("table", "Position restored.")  # noqa: SLF001
    return game


def discard_saved() -> None:
    """No game is on the table. Nothing should be picked up on the next boot."""
    try:
        current_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def append_pgn(game: ChessGame) -> None:
    """Add a finished game to the pile. Appended, never rewritten."""
    try:
        directory = _games_dir()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / PGN_NAME).open("a", encoding="utf-8") as handle:
            handle.write(game.pgn().rstrip() + "\n\n")
    except Exception:
        # Same call as `save`: the record of the game is worth less than the
        # process that just finished playing it.
        pass


__all__ = [
    "BLACK",
    "PHASE_OVER",
    "PHASE_PLAYING",
    "PHASE_THINKING",
    "RAU",
    "USER",
    "WHITE",
    "ChessGame",
    "Entry",
    "IllegalMove",
    "append_pgn",
    "current_path",
    "discard_saved",
    "pgn_path",
    "resume",
    "save",
]
