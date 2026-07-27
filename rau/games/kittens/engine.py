"""
What is true in a game of Exploding Kittens.

This module knows the rules and nothing else. It does not know about the event
bus, the model, HTTP, or the browser — it takes a move and either applies it or
explains why it is illegal. Everything that can be tested about this game can be
tested here, without a network or a language model, which is the point: the rules
are the risky part and they should be provable before anything renders.

## The two things worth understanding before reading on

**Turns are a counter, not a toggle.** `turns_to_take` is how many turns the
current player still owes, including the one in progress. Attack is the only card
that manipulates it. A turn ends when you draw or Skip, never when you play some
other card, so "play four cards then draw" is one turn.

**Played cards do not take effect immediately.** Anything Nope-able becomes a
`Pending` action that sits in front of the player who could Nope it, with a
deadline. Nope is itself played onto that same pending action rather than
creating a new one, so Nope-the-Nope-the-Nope needs no special case: the action
resolves if an even number of Nopes ended up on it, and is cancelled if odd.

The window opens even when the player who could Nope holds no Nope card. If it
did not, the *presence of a pause* would tell you they were holding one, which
would leak hidden information through timing rather than through state. The one
exception is the human's own window when they hold no Nope: they already know
their own hand, so closing early tells them nothing they did not know.
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rau.games.kittens import deck as deck_mod
from rau.games.kittens.deck import (
    ATTACK,
    DEFUSE,
    EXPLODING_KITTEN,
    FAVOR,
    FUTURE_DEPTH,
    NOPE,
    SEE_THE_FUTURE,
    SHUFFLE,
    SKIP,
    UNPLAYABLE,
)

USER = "user"
RAU = "rau"
SEATS: Tuple[str, str] = (USER, RAU)

#: How long a Nope may be played for. Long enough to react to, short enough that
#: a game of forty actions does not become a game of forty pauses.
NOPE_WINDOW_MS = 5_000

#: Turns the victim of an Attack must take. Attacks stack: an Attack played by
#: someone who already owes turns hands over what they owe *plus* two, so the
#: table climbs 2 → 4 → 6 rather than resetting.
ATTACK_TURNS = 2

#: Matching cards needed for each combo.
COMBO_TWO = 2
COMBO_THREE = 3
#: Five *different* cards, which is the only combo that reaches the discard pile.
COMBO_FIVE = 5

PHASE_PLAYING = "playing"
PHASE_NOPE = "nope_window"
PHASE_FAVOR = "awaiting_favor"
PHASE_DEFUSE = "awaiting_defuse"
PHASE_NAME = "awaiting_named_card"
PHASE_SALVAGE = "awaiting_discard_pick"
PHASE_OVER = "over"

#: Phases in which the game is waiting on a specific player for a specific
#: decision, rather than on whoever's turn it is.
BLOCKING_PHASES = (PHASE_FAVOR, PHASE_DEFUSE, PHASE_NAME, PHASE_SALVAGE)


class IllegalMove(Exception):
    """A move that the rules do not allow. Carries a machine-readable code."""

    def __init__(self, message: str, code: str = "illegal") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def other(seat: str) -> str:
    return RAU if seat == USER else USER


@dataclass
class Pending:
    """An action waiting out its Nope window."""

    action_id: str
    actor: str
    kind: str
    cards: List[str]
    payload: Dict[str, Any] = field(default_factory=dict)
    #: Nope cards stacked on top. Even count resolves, odd count cancels.
    nopes: int = 0
    #: Who played the most recent card on this stack; the *other* seat may Nope.
    last_player: str = ""
    deadline: float = 0.0

    @property
    def cancelled(self) -> bool:
        return self.nopes % 2 == 1

    def waiting_on(self) -> str:
        return other(self.last_player)


@dataclass
class Entry:
    """One line of what happened, for the UI feed and for Rau's context."""

    seat: str
    text: str
    at: float


