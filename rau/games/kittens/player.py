"""
Rau's player half — the one that actually plays the cards.

Separated from the face talker on purpose. A full conversational turn is too
slow and too distractible for a five-second Nope window or a turn that must
always end in a legal move. This module:

* decides Nope on the cheap `player` slot with a hard deadline
* takes ordinary turns as a compact JSON call: pick a legal move, say one line
* always advances the table — illegal answers retry once, then a guaranteed
  fallback (the last legal move) fires so the pump can never stall forever

His voice across the table is delivered as ordinary chat events so the Face
bubble and desktop TTS keep working without sharing the face tool loop.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from rau.events import BUS
from rau.games.kittens import deck as deck_mod
from rau.games.kittens import journal
from rau.games.kittens import view as view_mod
from rau.games.kittens.deck import ATTACK, FAVOR, NOPE
from rau.games.kittens.engine import RAU, USER, Game

#: Wall-clock budget for a Nope decision. Inside the Nope window, with room to
#: broadcast before it closes.
DECIDE_TIMEOUT_SEC = 1.2

#: Cards worth burning a Nope on when the model does not answer in time.
REFLEX_NOPE = frozenset({ATTACK, FAVOR})

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{[^{}]*\"move\"[^{}]*\}", re.DOTALL)


# ------------------------------------------------------------------- speech


def table_talk(text: str) -> None:
    """One short line across the table — bubble, log, and desktop speak."""
    line = str(text or "").strip()
    if not line:
        return
    from rau.face import choreography
    from rau import state as runtime_state

    turn_id = choreography.new_turn_id()
    journal.record("rau", "table_talk", line)
    runtime_state.add_log("rau", line, turn_id)
    BUS.emit("chat_started", turn_id=turn_id, text="")
    BUS.emit("chat_done", turn_id=turn_id, text=line)
    runtime_state.push_control({"action": "speak", "text": line})


# -------------------------------------------------------------------- nope


def _nope_prompt(game: Game) -> str:
    pending = game.pending
    assert pending is not None
    played = ", ".join(deck_mod.label(c) for c in pending.cards)
    mine = pending.actor == RAU
    stacked = (
        f" There are already {pending.nopes} Nopes on it, so right now it "
        f"{'will not' if pending.cancelled else 'will'} happen."
        if pending.nopes
        else ""
    )
    return (
        "You are playing Exploding Kittens. "
        f"{'You' if mine else 'Your opponent'} played {played}.{stacked}\n"
        f"Your hand: {', '.join(deck_mod.label(c) for c in game.hands[RAU])}.\n"
        f"They hold {len(game.hands[USER])} cards. "
        f"{len(game.draw)} cards left in the deck, one of them the kitten.\n\n"
        "Do you play a Nope to cancel it? Answer with exactly one word: "
        "NOPE or PASS. Nothing else."
    )


def _reflex(game: Game) -> bool:
    pending = game.pending
    if not pending or pending.actor == RAU:
        return False
    return any(card in REFLEX_NOPE for card in pending.cards)


def decide_nope(game: Game) -> bool:
    """
    Should Rau Nope what is on the table? Blocks for at most `DECIDE_TIMEOUT_SEC`.

    Returns the decision only; the caller applies it.
    """
    with game._lock:  # noqa: SLF001 — the snapshot must not straddle a move
        pending = game.pending
        if not pending or pending.waiting_on() != RAU:
            return False
        if NOPE not in game.hands[RAU]:
            return False
        prompt = _nope_prompt(game)
        fallback = _reflex(game)

    answer: list = []

    def ask() -> None:
        try:
            from rau.providers.base import Message
            from rau.providers.registry import chat_for_slot

            provider, slot = chat_for_slot("player")
            result = provider.chat(
                [Message(role="user", content=prompt)],
                model=slot.get("model") or "deepseek-v4-pro",
                max_tokens=8,
                temperature=0.4,
            )
            answer.append(str(result.content or "").strip().upper())
        except Exception:
            pass

    worker = threading.Thread(target=ask, name="kittens-nope", daemon=True)
    worker.start()
    worker.join(DECIDE_TIMEOUT_SEC)

    if not answer:
        return fallback
    said = answer[0]
    if "NOPE" in said:
        return True
    if "PASS" in said:
        return False
    return fallback


# -------------------------------------------------------------- turn taking


def _turn_prompt(game: Game, *, correction: str = "") -> str:
    table = view_mod.prompt_fragment(game, RAU)
    history = journal.tail()
    parts = [
        "You are Rau's player half in Exploding Kittens. Pick exactly one legal "
        "move and say one short line across the table. Play to win.",
        "",
        table.strip(),
    ]
    if history:
        parts.extend(["", history.strip()])
    parts.extend(
        [
            "",
            "Reply with ONLY a JSON object, no markdown fences, shaped like:",
            '{"move": {"move": "draw"}, "say": "alright, drawing."}',
            "The move object must match one of the legal moves listed above "
            "(same keys and values). Keep say to one short spoken line.",
        ]
    )
    if correction:
        parts.extend(["", correction.strip()])
    return "\n".join(parts)


def parse_turn_reply(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Pull `{move, say}` out of a model reply. Tolerates fences and trailing prose.
    Returns `(move_dict_or_None, say)`.
    """
    raw = str(text or "").strip()
    if not raw:
        return None, ""

    candidates: List[str] = [raw]
    fenced = _JSON_FENCE.search(raw)
    if fenced:
        candidates.insert(0, fenced.group(1))
    matched = _JSON_OBJECT.search(raw)
    if matched:
        candidates.insert(0, matched.group(0))

    # Prefer the longest brace-balanced slice starting at the first '{'.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.insert(0, raw[start : end + 1])

    for blob in candidates:
        try:
            data = json.loads(blob)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        move = data.get("move")
        say = str(data.get("say") or "").strip()
        if isinstance(move, dict) and move.get("move"):
            cleaned = {k: v for k, v in move.items() if v is not None}
            return cleaned, say
    return None, ""


