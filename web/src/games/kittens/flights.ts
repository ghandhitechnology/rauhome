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
import type { Seat, TableState } from './useGame'

/** The places a card can be. */
export type FlightSpot = 'deck' | 'discard' | 'rauHand' | 'playerHand'

export type FlightRequest = {
  from: FlightSpot
  to: FlightSpot
  /** Which card in the hand this is, so the deal can land them in order. */
  slot?: number
}

/** How long a card takes to cross the table. */
export const FLIGHT_MS = 420
/** Gap between cards in a dealt run. */
export const DEAL_STAGGER_MS = 90

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

  const anim = el.animate(
    [
      { transform: place(from, -spin / 2, 0.86), opacity: 0 },
      { transform: place(from, -spin / 2, 0.92), opacity: 1, offset: 0.12 },
      { transform: place(to, spin / 2, 1), opacity: 1 },
    ],
    {
      duration: opts.duration ?? FLIGHT_MS,
      delay: opts.delay ?? 0,
      easing: 'cubic-bezier(0.24, 0.72, 0.24, 1)',
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
