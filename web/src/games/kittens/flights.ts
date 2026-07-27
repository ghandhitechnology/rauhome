/**
 * Cards moving between places.
 *
 * Split in two on purpose. `diffFlights` is a pure reading of what moved
 * between two table states and can be tested on its own; `runFlight` is the
 * browser half, and is deliberately dumb — it takes two points and animates a
 * card back between them.
 *
 * Flights are screen-space rather than room-space. They only ever run while
 * the camera is settled — the deal starts after the push-in finishes, and
 * play flights happen during a hand — so there is nothing for them to come
 * unglued from, and screen space saves every one of them a matrix.
 */

import type { Pt } from '../../clawd/gameBridge'
import { currentTier } from '../../clawd/quality'
import type { CardId } from './art'
import type { Seat, TableState } from './useGame'

/** The places a card can be. */
export type FlightSpot = 'deck' | 'discard' | 'rauHand' | 'playerHand'

export type FlightRequest = {
  from: FlightSpot
  to: FlightSpot
  /** Which card in the hand this is, so the deal can land them in order. */
  slot?: number
}

/**
 * Which slots in the new hand hold a card that was not there before.
 *
 * Not "the last one": the engine sorts a hand every time it gives a card, so a
 * drawn Defuse lands in the middle of your fan, not on the end. Counting
 * multiples is what makes that safe — with two Skips already in hand and a
 * third arriving, only one of the three slots is new, and it has to be the one
 * the card is flown to.
 */
export function arrivedSlots(before: CardId[], after: CardId[]): number[] {
  const spare = new Map<CardId, number>()
  for (const card of before) spare.set(card, (spare.get(card) ?? 0) + 1)
  const slots: number[] = []
  after.forEach((card, i) => {
    const held = spare.get(card) ?? 0
    if (held > 0) spare.set(card, held - 1)
    else slots.push(i)
  })
  return slots
}

/**
 * How long a card takes to cross the table.
 *
 * Most of it is spent arriving. The card leaves fast and then eases into its
 * place over the last fifth of the flight, which is the difference between a
 * card thrown at a spot and a card dealt to one.
 */
export const FLIGHT_MS = 380
/** Gap between cards in a dealt run. */
export const DEAL_STAGGER_MS = 72

function seatSpot(seat: Seat): FlightSpot {
  return seat === 'rau' ? 'rauHand' : 'playerHand'
}

/**
 * What moved, as cards to fly.
 *
 * Only the movements worth watching: a card off the deck into somebody's
 * hand, a card out of a hand onto the pile, a card handed over on a Favor.
 * Shuffles and peeks move nothing you can see.
 */
export function diffFlights(prev: TableState | null, next: TableState): FlightRequest[] {
  const out: FlightRequest[] = []
  if (!prev || prev.game_id !== next.game_id) return out

  const drawn = prev.deck_count - next.deck_count
  if (drawn > 0) {
    const rauGain = next.hand_counts.rau - prev.hand_counts.rau
    const youGain = next.hand.length - prev.hand.length
    for (let i = 0; i < Math.min(drawn, Math.max(0, rauGain)); i++) {
      out.push({ from: 'deck', to: 'rauHand' })
    }
    for (let i = 0; i < Math.min(drawn, Math.max(0, youGain)); i++) {
      out.push({ from: 'deck', to: 'playerHand' })
    }
  }

  const played = next.discard.length - prev.discard.length
  if (played > 0) {
    const from = seatSpot(prev.current)
    for (let i = 0; i < played; i++) out.push({ from, to: 'discard' })
  }

  // A Favor: one hand shrank, the other grew, and nothing hit the pile.
  if (played <= 0 && drawn <= 0) {
    if (next.hand.length < prev.hand.length && next.hand_counts.rau > prev.hand_counts.rau) {
      out.push({ from: 'playerHand', to: 'rauHand' })
    } else if (next.hand.length > prev.hand.length && next.hand_counts.rau < prev.hand_counts.rau) {
      out.push({ from: 'rauHand', to: 'playerHand' })
    }
  }

  return out
}

