/**
 * The table, client side.
 *
 * A plain store rather than context, for the same reason `panels.ts` is one: the
 * room already has a subscription model and a second one would only give the two
 * different ideas about when a re-render happens.
 *
 * Everything here is *received*. The client never computes what is legal, never
 * decides whose turn it is, and never holds a card the server did not hand it —
 * the state that arrives over the socket is already redacted to this seat, so
 * there is nothing here to leak even by accident.
 */
import { useEffect, useRef, useState, type RefObject } from 'react'
import { api } from '../../api'
import { live } from '../../live'
import type { CardId } from './art'

export type Seat = 'user' | 'rau'

export type Phase =
  | 'playing'
  | 'nope_window'
  | 'awaiting_favor'
  | 'awaiting_defuse'
  | 'awaiting_named_card'
  | 'awaiting_discard_pick'
  | 'over'

export type PendingAction = {
  action_id: string
  actor: Seat
  kind: 'card' | 'combo_two' | 'combo_three' | 'combo_five'
  cards: CardId[]
  named_card?: CardId | null
  nopes: number
  waiting_on: Seat
  /** Unix seconds. The countdown is derived from this, never pushed as ticks. */
  deadline: number
}

export type LogEntry = { seat: Seat; text: string; at: number }

export type TableState = {
  game_id: string
  seat: Seat
  phase: Phase
  current: Seat
  turns_to_take: number
  deck_count: number
  discard: CardId[]
  hand: CardId[]
  hand_counts: Record<Seat, number>
  known_top: CardId[]
  awaiting_seat: Seat | null
  pending: PendingAction | null
  winner: Seat | null
  over_reason: string
  your_turn: boolean
  awaiting_you: boolean
  can_nope: boolean
  insert_max?: number
  final_hands?: Record<Seat, CardId[]>
  log: LogEntry[]
}

export type Move =
  | { move: 'play'; card: CardId }
  | { move: 'combo'; cards: CardId[]; named_card?: CardId }
  | { move: 'draw' }
  | { move: 'nope' }
  | { move: 'pass_nope' }
  | { move: 'give_favor'; card: CardId }
  | { move: 'take_from_discard'; card: CardId }
  | { move: 'insert_kitten'; index: number }
  | { move: 'concede' }

type Listener = () => void

class GameStore {
  private state: TableState | null = null
  private listeners = new Set<Listener>()
  /** Set while a move is in flight, so double-clicks cannot double-play a card. */
  private busy = false
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

  get(): TableState | null {
    return this.state
  }

  get isBusy(): boolean {
    return this.busy
  }

  get error(): string {
    return this.lastError
  }

  set(state: TableState | null) {
    this.state = state
    this.notify()
  }

  /** Load whatever is on the table. Used on mount and after a reconnect. */
  async refresh(): Promise<void> {
    try {
      const data = await api.kittens()
      this.set((data.state as TableState) ?? null)
    } catch {
      /* hub down — leave whatever we last saw on screen */
    }
  }

  async deal(): Promise<void> {
    const data = await api.dealKittens()
    this.set((data.state as TableState) ?? null)
  }

  async leave(): Promise<void> {
    await api.endKittens().catch(() => {})
    this.set(null)
  }

  /**
   * Send a move.
   *
   * The response carries the new table, so the common case needs no round trip
   * through the socket. A refusal is kept and shown rather than swallowed —
   * being told *why* a card cannot be played is most of learning the game.
   */
  async play(move: Move): Promise<boolean> {
    if (this.busy) return false
    this.busy = true
    this.lastError = ''
    this.notify()
    try {
      const data = await api.kittensMove(move)
      if (data.state) this.set(data.state as TableState)
      return true
    } catch (err) {
      this.lastError = err instanceof Error ? err.message : String(err)
      return false
    } finally {
      this.busy = false
      this.notify()
    }
  }

  clearError() {
    if (!this.lastError) return
    this.lastError = ''
    this.notify()
  }
}

export const gameStore = new GameStore()

/**
 * The socket, filtered to this game.
 *
 * The `game` key is the whole point of the guard. There is a second table in
 * the room now, pushing the same four event names down the same socket, and a
 * store that accepted any of them would set a chess position as its hand of
 * cards the first time somebody played the other game.
 */
live.subscribe((event) => {
  if (event.game !== 'kittens') return
  if (event.kind === 'game_started' || event.kind === 'game_state' || event.kind === 'game_over') {
    if (event.state) gameStore.set(event.state as TableState)
  } else if (event.kind === 'game_ended') {
    gameStore.set(null)
  }
})

/** Subscribe a component to the table. */
export function useGame(): {
  table: TableState | null
  busy: boolean
  error: string
} {
  const [, bump] = useState(0)
  useEffect(() => gameStore.subscribe(() => bump((n) => n + 1)), [])
  return { table: gameStore.get(), busy: gameStore.isBusy, error: gameStore.error }
}

/**
 * Seconds left in the Nope window, recomputed locally from the deadline.
 *
 * Driven by `requestAnimationFrame` rather than by server ticks: a countdown
 * that stuttered every time the socket was quiet would read as lag in the game
 * rather than in the network.
 */
/**
 * A deadline, as a CSS variable on one element.
 *
 * A countdown is a number that changes sixty times a second, and routed
 * through React state that is sixty renders a second for five seconds —
 * during the one moment of the game where you are being asked to react
 * quickly. The ring only ever needed a number to draw an arc from, so the
 * number goes straight onto the node that draws it and React is left out of
 * it. Anything that needs the value as *content* — a digit counting down —
 * would want state instead.
 */
export function useCountdownVar(
  deadline: number | null,
  total: number,
  name = '--left',
): RefObject<HTMLElement | null> {
  const ref = useRef<HTMLElement | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (!deadline) {
      el.style.setProperty(name, '0')
      return
    }
    let frame = 0
    const step = () => {
      const left = Math.max(0, deadline * 1000 - Date.now())
      el.style.setProperty(name, String(Math.min(1, left / total)))
      frame = requestAnimationFrame(step)
    }
    step()
    return () => cancelAnimationFrame(frame)
  }, [deadline, total, name])
  return ref
}