class Game:
    """
    One game, guarded by a lock.

    Every public method takes the lock, applies at most one legal transition, and
    leaves the game in a state that `view.py` can render. Callers never mutate
    fields directly — there is no state here that is safe to change from outside,
    because almost every field is hidden from at least one player.
    """

    def __init__(self, *, seed: Optional[int] = None, now: Optional[float] = None) -> None:
        self._lock = threading.RLock()
        self.game_id = uuid.uuid4().hex[:12]
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self._rng = random.Random(self.seed)
        self.started = now if now is not None else time.time()

        draw, hand_user, hand_rau = deck_mod.deal_two_player(self._rng)
        self.draw: List[str] = draw
        self.hands: Dict[str, List[str]] = {USER: hand_user, RAU: hand_rau}
        self.discard: List[str] = []

        self.current: str = USER
        self.turns_to_take: int = 1
        self.phase: str = PHASE_PLAYING
        self.pending: Optional[Pending] = None
        #: Set only for the player who is being asked something (Favor, naming a
        #: card, defusing). Never both.
        self.awaiting_seat: Optional[str] = None

        #: What See the Future last revealed, per seat, and how deep. Cleared the
        #: moment the deck changes underneath it — a stale peek is a lie.
        self.known_top: Dict[str, List[str]] = {USER: [], RAU: []}

        self.winner: Optional[str] = None
        self.over_reason: str = ""
        self.log: List[Entry] = []
        self._note(USER, "Game dealt. Your turn.")

    # ---------------------------------------------------------------- helpers

    def _note(self, seat: str, text: str) -> None:
        self.log.append(Entry(seat=seat, text=text, at=time.time()))
        del self.log[:-40]

    def _forget_future(self, seat: Optional[str] = None) -> None:
        """The deck moved; nobody's peek is trustworthy any more."""
        if seat is None:
            self.known_top = {USER: [], RAU: []}
        else:
            self.known_top[seat] = []

    def _take_from_hand(self, seat: str, card: str) -> None:
        try:
            self.hands[seat].remove(card)
        except ValueError:
            raise IllegalMove(f"you are not holding {deck_mod.label(card)}", "not_held")

    def _give(self, seat: str, card: str) -> None:
        self.hands[seat].append(card)
        self.hands[seat].sort()

    def _require_phase(self, *phases: str) -> None:
        if self.phase not in phases:
            raise IllegalMove(
                f"cannot do that while the game is {self.phase.replace('_', ' ')}",
                "wrong_phase",
            )

    def _require_turn(self, seat: str) -> None:
        if self.current != seat:
            raise IllegalMove("it is not your turn", "not_your_turn")

    def _end_game(self, winner: str, reason: str) -> None:
        self.phase = PHASE_OVER
        self.winner = winner
        self.over_reason = reason
        self.pending = None
        self.awaiting_seat = None
        self._note(winner, reason)

    # ------------------------------------------------------------ turn cycle

    def _end_turn(self) -> None:
        """One turn discharged. Hand over only when the counter runs out."""
        self.turns_to_take -= 1
        if self.turns_to_take <= 0:
            self.current = other(self.current)
            self.turns_to_take = 1
        self._note(self.current, "Your turn." if self.current == USER else "Rau's turn.")

    # ------------------------------------------------------------ nope window

    def _open_window(self, pending: Pending, now: float) -> None:
        """
        Start (or restart) the Nope window in front of whoever may Nope.

        Closing early when the human holds no Nope is safe — they know their own
        hand — and skips a pause that could only ever be dead air. Rau's window
        always runs its full length so the human cannot read his hand off the
        clock.
        """
        target = pending.waiting_on()
        self.pending = pending
        if target == USER and NOPE not in self.hands[USER]:
            self._resolve_pending(now)
            return
        pending.deadline = now + NOPE_WINDOW_MS / 1000.0
        self.phase = PHASE_NOPE

    def tick(self, now: Optional[float] = None) -> bool:
        """Resolve a Nope window whose time has run out. Returns True if it did."""
        with self._lock:
            now = now if now is not None else time.time()
            if self.phase != PHASE_NOPE or not self.pending:
                return False
            if now < self.pending.deadline:
                return False
            self._resolve_pending(now)
            return True

    def _resolve_pending(self, now: float) -> None:
        pending = self.pending
        self.pending = None
        if not pending:
            return
        if pending.cancelled:
            self.phase = PHASE_PLAYING
            self._note(
                pending.waiting_on(),
                f"{deck_mod.label(pending.cards[0])} was Noped.",
            )
            return
        self.phase = PHASE_PLAYING
        self._apply(pending, now)

    # ------------------------------------------------------------ resolution

    def _apply(self, pending: Pending, now: float) -> None:
        """An action survived its Nope window. Make it real."""
        actor = pending.actor
        victim = other(actor)

        if pending.kind == "combo_two":
            if not self.hands[victim]:
                self._note(actor, "Nothing to steal — their hand is empty.")
                return
            card = self._rng.choice(self.hands[victim])
            self.hands[victim].remove(card)
            self._give(actor, card)
            self._note(actor, f"Stole a card at random from {victim}.")
            return

        if pending.kind == "combo_three":
            named = str(pending.payload.get("named_card") or "")
            if named in self.hands[victim]:
                self.hands[victim].remove(named)
                self._give(actor, named)
                self._note(actor, f"Demanded {deck_mod.label(named)} — and got it.")
            else:
                self._note(actor, f"Demanded {deck_mod.label(named)} — they had none.")
            return

        if pending.kind == "combo_five":
            self.phase = PHASE_SALVAGE
            self.awaiting_seat = actor
            self._note(actor, "Picking a card back out of the discard pile.")
            return

        card = pending.cards[0]

        if card == ATTACK:
            # Shed everything still owed onto the other player, plus two. A first
            # Attack passes 2; one played while already owing 2 passes 4.
            owed = self.turns_to_take
            self.current = victim
            self.turns_to_take = ATTACK_TURNS if owed <= 1 else owed + ATTACK_TURNS
            self._note(actor, f"Attack — {victim} now owes {self.turns_to_take} turns.")
            return

        if card == SKIP:
            self._end_turn()
            return

        if card == SHUFFLE:
            self._rng.shuffle(self.draw)
            self._forget_future()
            self._note(actor, "Shuffled the draw pile.")
            return

        if card == SEE_THE_FUTURE:
            self.known_top[actor] = list(self.draw[:FUTURE_DEPTH])
            self._note(actor, "Looked at the top of the deck.")
            return

        if card == FAVOR:
            if not self.hands[victim]:
                self._note(actor, "Asked a favor of an empty hand.")
                return
            self.phase = PHASE_FAVOR
            self.awaiting_seat = victim
            self._note(actor, f"Favor — {victim} must hand something over.")
            return

    # ---------------------------------------------------------------- moves

    def play(self, seat: str, card: str, now: Optional[float] = None) -> None:
        """Play a single card from hand."""
        with self._lock:
            now = now if now is not None else time.time()
            self.tick(now)
            self._require_phase(PHASE_PLAYING)
            self._require_turn(seat)
            if card in UNPLAYABLE:
                raise IllegalMove(
                    f"{deck_mod.label(card)} cannot be played from your hand", "unplayable"
                )
            if card == NOPE:
                raise IllegalMove("Nope is only played to cancel something", "nope_unprompted")
            if card in deck_mod.CAT_CARDS:
                raise IllegalMove(
                    "cat cards do nothing alone — play two or three matching", "needs_combo"
                )
            self._take_from_hand(seat, card)
            self.discard.append(card)
            self._note(seat, f"Played {deck_mod.label(card)}.")
            self._open_window(
                Pending(
                    action_id=uuid.uuid4().hex[:10],
                    actor=seat,
                    kind="card",
                    cards=[card],
                    last_player=seat,
                ),
                now,
            )

    def combo(
        self,
        seat: str,
        cards: List[str],
        *,
        named_card: Optional[str] = None,
        now: Optional[float] = None,
    ) -> None:
        """Play two, three, or five cards as a set."""
        with self._lock:
            now = now if now is not None else time.time()
            self.tick(now)
            self._require_phase(PHASE_PLAYING)
            self._require_turn(seat)
            cards = list(cards)

            if len(cards) in (COMBO_TWO, COMBO_THREE):
                if len(set(cards)) != 1:
                    raise IllegalMove("a combo of two or three must be matching cards", "not_matching")
                if cards[0] in UNPLAYABLE:
                    raise IllegalMove("those cards cannot be played", "unplayable")
                kind = "combo_two" if len(cards) == COMBO_TWO else "combo_three"
                if kind == "combo_three":
                    if not named_card:
                        raise IllegalMove("name the card you are demanding", "needs_named_card")
                    if named_card not in deck_mod.ALL_CARDS:
                        raise IllegalMove(f"no such card: {named_card}", "unknown_card")
            elif len(cards) == COMBO_FIVE:
                if len(set(cards)) != COMBO_FIVE:
                    raise IllegalMove("a combo of five must be five different cards", "not_distinct")
                if not self.discard:
                    raise IllegalMove("the discard pile is empty", "empty_discard")
                kind = "combo_five"
            else:
                raise IllegalMove("combos are two, three, or five cards", "bad_combo_size")

            held = list(self.hands[seat])
            for card in cards:
                if card not in held:
                    raise IllegalMove(f"you are not holding {deck_mod.label(card)}", "not_held")
                held.remove(card)
            for card in cards:
                self._take_from_hand(seat, card)
            self.discard.extend(cards)
            self._note(seat, f"Played {len(cards)} cards as a set.")
            self._open_window(
                Pending(
                    action_id=uuid.uuid4().hex[:10],
                    actor=seat,
                    kind=kind,
                    cards=cards,
                    payload={"named_card": named_card} if named_card else {},
                    last_player=seat,
                ),
                now,
            )

    def nope(self, seat: str, now: Optional[float] = None) -> None:
        """Cancel — or un-cancel — whatever is waiting to resolve."""
        with self._lock:
            now = now if now is not None else time.time()
            self.tick(now)
            self._require_phase(PHASE_NOPE)
            pending = self.pending
            if not pending:
                raise IllegalMove("nothing to Nope", "nothing_pending")
            if pending.waiting_on() != seat:
                raise IllegalMove("you cannot Nope your own card", "own_card")
            self._take_from_hand(seat, NOPE)
            self.discard.append(NOPE)
            pending.nopes += 1
            pending.last_player = seat
            self._note(seat, "Nope." if pending.nopes % 2 else "Nope — un-Noped.")
            self._open_window(pending, now)

    def pass_nope(self, seat: str, now: Optional[float] = None) -> None:
        """Decline the window without waiting for it to expire."""
        with self._lock:
            now = now if now is not None else time.time()
            self._require_phase(PHASE_NOPE)
            if not self.pending or self.pending.waiting_on() != seat:
                raise IllegalMove("the window is not yours to pass", "not_yours")
            self._resolve_pending(now)

    def draw_card(self, seat: str, now: Optional[float] = None) -> str:
        """
        End a turn the only way that carries risk.

        Returns the card drawn — including the kitten, so the caller can stage the
        explosion — but a kitten never lands in a hand: it either burns a Defuse
        and goes back into the deck, or it ends the game.
        """
        with self._lock:
            now = now if now is not None else time.time()
            self.tick(now)
            self._require_phase(PHASE_PLAYING)
            self._require_turn(seat)
            if not self.draw:
                raise IllegalMove("the draw pile is empty", "empty_deck")

            card = self.draw.pop(0)
            for peeker in SEATS:
                if self.known_top[peeker]:
                    self.known_top[peeker] = self.known_top[peeker][1:]

            if card != EXPLODING_KITTEN:
                self._give(seat, card)
                self._note(seat, "Drew a card.")
                self._end_turn()
                return card

            self.discard.append(EXPLODING_KITTEN)
            if DEFUSE not in self.hands[seat]:
                self._end_game(other(seat), f"{seat} drew the Exploding Kitten.")
                return card

            self._take_from_hand(seat, DEFUSE)
            self.discard.append(DEFUSE)
            self.phase = PHASE_DEFUSE
            self.awaiting_seat = seat
            self._note(seat, "Exploding Kitten — defused. Putting it back somewhere.")
            return card

    def insert_kitten(self, seat: str, index: int, now: Optional[float] = None) -> None:
        """Slide the defused kitten back into the deck at a chosen depth."""
        with self._lock:
            self._require_phase(PHASE_DEFUSE)
            if self.awaiting_seat != seat:
                raise IllegalMove("not yours to place", "not_yours")
            if not isinstance(index, int) or not 0 <= index <= len(self.draw):
                raise IllegalMove(f"index must be between 0 and {len(self.draw)}", "bad_index")
            # The pile the kitten goes back into is one nobody may claim to know.
            self.draw.insert(index, EXPLODING_KITTEN)
            self.discard.remove(EXPLODING_KITTEN)
            self._forget_future()
            self.phase = PHASE_PLAYING
            self.awaiting_seat = None
            self._note(seat, "Put the kitten back.")
            self._end_turn()

    def give_favor(self, seat: str, card: str, now: Optional[float] = None) -> None:
        """Hand over the card you least want to lose."""
        with self._lock:
            self._require_phase(PHASE_FAVOR)
            if self.awaiting_seat != seat:
                raise IllegalMove("nobody asked you for a favor", "not_yours")
            self._take_from_hand(seat, card)
            self._give(other(seat), card)
            self.phase = PHASE_PLAYING
            self.awaiting_seat = None
            self._note(seat, f"Gave up {deck_mod.label(card)}.")

    def take_from_discard(self, seat: str, card: str, now: Optional[float] = None) -> None:
        """The five-different-cards combo: salvage anything off the pile."""
        with self._lock:
            self._require_phase(PHASE_SALVAGE)
            if self.awaiting_seat != seat:
                raise IllegalMove("not your pick", "not_yours")
            if card not in self.discard:
                raise IllegalMove(f"{deck_mod.label(card)} is not in the discard pile", "not_in_discard")
            if card == EXPLODING_KITTEN:
                raise IllegalMove("you may not take the kitten", "unplayable")
            self.discard.remove(card)
            self._give(seat, card)
            self.phase = PHASE_PLAYING
            self.awaiting_seat = None
            self._note(seat, f"Took {deck_mod.label(card)} back off the pile.")

    def concede(self, seat: str) -> None:
        with self._lock:
            if self.phase == PHASE_OVER:
                return
            self._end_game(other(seat), f"{seat} walked away from the table.")

    # ------------------------------------------------------------ legal moves

    def legal_moves(self, seat: str) -> List[Dict[str, Any]]:
        """
        Every move `seat` may make right now, as concrete tool arguments.

        This is handed to the model verbatim. Giving it the enumerated legal set
        rather than the rules and a hope is the difference between an opponent
        that plays and one that spends three retries discovering it cannot play a
        Defuse.
        """
        with self._lock:
            moves: List[Dict[str, Any]] = []
            hand = self.hands[seat]

            if self.phase == PHASE_NOPE and self.pending and self.pending.waiting_on() == seat:
                if NOPE in hand:
                    moves.append({"move": "nope"})
                moves.append({"move": "pass_nope"})
                return moves

            if self.phase == PHASE_FAVOR and self.awaiting_seat == seat:
                return [{"move": "give_favor", "card": c} for c in sorted(set(hand))]

            if self.phase == PHASE_DEFUSE and self.awaiting_seat == seat:
                return [{"move": "insert_kitten", "index": f"0..{len(self.draw)}"}]

            if self.phase == PHASE_SALVAGE and self.awaiting_seat == seat:
                return [
                    {"move": "take_from_discard", "card": c}
                    for c in sorted(set(self.discard))
                    if c != EXPLODING_KITTEN
                ]

            if self.phase != PHASE_PLAYING or self.current != seat:
                return moves

            for card in sorted(set(hand)):
                if card in UNPLAYABLE or card == NOPE or card in deck_mod.CAT_CARDS:
                    continue
                moves.append({"move": "play", "card": card})

            counts: Dict[str, int] = {}
            for card in hand:
                counts[card] = counts.get(card, 0) + 1
            for card, n in sorted(counts.items()):
                if card in UNPLAYABLE:
                    continue
                if n >= COMBO_TWO:
                    moves.append({"move": "combo", "cards": [card] * COMBO_TWO})
                if n >= COMBO_THREE:
                    moves.append(
                        {
                            "move": "combo",
                            "cards": [card] * COMBO_THREE,
                            "named_card": "<any card you want from their hand>",
                        }
                    )
            distinct = sorted({c for c in hand if c not in UNPLAYABLE})
            if len(distinct) >= COMBO_FIVE and self.discard:
                moves.append({"move": "combo", "cards": distinct[:COMBO_FIVE]})

            moves.append({"move": "draw"})
            return moves

    def snapshot(self) -> Dict[str, Any]:
        """Complete state. Hidden from everyone — only tests and `view.py` see this."""
        with self._lock:
            return {
                "game_id": self.game_id,
                "seed": self.seed,
                "phase": self.phase,
                "current": self.current,
                "turns_to_take": self.turns_to_take,
                "draw": list(self.draw),
                "hands": {s: list(h) for s, h in self.hands.items()},
                "discard": list(self.discard),
                "known_top": {s: list(v) for s, v in self.known_top.items()},
                "awaiting_seat": self.awaiting_seat,
                "winner": self.winner,
                "over_reason": self.over_reason,
                "pending": None
                if not self.pending
                else {
                    "action_id": self.pending.action_id,
                    "actor": self.pending.actor,
                    "kind": self.pending.kind,
                    "cards": list(self.pending.cards),
                    "payload": dict(self.pending.payload),
                    "nopes": self.pending.nopes,
                    "waiting_on": self.pending.waiting_on(),
                    "deadline": self.pending.deadline,
                },
                "log": [{"seat": e.seat, "text": e.text, "at": e.at} for e in self.log],
            }
