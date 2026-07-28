/**
 * The board, client side, and the table it is standing on.
 *
 * Two stores, because they answer two questions that come apart. `gameStore`
 * knows what is on the board and whose move it is; `phaseStore` knows whether
 * he has walked over and sat down yet. A game exists on the server the instant
 * you press Play, but for three or four seconds after that there is nothing on
 * screen but a crab crossing a room, and the pieces must not appear until they
 * have a table to stand on. They live in one file because chess has no dealing
 * flourish between the two — the position simply arrives — and a second module
 * holding four lines would only be somewhere else to look.
 *
 * Everything here is *received*. Chess is perfect information, so unlike the
 * card table there is nothing to redact, and the temptation is the opposite
 * one: to work things out locally because the client now has everything it
 * would need to. It does not. There is no `legal_moves` field on the wire and
 * there is none computed here — the board sends two square names and finds out
 * from the server whether that was a move. That is the whole reason a refusal
 * is worth showing rather than preventing: being told *why* by the person
 * sitting opposite is the game.
 */

import { useEffect, useState } from 'react'
import { api } from '../../api'
import { gameBridge, type GameResult } from '../../clawd/gameBridge'
import { CHESS_SURFACE } from '../../clawd/chessTableLayer'
import { live } from '../../live'

export type Seat = 'user' | 'rau'
export type Color = 'white' | 'black'

export type Phase =
  /** Somebody's move, nothing in flight. */
  | 'playing'
  /** His delay is running and the hover script is playing. */
  | 'thinking'
  | 'over'

export type LastMove = { from: string; to: string; san: string }
export type Offer = { by: Seat; kind: 'draw' }
/**
 * Who a log line is attributed to.
 *
 * Wider than `Seat`, and deliberately: the board itself says things neither
 * player did — "Position restored." after a reload, the result when a game
 * ends — and those arrive from `rau/games/chess/journal.py` as `"table"`.
 * Typing this as `Seat` would be a lie the compiler happily agrees with, right
 * up until something switches on it.
 */
export type LogSeat = Seat | 'table'

export type LogEntry = { seat: LogSeat; text: string; at: number }

export type TableState = {
  game_id: string
  phase: Phase
  fen: string
  turn: Color
  rau_color: Color
  user_color: Color
  your_turn: boolean
  /** SAN, in order. */
  moves: string[]
  last_move: LastMove | null
  /** The square of the king in check, if one is. */
  check_square: string | null
  /** Only while the phase is `thinking`. `hover` is a square he is eyeing. */
  thinking: { hover: string | null } | null
  offer: Offer | null
  result: string | null
  /** Null on a draw, and on a game still going. */
  winner: Seat | null
  over_reason: string
  can_claim_draw: boolean
  log: LogEntry[]
}

export type Promotion = 'q' | 'r' | 'b' | 'n'

export type Move =
  | { move: 'move'; from: string; to: string; promotion?: Promotion | null }
  | { move: 'resign' }
  | { move: 'offer_draw' }
  | { move: 'accept_draw' }
  | { move: 'decline_draw' }
  | { move: 'claim_draw' }

type Listener = () => void

/**
 * A refusal, as he said it.
 *
 * The hub answers an illegal move with `400` and a JSON body, and `api.req`
 * hands that body up as the message of an `Error` — so without this the board
 * would show you a line of JSON where a sentence should be. The `error` field
 * is written to be spoken across a table, which is exactly what the strip
 * under the board wants.
 */
function refusal(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)
  try {
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && 'error' in parsed) {
      const message = (parsed as { error?: unknown }).error
      if (typeof message === 'string' && message) return message
    }
  } catch {
    /* not JSON — a network failure or a proxy page, and the text is the best
       thing there is to show. */
  }
  return raw
}