def _ask_model(prompt: str) -> str:
    from rau.providers.base import Message
    from rau.providers.registry import chat_for_slot

    provider, slot = chat_for_slot("player")
    result = provider.chat(
        [Message(role="user", content=prompt)],
        model=slot.get("model") or "deepseek-v4-pro",
        max_tokens=int(slot.get("max_tokens") or 400),
        temperature=float(slot.get("temperature") if slot.get("temperature") is not None else 0.6),
    )
    return str(result.content or "")


def _fallback_move(game: Game) -> Dict[str, Any]:
    """
    The move that always exists when he must act: the last legal option.

    Engine lists draw / blocking answers last, so taking the last entry is the
    safe default that advances the table.
    """
    moves = game.legal_moves(RAU)
    if not moves:
        return {"move": "concede"}
    chosen = dict(moves[-1])
    # The two open-choice moves are listed with prose placeholders ("0..N",
    # "<any card…>"), which the engine refuses verbatim — fill them with real
    # values or the guaranteed move is guaranteed to fail.
    if chosen.get("move") == "combo" and "named_card" in chosen:
        if chosen["named_card"] not in deck_mod.ALL_CARDS:
            chosen["named_card"] = "skip"
    if chosen.get("move") == "insert_kitten" and not isinstance(chosen.get("index"), int):
        chosen["index"] = 0
    if chosen.get("move") == "give_favor" and "card" not in chosen and game.hands[RAU]:
        chosen["card"] = game.hands[RAU][0]
    if chosen.get("move") == "take_from_discard" and "card" not in chosen and game.discard:
        chosen["card"] = game.discard[-1]
    return chosen


def _describe_move(move: Dict[str, Any]) -> str:
    kind = str(move.get("move") or "")
    if kind == "play":
        return f"played {deck_mod.label(str(move.get('card') or ''))}"
    if kind == "combo":
        cards = move.get("cards") or []
        return f"played a set of {len(cards)}"
    if kind == "draw":
        return "drew"
    if kind == "nope":
        return "noped"
    if kind == "pass_nope":
        return "let it stand"
    if kind == "give_favor":
        return f"gave {deck_mod.label(str(move.get('card') or ''))}"
    if kind == "take_from_discard":
        return f"took {deck_mod.label(str(move.get('card') or ''))} from discard"
    if kind == "insert_kitten":
        return f"put the kitten back at {move.get('index', 0)}"
    if kind == "concede":
        return "conceded"
    return kind or "moved"


def take_turn(game: Game) -> None:
    """
    Make exactly one legal move for Rau, and optionally say a line.

    Never returns without advancing when a legal move exists. On model failure
    the last legal move is applied as a guaranteed fallback.
    """
    from rau.games.kittens import session

    if not game.legal_moves(RAU):
        return

    move: Optional[Dict[str, Any]] = None
    say = ""
    correction = ""

    for _attempt in range(2):
        try:
            raw = _ask_model(_turn_prompt(game, correction=correction))
        except Exception as exc:
            BUS.emit("game_error", game="kittens", error=f"player: {exc}")
            break
        parsed, say = parse_turn_reply(raw)
        if not parsed:
            correction = (
                "That was not valid JSON. Reply with only "
                '{"move": {…}, "say": "…"}.'
            )
            continue
        result = session.apply_move(RAU, parsed)
        if result.get("ok"):
            move = parsed
            break
        err = result.get("error") or "illegal move"
        legal = result.get("legal_moves") or game.legal_moves(RAU)
        correction = (
            f"Illegal: {err}. Pick exactly one of these moves:\n"
            + "\n".join(f"- {json.dumps(m)}" for m in legal)
        )

    if move is None:
        move = _fallback_move(game)
        say = say or ""
        result = session.apply_move(RAU, move)
        if not result.get("ok"):
            BUS.emit(
                "game_error",
                game="kittens",
                error=f"fallback failed: {result.get('error')}",
            )
            return

    journal.record("rau", "move", _describe_move(move))
    if say:
        table_talk(say)
