/**
 * Cards moving between places.
 *
 * Split in two on purpose. `diffFlights` is a pure reading of what moved
 * between two table states and can be tested on its own; `runFlight` is the
 * browser half, and is deliberately dumb — it takes two points and an element
 * to clone, and animates the clone between them.
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
  /**
   * The card itself, when the diff could possibly know it: what landed on the
   * pile, what arrived in your hand. His draws and his cards stay anonymous,
   * and fly face-down.
   */
  card?: CardId
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
/** Gap between cards crossing the table together, outside the deal. */
export const FLIGHT_STAGGER_MS = 80
/**
 * How long the pile waits before turning a new top card over. The flip
 * itself is 280ms, so starting it this late has the face come around just as
 * the flight carrying that card lands. Set inline as `--ek-flip-delay`.
 */
export const FLIP_DELAY_MS = FLIGHT_MS - 120

function seatSpot(seat: Seat): FlightSpot {
  return seat === 'rau' ? 'rauHand' : 'playerHand'
}

/**
 * What moved, as cards to fly.
 *
 * Only the movements worth watching: a card off the deck into somebody's
 * hand, a card out of a hand onto the pile, a card handed over on a Favor, a
 * defused kitten going back into the deck. Shuffles and peeks move nothing
 * you can see.
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
    // Which cards arrived is only known on your side of the table.
    const arrived = arrivedSlots(prev.hand, next.hand).map((slot) => next.hand[slot])
    for (let i = 0; i < Math.min(drawn, Math.max(0, youGain)); i++) {
      out.push({ from: 'deck', to: 'playerHand', card: arrived[i] })
    }
  }

  const played = next.discard.length - prev.discard.length
  if (played > 0) {
    let from = seatSpot(prev.current)
    // A Nope is thrown by the seat the window was waiting on — never by
    // whoever holds the turn — so it flies out of the other hand.
    if (prev.pending && next.pending && next.pending.nopes > prev.pending.nopes) {
      from = seatSpot(prev.pending.waiting_on)
    }
    const thrown = next.discard.slice(prev.discard.length)
    for (let i = 0; i < played; i++) {
      // A kitten is never played from a hand: it comes off the deck already
      // face-up, and only the Defuse that answers it flies out of a fan.
      const card = thrown[i]
      out.push({ from: card === 'exploding_kitten' ? 'deck' : from, to: 'discard', card })
    }
  }

  // A defused kitten going home: it leaves the pile and the deck grows.
  if (
    next.deck_count > prev.deck_count &&
    prev.discard.includes('exploding_kitten') &&
    !next.discard.includes('exploding_kitten')
  ) {
    out.push({ from: 'discard', to: 'deck', card: 'exploding_kitten' })
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
 * Fly one card from `from` to `to`, both in screen pixels.
 *
 * Cloned from an element the table hands it — the hidden back template for
 * his cards, the real face for anything of yours — so the card in flight is
 * the same drawing as the card that lands rather than an approximation of it.
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

  /*
    The arc.

    A thrown card does not travel the straight line between two points: it
    comes off one place and drops onto the other. The lift is perpendicular
    to that line, always on the up side of the screen, and grows with the
    distance — across the table is a bigger throw than across the fan. The
    low tier skips it for the same reason it skips the settle: one fewer
    keyframe to composite.
  */
  const dx = to.x - from.x
  const dy = to.y - from.y
  const dist = Math.hypot(dx, dy)
  let apex: Pt | null = null
  if (settles && dist > 1) {
    const lift = Math.min(dist * 0.12, 90)
    let px = -dy / dist
    let py = dx / dist
    if (py > 0) {
      px = -px
      py = -py
    }
    apex = {
      x: from.x + (past.x - from.x) * 0.42 + px * lift,
      y: from.y + (past.y - from.y) * 0.42 + py * lift,
    }
  }

  const frames: Keyframe[] = [
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
  ]
  if (apex) {
    frames.push({
      transform: place(apex, 0, (s0 + s1) / 2),
      opacity: 1,
      offset: 0.45,
      // Over the top; everything from here is descent.
      easing: 'cubic-bezier(0.33, 0, 0.2, 1)',
    })
  }
  frames.push(
    {
      transform: place(past, (spin / 2) * 1.05, s1 * (settles ? 1.015 : 1)),
      opacity: 1,
      offset: 0.8,
      // Soft landing: it comes back to the mark rather than onto it.
      easing: 'cubic-bezier(0.33, 0, 0.2, 1)',
    },
    { transform: place(to, spin / 2, s1), opacity: 1, offset: 1 },
  )

  const anim = el.animate(frames, {
    duration: opts.duration ?? FLIGHT_MS,
    delay: opts.delay ?? 0,
    fill: 'both',
  })

  return new Promise<void>((resolve) => {
    const done = () => {
      finish()
      resolve()
    }
    anim.addEventListener('finish', done, { once: true })
    anim.addEventListener('cancel', done, { once: true })
  })
}