/** Whether the viewer has asked for none of this. */
export function reducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

export type FlightOptions = {
  delay?: number
  duration?: number
  /** Degrees the card turns as it travels. Gives it some weight. */
  spin?: number
  /**
   * How big the card is at each end, as a multiple of the flying card's own
   * width. The flying card is sized like the fan you hold, and the piles it
   * comes from are room objects a camera-length away — so a card dealt to you
   * genuinely grows on the way over, and one you throw at the discard pile
   * genuinely shrinks. Leaving these unset keeps the old near-uniform flight.
   */
  fromScale?: number
  toScale?: number
}

/**
 * Fly one card back from `from` to `to`, both in screen pixels.
 *
 * Cloned from a template the table renders once, so the card in flight is the
 * same drawing as the card that lands rather than an approximation of it.
 * Resolves when the card has arrived and been cleaned up.
 */
export function runFlight(
  layer: HTMLElement,
  template: HTMLElement,
  from: Pt,
  to: Pt,
  opts: FlightOptions = {},
): Promise<void> {
  if (reducedMotion()) return Promise.resolve()

  const el = template.cloneNode(true) as HTMLElement
  el.className = 'ek-flight'
  el.removeAttribute('id')
  el.setAttribute('aria-hidden', 'true')
  layer.appendChild(el)

  const spin = opts.spin ?? 0
  const place = (p: Pt, rot: number, scale: number) =>
    `translate(${p.x}px, ${p.y}px) translate(-50%, -50%) rotate(${rot}deg) scale(${scale})`

  const finish = () => {
    el.remove()
  }

  // `animate` is missing in a non-browser environment and behind a flag in
  // some older ones. Landing the card instantly beats throwing.
  if (typeof el.animate !== 'function') {
    finish()
    return Promise.resolve()
  }

  const s0 = opts.fromScale ?? 0.86
  const s1 = opts.toScale ?? 1

  /*
    The landing.

    A card that decelerates straight onto its mark stops dead, which is what
    an interpolation looks like. This one carries a little past the mark and
    is pulled back over the last fifth of the flight — the follow-through a
    real card has because it has mass. Three per cent of the distance is
    small enough that you never read it as an error and large enough that the
    stop is not the thing you notice. The low tier skips it: the point of
    that tier is fewer keyframes to composite, not a different table.
  */
  const settles = currentTier() !== 'low'
  const past = settles
    ? { x: to.x + (to.x - from.x) * 0.03, y: to.y + (to.y - from.y) * 0.03 }
    : to

  const anim = el.animate(
    [
      {
        transform: place(from, -spin / 2, s0 * 0.94),
        opacity: 0,
        offset: 0,
        easing: 'cubic-bezier(0.4, 0, 0.6, 1)',
      },
      {
        transform: place(from, -spin / 2, s0),
        opacity: 1,
        offset: 0.1,
        // Fast out: most of the ground is covered in the first half.
        easing: 'cubic-bezier(0.16, 0.78, 0.28, 1)',
      },
      {
        transform: place(past, (spin / 2) * 1.05, s1 * (settles ? 1.015 : 1)),
        opacity: 1,
        offset: 0.8,
        // Soft landing: it comes back to the mark rather than onto it.
        easing: 'cubic-bezier(0.33, 0, 0.2, 1)',
      },
      { transform: place(to, spin / 2, s1), opacity: 1, offset: 1 },
    ],
    {
      duration: opts.duration ?? FLIGHT_MS,
      delay: opts.delay ?? 0,
      fill: 'both',
    },
  )

  return new Promise<void>((resolve) => {
    const done = () => {
      finish()
      resolve()
    }
    anim.addEventListener('finish', done, { once: true })
    anim.addEventListener('cancel', done, { once: true })
  })
}
