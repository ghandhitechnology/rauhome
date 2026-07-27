"""
Who is allowed to know what.

The engine holds the whole truth: both hands and the exact order of the draw
pile. Nobody may see that. This module is the only place the truth is cut down,
and there are exactly two cuts:

* `browser_view` — what is sent over the websocket to the page. It is not enough
  to hide Rau's hand in the React component: the socket payload is one devtools
  panel away, so the hidden state must never leave the process at all.

* `rau_view` / `prompt_fragment` — what the *player* half sees: hand, public
  table, peeks he paid for, and enumerated legal moves. He does not get your
  hand or the deck order.

* `talker_fragment` — what the *face* half sees while chatting: the same public
  table and peeks, plus the shared journal, but no legal-move menu. Moves are
  made by the player half, not by the talker.

Kittens tool results use `rau_view` / `seat_view` for the mover so a See the
Future peek is never delivered via the human's seat payload. Neither cut
receives a field the other player is entitled to keep private.

`tests/test_kittens_fairness.py` asserts this by brute force over full games —
if a card that should be hidden ever appears in either output, it fails.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from rau.games.kittens import deck as deck_mod
from rau.games.kittens.deck import EXPLODING_KITTEN
from rau.games.kittens.engine import (
    BLOCKING_PHASES,
    PHASE_DEFUSE,
    PHASE_FAVOR,
    PHASE_NOPE,
    PHASE_OVER,
    PHASE_SALVAGE,
    RAU,
    USER,
    Game,
    other,
)


def _public(game: Game) -> Dict[str, Any]:
    """The parts of the table both players can see by looking at it."""
    pending = None
    if game.pending:
        pending = {
            "action_id": game.pending.action_id,
            "actor": game.pending.actor,
            "kind": game.pending.kind,
            # The cards are already face up on the discard pile.
            "cards": list(game.pending.cards),
            "named_card": game.pending.payload.get("named_card"),
            "nopes": game.pending.nopes,
            "waiting_on": game.pending.waiting_on(),
            "deadline": game.pending.deadline,
        }
    return {
        "game_id": game.game_id,
        "phase": game.phase,
        "current": game.current,
        "turns_to_take": game.turns_to_take,
        "deck_count": len(game.draw),
        "discard": list(game.discard),
        "awaiting_seat": game.awaiting_seat,
        "pending": pending,
        "winner": game.winner,
        "over_reason": game.over_reason,
        "hand_counts": {seat: len(cards) for seat, cards in game.hands.items()},
        "log": [{"seat": e.seat, "text": e.text, "at": e.at} for e in game.log[-12:]],
    }


def seat_view(game: Game, seat: str) -> Dict[str, Any]:
    """
    The table as one seat is entitled to see it.

    Their own hand in full, their own peek at the future, everyone's hand *count*,
    and nothing else. The opposing hand and the draw order are simply absent —
    not masked, not nulled, absent, so there is nothing to accidentally render.
    """
    view = _public(game)
    view["seat"] = seat
    view["hand"] = list(game.hands[seat])
    view["known_top"] = list(game.known_top[seat])
    view["your_turn"] = game.current == seat and game.phase not in BLOCKING_PHASES
    view["awaiting_you"] = game.awaiting_seat == seat
    view["can_nope"] = bool(
        game.phase == PHASE_NOPE
        and game.pending
        and game.pending.waiting_on() == seat
        and deck_mod.NOPE in game.hands[seat]
    )
    if game.phase == PHASE_DEFUSE and game.awaiting_seat == seat:
        # The only number that matters while placing the kitten, and it is public.
        view["insert_max"] = len(game.draw)
    if game.phase == PHASE_OVER:
        # Hands are revealed at the end, the way you turn your cards over.
        view["final_hands"] = {s: sorted(h) for s, h in game.hands.items()}
    return view


def browser_view(game: Game) -> Dict[str, Any]:
    """What goes over the websocket. The human's seat, and nothing more."""
    return seat_view(game, USER)


# ------------------------------------------------------------------ the model

def _describe_hand(hand: List[str]) -> str:
    counts: Dict[str, int] = {}
    for card in hand:
        counts[card] = counts.get(card, 0) + 1
    parts = [
        f"{deck_mod.label(card)}{f' x{n}' if n > 1 else ''}"
        for card, n in sorted(counts.items())
    ]
    return ", ".join(parts) if parts else "(empty)"


def _move_line(move: Dict[str, Any]) -> str:
    kind = move["move"]
    if kind == "play":
        return f'play_kittens_card(move="play", card="{move["card"]}") — {deck_mod.EFFECTS.get(move["card"], "")}'.strip()
    if kind == "combo":
        cards = json.dumps(move["cards"])
        if "named_card" in move:
            return (
                f'play_kittens_card(move="combo", cards={cards}, named_card="…") — '
                "three of a kind: name any card and take it from their hand if they hold it"
            )
        if len(move["cards"]) == 5:
            return (
                f'play_kittens_card(move="combo", cards={cards}) — '
                "five different cards: take anything you like off the discard pile"
            )
        return (
            f'play_kittens_card(move="combo", cards={cards}) — '
            "two of a kind: steal one card from their hand at random"
        )
    if kind == "draw":
        return 'play_kittens_card(move="draw") — end your turn and take the risk'
    if kind == "nope":
        return 'play_kittens_card(move="nope") — cancel what is on the table'
    if kind == "pass_nope":
        return 'play_kittens_card(move="pass_nope") — let it happen'
    if kind == "give_favor":
        return f'play_kittens_card(move="give_favor", card="{move["card"]}")'
    if kind == "take_from_discard":
        return f'play_kittens_card(move="take_from_discard", card="{move["card"]}")'
    if kind == "insert_kitten":
        return f'play_kittens_card(move="insert_kitten", index=N) — N is {move["index"]}, 0 is the very top'
    return kind


