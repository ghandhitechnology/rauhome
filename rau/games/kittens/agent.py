"""
Compatibility shim — Nope decisions and turn-taking live in `player.py` now.
"""
from __future__ import annotations

from rau.games.kittens.player import (  # noqa: F401
    DECIDE_TIMEOUT_SEC,
    REFLEX_NOPE,
    decide_nope,
    take_turn,
)
