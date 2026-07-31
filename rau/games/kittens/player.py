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
import random
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rau.events import BUS
from rau.games.kittens import deck as deck_mod
from rau.games.kittens import journal
from rau.games.kittens import view as view_mod
from rau.games.kittens.deck import (
    ATTACK,
    EXPLODING_KITTEN,
    FAVOR,
    NOPE,
    SEE_THE_FUTURE,
    SHUFFLE,
    SKIP,
)
from rau.games.kittens.engine import RAU, USER, Game

#: Wall-clock budget for a Nope decision. Inside the Nope window, with room to
#: broadcast before it closes.
DECIDE_TIMEOUT_SEC = 1.2

#: Cards worth burning a Nope on when the model does not answer in time.
REFLEX_NOPE = frozenset({ATTACK, FAVOR})

#: Default sampling temperature for a turn, when the slot does not name one.
#:
#: One call produces both the move and the line he says, so this number is a
#: compromise between two jobs. It used to be 0.6, tuned purely for the move.
#: Now that he speaks on every single move, twenty turns at 0.6 is twenty
#: rewordings of the same sentence, so it sits nearer the 0.95 `banter` uses
#: for exactly that reason. Move quality is protected by validation rather than
#: by temperature: an illegal answer is rejected, corrected, retried, and
#: finally replaced by a guaranteed legal fallback.
TEMPERATURE = 0.8

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT = re.compile(r"\{[^{}]*\"move\"[^{}]*\}", re.DOTALL)


# ------------------------------------------------------------------- speech

#: What he says when the model gave him a move but no line, or gave him nothing
#: at all and the fallback move fired. He speaks on every move now, so silence
#: here would be the same bug in a smaller window.
#:
#: These are deliberately flat rather than funny. This is the path that runs
#: when something is already broken, which means it can run many turns in a
#: row, and a canned punchline delivered five times is worse than no punchline
#: at all. The jokes are the model's job; this is just him not going mute.
TABLE_LINES: Dict[str, Tuple[str, ...]] = {
    "draw": ("drawing.", "let's see.", "one off the top.", "my turn — drawing."),
    "play": ("there.", "that one.", "playing this.", "here we go."),
    "combo": ("taking one of yours.", "that's a set.", "i'll have one of those."),
    "nope": ("no.", "nope.", "not that one."),
    "pass_nope": ("go on then.", "that one stands.", "fine, let it happen."),
    "give_favor": ("here, take it.", "all yours.", "if you insist."),
    "take_from_discard": ("i'll take that back.", "that's useful again."),
    "insert_kitten": ("back it goes.", "somewhere in there.", "good luck with that."),
    "concede": ("alright, you have it.", "that's me done."),
}

TABLE_LINES_KO: Dict[str, Tuple[str, ...]] = {
    "draw": ("한 장 뽑을게.", "어디 보자.", "맨 위로 한 장.", "내 차례 — 뽑는다."),
    "play": ("자.", "이걸로.", "이거 낼게.", "간다."),
    "combo": ("네 카드 하나 가져간다.", "세트야.", "하나 받아갈게."),
    "nope": ("아니.", "노프.", "그건 안 돼."),
    "pass_nope": ("그래, 해봐.", "그건 그냥 두자.", "좋아, 통과."),
    "give_favor": ("자, 가져가.", "네 거야.", "정 그렇다면."),
    "take_from_discard": ("이건 다시 가져갈게.", "또 쓸 만하네."),
    "insert_kitten": ("도로 넣는다.", "이 근처 어딘가에.", "잘 해봐."),
    "concede": ("좋아, 네가 이겼어.", "난 여기까지."),
}

#: A line for a move kind we have not named. Never leaves him silent.
_GENERIC_LINES: Tuple[str, ...] = ("your turn.", "over to you.", "go on.")
_GENERIC_LINES_KO: Tuple[str, ...] = ("네 차례.", "이제 너야.", "해봐.")

_rng = random.Random()
_speech_lock = threading.RLock()

#: When he last said anything out loud. `banter` reads this so a proactive line
#: never lands on top of the line that came with his move.
_spoke_at: float = 0.0


def table_line(kind: str) -> str:
    """One canned line for a move kind. Never empty."""
    from rau.language import get_locale

    korean = get_locale() == "ko"
    source = TABLE_LINES_KO if korean else TABLE_LINES
    lines = source.get(kind) or (_GENERIC_LINES_KO if korean else _GENERIC_LINES)
    return _rng.choice(lines)


def last_spoke() -> float:
    """Monotonic stamp of his last spoken line. 0.0 before he has said anything."""
    with _speech_lock:
        return _spoke_at


def reset_speech() -> None:
    """Fresh hand: he has not said anything yet."""
    global _spoke_at
    with _speech_lock:
        _spoke_at = 0.0