def _table_lines(game: Game, seat: str) -> List[str]:
    """Shared public + private-for-seat facts, without a move menu."""
    if game.phase == PHASE_OVER:
        who = "You won" if game.winner == seat else "You lost"
        return [
            "\n## The game",
            f"{who}. {game.over_reason}",
            "The table is finished. React to it in your own voice, then let it go.",
        ]

    opponent = other(seat)
    lines = [
        "\n## The game of Exploding Kittens on the table",
        "",
        f"Your hand ({len(game.hands[seat])}): {_describe_hand(game.hands[seat])}",
        f"Their hand: {len(game.hands[opponent])} cards — you cannot see them, and guessing is part of it.",
        f"Draw pile: {len(game.draw)} cards. Exactly one Exploding Kitten is somewhere in it.",
        f"Discard pile: {_describe_hand(game.discard) if game.discard else '(empty)'}",
    ]

    if game.known_top[seat]:
        peeked = ", ".join(deck_mod.label(c) for c in game.known_top[seat])
        lines.append(
            f"You have seen the top of the deck: {peeked} (in that order, from the top)."
        )

    if game.phase == PHASE_NOPE and game.pending:
        played = ", ".join(deck_mod.label(c) for c in game.pending.cards)
        who = "You" if game.pending.actor == seat else "They"
        lines.append("")
        lines.append(f"{who} played {played}. It is waiting to resolve.")
        if game.pending.nopes:
            lines.append(f"Nopes stacked on it so far: {game.pending.nopes}.")
        if game.pending.waiting_on() == seat:
            lines.append("You have a moment to Nope it. Decide now.")
    elif game.phase == PHASE_FAVOR and game.awaiting_seat == seat:
        lines.append("")
        lines.append("They played Favor on you. You must hand over one card of your choosing.")
    elif game.phase == PHASE_DEFUSE and game.awaiting_seat == seat:
        lines.append("")
        lines.append(
            f"You drew the Exploding Kitten and used your Defuse. Put it back anywhere "
            f"in the {len(game.draw)}-card pile — index 0 is the very top, "
            f"{len(game.draw)} is the bottom. They do not get to see where."
        )
    elif game.phase == PHASE_SALVAGE and game.awaiting_seat == seat:
        lines.append("")
        lines.append("Your five-card set landed. Take anything you want off the discard pile.")
    elif game.current == seat:
        owed = game.turns_to_take
        lines.append("")
        lines.append(
            f"It is your turn — you owe {owed} turn{'s' if owed != 1 else ''}. "
            "You may play as many cards as you like, but the turn only ends when you "
            "draw or Skip."
        )
    else:
        lines.append("")
        lines.append("It is their turn. Wait, and talk.")
    return lines


def _copiable(move: Dict[str, Any]) -> Dict[str, Any]:
    """
    A listed move with its open choices filled in.

    `legal_moves` marks the two free choices — where the kitten goes back,
    which card to demand — with prose placeholders ("0..N", "<any card you
    want…>"). That reads fine but the engine refuses both verbatim, and the
    model is told to copy. Fill them so anything on the list plays as printed.
    """
    move = dict(move)
    if move.get("move") == "insert_kitten" and not isinstance(move.get("index"), int):
        move["index"] = 0
    named = move.get("named_card")
    if named is not None and named not in deck_mod.ALL_CARDS:
        move["named_card"] = deck_mod.SKIP
    return move


def prompt_fragment(game: Game, seat: str = RAU) -> str:
    """
    The game as the player half is entitled to see it.

    Every move he is allowed to make is spelled out with its exact arguments, so
    a legal move is always a copy rather than a derivation.
    """
    lines = _table_lines(game, seat)
    if game.phase == PHASE_OVER:
        return "\n".join(lines) + "\n"

    moves = game.legal_moves(seat)
    if moves:
        lines.append("")
        lines.append("Legal moves right now — reply with one of these as JSON `move`:")
        lines.extend(f"- {json.dumps(_copiable(m))}" for m in moves)
        lines.append("")
        lines.append(
            "Play to win, and say something while you do it — one short line, in your "
            "own voice, the way someone actually talks across a table. Do not narrate "
            "the rules and do not list your hand out loud."
        )
    return "\n".join(lines) + "\n"


def talker_fragment(game: Game, seat: str = RAU) -> str:
    """
    The game as the face talker sees it — table and journal, no move menu.

    Moves are made by the player half. The talker reacts, banters, and deals or
    clears the table; he does not play_kittens_card.
    """
    from rau.games.kittens import journal

    lines = _table_lines(game, seat)
    if game.phase != PHASE_OVER:
        lines.append("")
        lines.append(
            "Your player half makes the moves at this table. You talk across it — "
            "react, banter, celebrate, complain. Do not try to play cards yourself; "
            "start_kittens and end_kittens are the only game tools you have."
        )
    history = journal.tail()
    if history:
        lines.append("")
        lines.append(history.strip())
    return "\n".join(lines) + "\n"


def rau_view(game: Game) -> Dict[str, Any]:
    """Structured form of the same information, for logging and tests."""
    return seat_view(game, RAU)
