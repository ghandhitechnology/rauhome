/**
 * Names, colours and shapes for the thirteen cards.
 *
 * Kept beside the table rather than inside `art/` because this is what the *game*
 * calls each card — the title on the frame, the plate colour, and whether it is
 * an action, a cat, or one of the two cards the whole game is about. The art
 * folder owns how a card is drawn; this owns what it is called.
 */
import type { CardId } from './art'
import { PALETTE } from './art'
import type { CardKind } from './art/frame'

export type CardMeta = {
  title: string
  accent: string
  kind: CardKind
  /** One line, shown on hover and read by screen readers. */
  effect: string
}

export const CARD_META: Record<CardId, CardMeta> = {
  exploding_kitten: {
    title: 'Exploding Kitten',
    accent: PALETTE.red,
    kind: 'kitten',
    effect: 'Draw this without a Defuse and you are out.',
  },
  defuse: {
    title: 'Defuse',
    accent: PALETTE.green,
    kind: 'defuse',
    effect: 'Saves you from a kitten, then you hide it back in the deck.',
  },
  nope: {
    title: 'Nope',
    accent: PALETTE.red,
    kind: 'action',
    effect: 'Cancels what is on the table. Can be Noped right back.',
  },
  attack: {
    title: 'Attack',
    accent: PALETTE.violet,
    kind: 'action',
    effect: 'End your turn without drawing. They take two turns.',
  },
  skip: {
    title: 'Skip',
    accent: PALETTE.blue,
    kind: 'action',
    effect: 'End one turn without drawing.',
  },
  favor: {
    title: 'Favor',
    accent: PALETTE.gold,
    kind: 'action',
    effect: 'They choose a card and hand it over.',
  },
  shuffle: {
    title: 'Shuffle',
    accent: PALETTE.green,
    kind: 'action',
    effect: 'Shuffle the draw pile. Nobody knows anything any more.',
  },
  see_the_future: {
    title: 'See the Future',
    accent: PALETTE.violet,
    kind: 'action',
    effect: 'Look at the top three cards, privately.',
  },
  tacocat: {
    title: 'Tacocat',
    accent: PALETTE.gold,
    kind: 'cat',
    effect: 'Does nothing alone. Collect matching pairs.',
  },
  rainbow_ralphing_cat: {
    title: 'Rainbow-Ralphing Cat',
    accent: PALETTE.pink,
    kind: 'cat',
    effect: 'Does nothing alone. Collect matching pairs.',
  },
  cattermelon: {
    title: 'Cattermelon',
    accent: PALETTE.green,
    kind: 'cat',
    effect: 'Does nothing alone. Collect matching pairs.',
  },
  hairy_potato_cat: {
    title: 'Hairy Potato Cat',
    accent: PALETTE.gold,
    kind: 'cat',
    effect: 'Does nothing alone. Collect matching pairs.',
  },
  beard_cat: {
    title: 'Beard Cat',
    accent: PALETTE.blue,
    kind: 'cat',
    effect: 'Does nothing alone. Collect matching pairs.',
  },
}

export function cardTitle(id: string): string {
  return CARD_META[id as CardId]?.title ?? id
}