class GameStore {
  private state: TableState | null = null
  private listeners = new Set<Listener>()
  /** Set while a move is in flight, so a double click cannot send two. */
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
      const data = await api.chess()
      this.set((data.state as TableState) ?? null)
    } catch {
      /* hub down — leave whatever we last saw on screen */
    }
  }

  /**
   * Set the pieces up.
   *
   * No colour is asked for, deliberately. The server resumes an unfinished
   * game if there is one; otherwise the colours alternate from the last
   * finished game, the way they do between two people at a real board. The
   * very first game he takes black, so the person who just sat down opens.
   */
  async start(): Promise<void> {
    const data = await api.startChess()
    this.set((data.state as TableState) ?? null)
  }

  async leave(): Promise<void> {
    await api.endChess().catch(() => {})
    this.set(null)
  }

  /**
   * Send a move, or a resignation, or an answer to a draw offer.
   *
   * The response carries the new position, so the common case needs no round
   * trip through the socket. A refusal is kept and shown rather than
   * swallowed: he also says it out loud, and the two arriving together is what
   * makes a piece snapping back read as him objecting rather than as a bug.
   */
  async play(move: Move): Promise<boolean> {
    if (this.busy) return false
    this.busy = true
    this.lastError = ''
    this.notify()
    try {
      const data = await api.chessMove(move)
      if (data.state) this.set(data.state as TableState)
      return true
    } catch (err) {
      this.lastError = refusal(err)
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
 * The `game` key is the whole point of the guard. Two tables now push the same
 * four event names down the same socket, and a store that accepted any of them
 * would happily set a hand of cards as its chess position the first time
 * somebody played the other game.
 */
live.subscribe((event) => {
  if (event.game !== 'chess') return
  if (event.kind === 'game_started' || event.kind === 'game_state' || event.kind === 'game_over') {
    if (event.state) gameStore.set(event.state as TableState)
  } else if (event.kind === 'game_ended') {
    gameStore.set(null)
  }
})

/** Subscribe a component to the board. */
export function useGame(): {
  table: TableState | null
  busy: boolean
  error: string
} {
  const [, bump] = useState(0)
  useEffect(() => gameStore.subscribe(() => bump((n) => n + 1)), [])
  return { table: gameStore.get(), busy: gameStore.isBusy, error: gameStore.error }
}

/* ─────────────────────────────────────────────── the table's own life */

export type TablePhase =
  /** No board. The room is his. */
  | 'idle'
  /** Play pressed: the position is in flight and so is he. */
  | 'summoning'
  /** He is seated and the pieces are up. */
  | 'playing'
  /** Standing up, camera pulling back, board going away. */
  | 'ending'

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
        /* as above */
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
   * The surface is raised before the ritual starts and taken down after it
   * ends, in that order, because both the room's paint and the choreographer
   * the bridge routes to are chosen from whichever table is currently up. Ask
   * him to walk over first and he spends the walk sitting down at a card
   * table.
   *
   * The request goes out alongside the walk rather than before it, so the
   * network is never waiting on the animation and the animation is never
   * waiting on the network.
   */
  async begin(): Promise<void> {
    if (this.phase !== 'idle') return
    this.lastError = ''
    this.set('summoning')
    gameBridge.activate(CHESS_SURFACE)

    const opened = gameStore.start().then(
      () => true,
      (err: unknown) => {
        this.lastError = refusal(err)
        return false
      },
    )
    const seated = gameBridge.choreography?.summon() ?? Promise.resolve()
    const [ok] = await Promise.all([opened, seated])

    if (!ok) {
      await this.end({ fast: true })
      this.notify()
      return
    }
    // Left the board while he was still walking to it.
    if (this.get() !== 'summoning') return
    this.set('playing')
  }

  /**
   * A game was already in progress — a reload, or coming back to the room.
   *
   * No ritual: he did not just decide to play, he has been sitting there the
   * whole time and you went away.
   */
  adopt(): void {
    if (this.phase !== 'idle') return
    gameBridge.activate(CHESS_SURFACE)
    gameBridge.choreography?.seatInstantly()
    this.set('playing')
  }

  /**
   * A board appeared that this page did not ask for.
   *
   * He set it up himself — `start_chess`, in the middle of a conversation — so
   * he gets the whole walk over, minus the request nobody here made.
   */
  async arrive(): Promise<void> {
    if (this.phase !== 'idle') return
    this.set('summoning')
    gameBridge.activate(CHESS_SURFACE)
    await (gameBridge.choreography?.summon() ?? Promise.resolve())
    if (this.get() !== 'summoning') return
    this.set('playing')
  }

  /**
   * Set them up again from the game-over card. He is already seated.
   *
   * The pose has to be let go of by hand. `cheer` and `slump` are held rather
   * than tidied away — that is what makes them readable while you take the
   * result in — and a second game is not a beat, so nothing else would ever
   * release them. He would set the pieces up still folded over the last game.
   */
  async again(): Promise<void> {
    if (this.phase !== 'playing') return
    this.lastError = ''
    try {
      await gameStore.start()
      gameBridge.choreography?.settle()
    } catch (err) {
      this.lastError = refusal(err)
      this.notify()
    }
  }

  /**
   * Give the room back.
   *
   * Only if it is still this table's to give. The server swaps the two games
   * either way round — the cards come out and the board is put away — and the
   * one arriving raises its surface while the one leaving is still getting to
   * its feet. Handing the room back unconditionally would take the new table
   * down with the old one.
   */
  async end(opts: { fast?: boolean; result?: GameResult } = {}): Promise<void> {
    if (this.phase === 'idle' || this.phase === 'ending') return
    this.set('ending')
    await (gameBridge.choreography?.dismiss(opts) ?? Promise.resolve())
    if (gameBridge.surface === CHESS_SURFACE) {
      gameBridge.activate(null)
      gameBridge.hoverPoint = null
    }
    this.set('idle')
  }

  /**
   * Leave mid-game: clear the server board and unwind the room together.
   *
   * The unwind is started *first*, and that ordering is load-bearing. Clearing
   * the board trips the watchdog below, which stands him up with no result and
   * no ceremony — correct when the game vanished on its own, wrong when you
   * pressed Leave on a game you had just won. Whichever call gets there first
   * decides how he gets out of the chair, so it may as well be the one that
   * knows how it went.
   */
  async leave(result: GameResult = null): Promise<void> {
    const unwind = this.end({ result })
    void gameStore.leave().catch(() => {})
    await unwind
  }
}

export const phaseStore = new PhaseStore()

/**
 * A board that disappears out from under him — `game_ended` from the hub, or
 * the socket handing back an empty room — still has to put him back on his
 * feet. Only a real transition counts: the table is null before the first
 * position lands too, and ending on that would cancel the ritual that is still
 * starting.
 */
let hadBoard = gameStore.get() !== null
gameStore.subscribe(() => {
  const has = gameStore.get() !== null
  if (hadBoard && !has && phaseStore.get() === 'playing') {
    void phaseStore.end({ fast: true })
  }
  hadBoard = has
})

/** Subscribe a component to the table's own state. */
export function usePhase(): TablePhase {
  const [, bump] = useState(0)
  useEffect(() => phaseStore.subscribe(() => bump((n) => n + 1)), [])
  return phaseStore.get()
}