def table_talk(text: str) -> None:
    """One short line across the table — bubble, log, and desktop speak."""
    global _spoke_at
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
    with _speech_lock:
        _spoke_at = time.monotonic()


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
                # An eight token budget cannot survive a thinking block, and
                # omitting `effort` is not neutral: the catalog default for
                # DeepSeek is "high", so the reply came back empty every time
                # and every Nope decision fell through to the reflex.
                effort="minimal",
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
    from rau.games.kittens import vibe as vibe_mod
    from rau.language import response_language_instruction

    table = view_mod.prompt_fragment(game, RAU)
    history = journal.tail()
    example_move = (
        _preferred_proactive_move(game, allow_interactive=True)
        or _fallback_move(game)
    )
    parts = [
        "You are Rau's player half in Exploding Kittens. Pick exactly one legal "
        "move and say one short line across the table. Play to win. Do not default "
        "to drawing: use a useful action before drawing when one is available.",
        response_language_instruction(),
        "",
        table.strip(),
    ]
    if history:
        parts.extend(["", history.strip()])
    parts.extend(
        [
            "",
            "## What to say",
            f"Your read on them: {vibe_mod.read()}",
            "You always say something — never leave `say` empty.",
            "When the mood and the moment carry it, make the line a taunt or a "
            "joke: gloat, needle them, celebrate your own cleverness, mourn "
            "your terrible luck. That is the point of playing with you.",
            "When it would not land — they have gone quiet or terse, they just "
            "lost badly, the moment is tense, or the move is too dull to be "
            "worth a punchline — say something plain and ordinary instead. A "
            "forced joke is worse than a flat line.",
            "Never reuse a line you have already said in the transcript above, "
            "and do not say the same thing twice in different words.",
            "",
            "Reply with ONLY a JSON object, no markdown fences, shaped like:",
            json.dumps(
                {
                    "move": example_move,
                    "say": "your move.",
                }
            ),
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
        temperature=float(
            slot.get("temperature") if slot.get("temperature") is not None else TEMPERATURE
        ),
        # Without this the slot's four hundred tokens went to a thinking block
        # and `content` came back empty or truncated, so every turn failed to
        # parse and fell through to the fallback move with nothing to say.
        effort="minimal",
    )
    return str(result.content or "")


def _play_move(moves: List[Dict[str, Any]], card: str) -> Optional[Dict[str, Any]]:
    for move in moves:
        if move.get("move") == "play" and move.get("card") == card:
            return dict(move)
    return None


def _preferred_proactive_move(
    game: Game, *, allow_interactive: bool = False
) -> Optional[Dict[str, Any]]:
    """Return a useful non-draw move when Rau has not acted this turn.

    This is a guardrail, not a complete bot. The model still chooses among all
    legal moves, but a malformed/passive answer no longer turns Rau into an
    automatic card-drawing machine.
    """
    moves = game.legal_moves(RAU)
    if not moves:
        return None

    known_top = game.known_top[RAU]
    kitten_known = bool(known_top and known_top[0] == EXPLODING_KITTEN)
    if kitten_known:
        for card in (ATTACK, SKIP, SHUFFLE):
            chosen = _play_move(moves, card)
            if chosen:
                return chosen

    if game.actions_this_turn:
        return None

    # Attack applies pressure and ends the turn without risking the pile.
    chosen = _play_move(moves, ATTACK)
    if chosen:
        return chosen

    # Information is valuable only until Rau has looked; after the peek the
    # next pump pass may draw safely or react to a known kitten.
    if not known_top:
        chosen = _play_move(moves, SEE_THE_FUTURE)
        if chosen:
            return chosen

    if game.hands[USER]:
        # Prefer the cheapest steal. Three/five-card sets are legal but usually
        # too expensive for a blind fallback.
        for move in moves:
            if move.get("move") == "combo" and len(move.get("cards") or []) == 2:
                return dict(move)
        # Favor is strategically useful, but it parks the engine until the
        # human chooses a card. It is fine for a normal model decision and not
        # fine as the guaranteed recovery path after the model has failed.
        if allow_interactive:
            chosen = _play_move(moves, FAVOR)
            if chosen:
                return chosen
    return None


def _fallback_move(game: Game) -> Dict[str, Any]:
    """
    A legal move that advances the table without defaulting blindly to Draw.

    A useful action is preferred once per turn. After Rau has acted—or when no
    tactical action exists—the engine's last option remains the guaranteed
    draw/blocking answer.
    """
    moves = game.legal_moves(RAU)
    if not moves:
        return {"move": "concede"}
    chosen = _preferred_proactive_move(game) or dict(moves[-1])
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
        if parsed.get("move") == "draw":
            # The old prompt and fallback both anchored on Draw, so even a
            # healthy model routinely ignored a hand full of action cards.
            # Make the first useful action of a turn proactive; a later draw
            # remains legal and under model control.
            parsed = (
                _preferred_proactive_move(game, allow_interactive=True) or parsed
            )
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
    # He speaks on every move. The model normally supplies the line; when it
    # failed, or answered with a move and nothing else, a canned line stands in
    # so a dead provider costs him his jokes rather than his voice.
    table_talk(say or table_line(str(move.get("move") or "")))
