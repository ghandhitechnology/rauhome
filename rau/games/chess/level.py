"""
How hard he plays, and why it moves the way it does.

An opponent with a fixed strength is a wall or a pushover, and which one it is
gets decided in the first twenty minutes and never revisited. So the elo handed
to `engine.py` follows the score between the two of you.

**The direction is the counterintuitive part, and it is not a bug: beating him
makes him stronger.** He is not rewarding you for winning and he is not sulking
when he loses. He is keeping the game close, which means the number moves against
whoever has been winning. Lose three in a row and he quietly eases off; take a
game off him and he sits up.

None of this is ever shown. There is no rating in the UI, he never mentions a
number at the table, and the adjustment happens between games where you cannot
watch it happen. If you can see the handicap it stops being a game and starts
being a difficulty slider.

The band is also allowed to forget. Ten points a week of drift back toward the
middle means a run of losses from six months ago does not still be shaping the
first game after a long gap — you are a different player by then, and so is the
version of him you remember.

Storage is `memories/games.json`, shared with kittens, so every write here is a
read-modify-write of the whole document. `kittens/session.py` used to write
`{"kittens": …}` over the top of the file; doing the same thing from this side
would erase the kittens record on every finished chess game.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

USER = "user"
RAU = "rau"

#: Where a fresh opponent starts. Club-ish: loses to a real player, punishes a
#: careless one.
START = 1500

#: The agreed band was 1100–1900. 1100 is not reachable: the Stockfish on this
#: machine reports `UCI_Elo` as `spin min 1320 max 3190` — checked against the
#: binary, not against the docs — and asking for less is refused. The
#: obvious workaround — dropping `Skill Level` instead — is worse than the
#: problem, because the two knobs interact and the resulting strength stops
#: being predictable from either number. So the floor moved to the real one.
FLOOR = 1320
CEIL = 1900

#: Per decisive game. Three losses in a row is a visibly different opponent,
#: which is the point; any smaller and the adaptation is invisible for a month.
DECISIVE = 60

#: A draw barely tells you anything, so it only nudges — and it nudges toward
#: the middle, since a drawn game is roughly a matched one.
DRAW_PULL = 15

#: Points per week of not playing, back toward START.
DRIFT_PER_WEEK = 10.0
WEEK_SEC = 7 * 24 * 3600.0

_lock = threading.RLock()


def _clamp(elo: float) -> int:
    return int(round(max(FLOOR, min(CEIL, elo))))


def _toward(elo: float, target: float, amount: float) -> float:
    """Move `amount` toward `target`, never past it."""
    if elo < target:
        return min(target, elo + amount)
    return max(target, elo - amount)


def _read_all() -> Dict[str, Any]:
    """The whole games document, which belongs to more than one game."""
    try:
        from rau.paths import GAMES_FILE

        if not GAMES_FILE.exists():
            return {}
        data = json.loads(GAMES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_chess(record: Dict[str, Any]) -> None:
    """
    Replace only the `chess` key, atomically.

    Read-modify-write, not write: the same file holds the kittens tally, and the
    two games finish at unrelated times.
    """
    try:
        from rau.paths import GAMES_FILE

        data = _read_all()
        data["chess"] = record
        GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = GAMES_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(GAMES_FILE)
    except Exception:
        # A game that was played and unrecorded still beats one that crashed on
        # the way to the scoreboard.
        pass


def _drifted(record: Dict[str, Any], now: float) -> float:
    """Stored elo with idle drift applied, without writing anything back."""
    try:
        elo = float(record.get("elo", START))
    except (TypeError, ValueError):
        return float(START)
    try:
        last = float(record.get("last_played") or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0.0:
        return elo
    weeks = max(0.0, (now - last) / WEEK_SEC)
    return _toward(elo, float(START), weeks * DRIFT_PER_WEEK)


def tally() -> Dict[str, Any]:
    """The running chess record, for the model and for whoever asks."""
    with _lock:
        return _read_all().get("chess") or {}


def current(now: Optional[float] = None) -> int:
    """
    The elo to open the next game at.

    Reads only. Drift is a function of elapsed time, so computing it on the way
    out is honest and saves a write on a path that is asked every game.
    """
    with _lock:
        record = _read_all().get("chess") or {}
        return _clamp(_drifted(record, now if now is not None else time.time()))


def last_color() -> Optional[str]:
    """
    Which side Rau took in the last *finished* game, or None before any.

    This is what colour alternation runs on. Finished games only, on purpose: a
    board that was set up and abandoned was not a game, and letting it flip the
    colours would mean leaving and coming back changes which side of the table
    you sit on.
    """
    with _lock:
        colour = (_read_all().get("chess") or {}).get("last_rau_color")
        return colour if colour in ("white", "black") else None


def record_result(
    winner: Optional[str],
    now: Optional[float] = None,
    *,
    rau_color: Optional[str] = None,
) -> int:
    """
    Fold one finished game into the band. `winner` is USER, RAU, or None.

    Returns the new elo. Drift is settled first, so a game after a long gap is
    scored against the softened number rather than the one from months ago.
    `rau_color` is remembered so the next game can hand him the other side.
    """
    with _lock:
        now = now if now is not None else time.time()
        data = _read_all()
        record = dict(data.get("chess") or {})
        elo = _drifted(record, now)

        if winner == USER:
            elo += DECISIVE
        elif winner == RAU:
            elo -= DECISIVE
        else:
            elo = _toward(elo, float(START), float(DRAW_PULL))

        record["wins"] = int(record.get("wins", 0)) + (1 if winner == RAU else 0)
        record["losses"] = int(record.get("losses", 0)) + (1 if winner == USER else 0)
        record["draws"] = int(record.get("draws", 0)) + (1 if winner is None else 0)
        record["elo"] = _clamp(elo)
        record["last_played"] = now
        if rau_color in ("white", "black"):
            record["last_rau_color"] = rau_color
        _write_chess(record)
        return int(record["elo"])
