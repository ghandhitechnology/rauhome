"""
The deck itself: what cards exist, how many, and how a two-player game is dealt.

Kept separate from the engine because the composition of the deck is *data* — it is
the one part of the game with a right answer that can be checked against a physical
box, and it should be readable as a table rather than dug out of a state machine.

Counts are the 56-card base set.
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple

EXPLODING_KITTEN = "exploding_kitten"
DEFUSE = "defuse"
NOPE = "nope"
ATTACK = "attack"
SKIP = "skip"
FAVOR = "favor"
SHUFFLE = "shuffle"
SEE_THE_FUTURE = "see_the_future"

#: Cat cards have no ability of their own. They exist only to be collected into
#: matching sets, which is why they are the funniest cards and the most annoying
#: ones to hold.
CAT_CARDS: Tuple[str, ...] = (
    "tacocat",
    "rainbow_ralphing_cat",
    "cattermelon",
    "hairy_potato_cat",
    "beard_cat",
)

COUNTS: Dict[str, int] = {
    EXPLODING_KITTEN: 4,
    DEFUSE: 6,
    NOPE: 5,
    ATTACK: 4,
    SKIP: 4,
    FAVOR: 4,
    SHUFFLE: 4,
    SEE_THE_FUTURE: 5,
    **{cat: 4 for cat in CAT_CARDS},
}

LABELS: Dict[str, str] = {
    EXPLODING_KITTEN: "Exploding Kitten",
    DEFUSE: "Defuse",
    NOPE: "Nope",
    ATTACK: "Attack",
    SKIP: "Skip",
    FAVOR: "Favor",
    SHUFFLE: "Shuffle",
    SEE_THE_FUTURE: "See the Future",
    "tacocat": "Tacocat",
    "rainbow_ralphing_cat": "Rainbow-Ralphing Cat",
    "cattermelon": "Cattermelon",
    "hairy_potato_cat": "Hairy Potato Cat",
    "beard_cat": "Beard Cat",
}

#: What a card does when it resolves, in one line, for the model's benefit. Cat
#: cards are deliberately absent: they do nothing alone.
EFFECTS: Dict[str, str] = {
    ATTACK: "End your turn without drawing; the other player takes two turns.",
    SKIP: "End one of your turns without drawing.",
    FAVOR: "The other player chooses a card from their hand and gives it to you.",
    SHUFFLE: "Shuffle the draw pile.",
    SEE_THE_FUTURE: "Privately look at the top three cards of the draw pile.",
    NOPE: "Cancel the action that is waiting to resolve. Can itself be Noped.",
    DEFUSE: "Played automatically when you draw the Exploding Kitten.",
}

ALL_CARDS: Tuple[str, ...] = tuple(COUNTS)

#: Cards that may not be played from hand as an action. Defuse is spent by the
#: engine when a kitten is drawn; the kitten is never in a hand to begin with.
UNPLAYABLE: frozenset = frozenset({EXPLODING_KITTEN, DEFUSE})

#: How many cards each player starts holding, *before* their guaranteed Defuse.
STARTING_HAND = 7

#: Cards you may look at with See the Future.
FUTURE_DEPTH = 3


def label(card: str) -> str:
    return LABELS.get(card, card)


def build_full_deck() -> List[str]:
    """Every card in the box, unshuffled. 56 cards."""
    deck: List[str] = []
    for card, count in COUNTS.items():
        deck.extend([card] * count)
    return deck


def deal_two_player(rng: random.Random) -> Tuple[List[str], List[str], List[str]]:
    """
    Set up a two-player game exactly the way the rulebook says.

    1. Take the Exploding Kittens and Defuses out of the deck.
    2. Deal seven cards to each player from what is left.
    3. Give each player one Defuse, so nobody dies on turn one.
    4. Put the remaining Defuses back.
    5. Put in one Exploding Kitten — always one fewer than there are players, so
       exactly one person is left standing.
    6. Shuffle.

    Returns ``(draw_pile, hand_a, hand_b)``. The draw pile is ordered top-first:
    index 0 is the next card drawn, which is what makes insert positions and
    See the Future readable rather than something you have to hold backwards in
    your head.
    """
    pool = [c for c in build_full_deck() if c not in (EXPLODING_KITTEN, DEFUSE)]
    rng.shuffle(pool)

    hand_a = [pool.pop() for _ in range(STARTING_HAND)]
    hand_b = [pool.pop() for _ in range(STARTING_HAND)]
    hand_a.append(DEFUSE)
    hand_b.append(DEFUSE)

    draw = pool
    draw.extend([DEFUSE] * (COUNTS[DEFUSE] - 2))
    draw.append(EXPLODING_KITTEN)
    rng.shuffle(draw)

    hand_a.sort()
    hand_b.sort()
    return draw, hand_a, hand_b
