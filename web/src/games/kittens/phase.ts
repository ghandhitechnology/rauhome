/**
 * Where the table is in its own life, as distinct from where the *game* is.
 *
 * `useGame` knows whose turn it is. This knows whether he has sat down yet.
 * They are genuinely different questions: a game exists on the server the
 * instant you press Play, but for three or four seconds after that there is
 * nothing on screen but a crab walking across a room, and the cards must not
 * appear until he is behind the table they are lying on.
 *
 * Same store shape as `useGame` and `panels` — a plain singleton with
 * subscribers, so the room has one idea about when a re-render happens.
 */

import { useEffect, useState } from 'react'
import { gameBridge, type GameResult } from '../../clawd/gameBridge'
import { gameStore } from './useGame'

export type TablePhase =
  /** No table. The room is his. */
  | 'idle'
  /** Play pressed: the deal is in flight and so is he. */
  | 'summoning'
  /** He is seated and dealing; cards are flying to their places. */
  | 'dealing'
  /** A hand is on. */
  | 'playing'
  /** Standing up, camera pulling back, table going away. */
  | 'ending'

type Listener = () => void

class PhaseStore {
  private phase: TablePhase = 'idle'
  private listeners = new Set<Listener>()
  private lastError = ''

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  private notify() {
    for (const fn of [...this.listeners]) {
      try {
        fn()
      } catch {
        /* one bad view must not stop the rest updating */
      }
    }
  }

  get(): TablePhase {
    return this.phase
  }

  get error(): string {
    return this.lastError
  }

  clearError() {
    if (!this.lastError) return
    this.lastError = ''
    this.notify()
  }

  private set(next: TablePhase) {
    if (this.phase === next) return
    this.phase = next
    this.notify()
  }

  /**
   * Press Play.
   *
   * The deal is posted immediately and the ritual runs alongside it, so the
   * walk is never waiting on the network and the network is never waiting on
   * the walk. Whichever finishes last is when the cards may appear.
   */
  async begin(): Promise<void> {
    if (this.phase !== 'idle') return
    this.lastError = ''
    this.set('summoning')
    gameBridge.active = true

    const dealt = gameStore.deal().then(
      () => true,
      (err: unknown) => {
        this.lastError = err instanceof Error ? err.message : String(err)
        return false
      },
    )
    const seated = gameBridge.choreography?.summon() ?? Promise.resolve()
    const [ok] = await Promise.all([dealt, seated])

    if (!ok) {
      await this.end({ fast: true })
      this.notify()
      return
    }
    // Left the table while he was still walking to it.
    if (this.get() !== 'summoning') return
    this.set('dealing')
  }

  /**
   * A game was already in progress — a reload, or coming back to the room.
   *
   * No ritual: he did not just decide to play, he has been sitting there the
   * whole time and you went away.
   *
   * Safe to call over a game already adopted: a choreographer mid-ritual
   * ignores the seating, and a *fresh* one — the room was navigated away from
   * mid-game and come back to, leaving the phase 'playing' — is sat down
   * where the last room had him.
   */
  adopt(): void {
    gameBridge.active = true
    gameBridge.choreography?.seatInstantly()
    if (this.phase === 'idle') this.set('playing')
  }

  /**
   * A table appeared that this page did not ask for.
   *
   * He dealt himself in — `start_kittens`, on his own turn — so he gets the
   * whole ritual, minus the deal nobody here posted.
   */
  async arrive(): Promise<void> {
    if (this.phase !== 'idle') return
    this.set('summoning')
    gameBridge.active = true
    await (gameBridge.choreography?.summon() ?? Promise.resolve())
    if (this.get() !== 'summoning') return
    this.set('dealing')
  }

  /** Deal again from the game-over card. He is already seated. */
  async redeal(): Promise<void> {
    if (this.phase !== 'playing') return
    this.lastError = ''
    try {
      await gameStore.deal()
    } catch (err) {
      this.lastError = err instanceof Error ? err.message : String(err)
      this.notify()
      return
    }
    if (this.get() !== 'playing') return
    this.set('dealing')
  }

  /** The table reports every dealt card has landed. */
  dealt(): void {
    if (this.phase === 'dealing') this.set('playing')
  }

  /** Give the room back. */
  async end(opts: { fast?: boolean; result?: GameResult } = {}): Promise<void> {
    if (this.phase === 'idle' || this.phase === 'ending') return
    this.set('ending')
    await (gameBridge.choreography?.dismiss(opts) ?? Promise.resolve())
    gameBridge.active = false
    gameBridge.hoverPoint = null
    this.set('idle')
  }

  /** Leave mid-game: clear the server table and unwind the room together. */
  async leave(result: GameResult = null): Promise<void> {
    void gameStore.leave().catch(() => {})
    await this.end({ result })
  }
}

export const phaseStore = new PhaseStore()

/**
 * A game that disappears out from under the table — `game_ended` from the
 * hub, or the socket handing back an empty room — still has to put him back
 * on his feet. Only a real transition counts: the table is null before the
 * first deal lands too, and ending on that would cancel the ritual that is
 * still starting. Every live phase ends, summoning most of all: the walk
 * must never complete into a game that no longer exists.
 */
let hadTable = gameStore.get() !== null
gameStore.subscribe(() => {
  const has = gameStore.get() !== null
  if (hadTable && !has) {
    // end() already ignores idle/ending, so there is nothing to gate on here.
    void phaseStore.end({ fast: true })
  }
  hadTable = has
})

/** Subscribe a component to the table's own state. */
export function usePhase(): TablePhase {
  const [, bump] = useState(0)
  useEffect(() => phaseStore.subscribe(() => bump((n) => n + 1)), [])
  return phaseStore.get()
}
