/**
 * Names, colours and shapes for the thirteen cards.
 *
 * Kept beside the table rather than inside `art/` because this is what the *game*
 * calls each card — the title on the frame, the plate colour, and whether it is
 * an action, a cat, or one of the two cards the whole game is about. The art
 * folder owns how a card is drawn; this owns what it is called.
 */
import { tr, type TranslationKey } from '../../i18n'
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

/**
 * The thirteen cards, named in the reader's language.
 *
 * A function rather than a constant because the language can change with a
 * game already dealt: a frozen record would leave the hand in English while
 * the rest of the table moved to Korean. The five cat cards share one effect
 * line, since what they do is precisely that they do nothing on their own.
 */
const CARDS: Record<CardId, { accent: string; kind: CardKind; effect: TranslationKey }> = {
  exploding_kitten: {
    accent: PALETTE.red,
    kind: 'kitten',
    effect: 'card.exploding_kitten.effect',
  },
  defuse: { accent: PALETTE.green, kind: 'defuse', effect: 'card.defuse.effect' },
  nope: { accent: PALETTE.red, kind: 'action', effect: 'card.nope.effect' },
  attack: { accent: PALETTE.violet, kind: 'action', effect: 'card.attack.effect' },
  skip: { accent: PALETTE.blue, kind: 'action', effect: 'card.skip.effect' },
  favor: { accent: PALETTE.gold, kind: 'action', effect: 'card.favor.effect' },
  shuffle: { accent: PALETTE.green, kind: 'action', effect: 'card.shuffle.effect' },
  see_the_future: {
    accent: PALETTE.violet,
    kind: 'action',
    effect: 'card.see_the_future.effect',
  },
  tacocat: { accent: PALETTE.gold, kind: 'cat', effect: 'card.cat.effect' },
  rainbow_ralphing_cat: { accent: PALETTE.pink, kind: 'cat', effect: 'card.cat.effect' },
  cattermelon: { accent: PALETTE.green, kind: 'cat', effect: 'card.cat.effect' },
  hairy_potato_cat: { accent: PALETTE.gold, kind: 'cat', effect: 'card.cat.effect' },
  beard_cat: { accent: PALETTE.blue, kind: 'cat', effect: 'card.cat.effect' },
}

export function cardMeta(id: CardId): CardMeta {
  const { accent, kind, effect } = CARDS[id]
  return { accent, kind, title: tr(`card.${id}`), effect: tr(effect) }
}

/** Every card, in deck order — for pickers that offer the whole set. */
export const CARD_IDS = Object.keys(CARDS) as CardId[]

export function cardTitle(id: string): string {
  return id in CARDS ? cardMeta(id as CardId).title : id
}
