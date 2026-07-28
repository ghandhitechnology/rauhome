/**
 * Getting him to the table, and what his body does once he is there.
 *
 * This is the whole of the ritual. Press Play and the deal is posted at once,
 * but nothing appears for three or four seconds while he perks up, walks
 * over, waits for the table to arrive, sits, and the camera pushes in. The
 * animation is not covering for a slow server — the table comes back almost
 * immediately — it is there because a game that simply appears is a game you
 * opened, and a game he sits down to is a game you are playing with him.
 *
 * The state machine is deliberately explicit rather than a chain of promises:
 * every one of these states can be interrupted from outside — leave mid-walk,
 * socket drops mid-deal, game over lands while the camera is still moving —
 * and a chain of `await`s has nowhere to put that.
 *
 * None of the above is about cards, and that is the point of taking the game
 * by construction. What differs between two tables is small and knowable: the
 * surface he sits at, the clip each beat of the game maps to, and which of
 * those beats outrank the queue or are meant to be held rather than tidied
 * away. Everything between the perk and standing back up is identical, and
 * had to stay that way — the second game gets the ritual that was tuned for
 * the first, or it gets a worse one.
 */

import { bodyController } from './body'
import { damp } from './easing'
import type { Director } from './director'
import { gameBridge, type GameResult, type GameVerb, type TableChoreo } from './gameBridge'
import { DEAL_DURATION, DEAL_FLICKS } from './motionsGame'
import type { MotionName } from './motions'
import type { ClawdRig } from './rig'
import { station } from './room'
import type { Scene } from './scene'
import type { TableShot, TableSurface } from './tableSurface'

export type ChoreoState =
  | 'idle'
  | 'perk'
  | 'walk'
  | 'sitting'
  | 'framing'
  | 'playing'
  | 'exiting'
  | 'standing'
  | 'releasing'

/** The body and the behaviour layer the ritual borrows while it runs. */
export type ChoreoDeps = { rig: ClawdRig; director: Director }

/** Everything about one game that the ritual itself cannot know. */
export type TableGame = {
  surface: TableSurface
  /** Which clip each of this game's beats plays. */
  verbClips: Record<string, MotionName>
  /** Beats that wipe whatever was queued behind them. */
  interrupting: Set<string>
  /**
   * Beats that are a state rather than an event.
   *
   * A finished one-shot holds its last frame for as long as you let it, and
   * for most beats that is a bug — he ends up frozen mid-gesture. For these
   * it is the whole point: the slump you are still looking at when you read
   * the result, or the claw left hovering over a square while he decides.
   */
  terminal: Set<string>
}

/**
 * Floor on the gap between beats, and how many may wait.
 *
 * The server can collapse several changes into one state push — he draws,
 * the turn passes, a Nope lands — and firing all of them at once reads as a
 * glitch rather than as three things happening.
 */
const BEAT_GAP = 0.8
const MAX_QUEUE = 3

/** Looking at his own cards on the table between beats. */
const TABLE_GAZE = { x: 0, y: 0.45, speed: 4, wander: 0.4 }
/** Up at you, because you said something while he was thinking. */
const GLANCE_GAZE = { x: 0, y: -0.35, speed: 12, wander: 0.15 }
const GLANCE_HOLD = 0.75

/** How close he has to be before the table fades in around him. */
const TABLE_NEAR = 14
/** Past this, the walk is worth hurrying. */
const HURRY_FROM = 25

export class GameChoreographer implements TableChoreo {
  state: ChoreoState = 'idle'
  /** 0..1 — how present the table prop is. */
  presence = 0
  /** 0..1 — how dark the rest of the room is. */
  dim = 0
  cameraTarget: TableShot | null = null

  private rig: ClawdRig
  private director: Director
  private game: TableGame
  /**
   * The same shot, approached slowly.
   *
   * Used while he is still walking, so the push-in has already begun by the
   * time he sits: one continuous move instead of a walk, a pause, and a zoom.
   */
  private approachShot: TableShot
  /** The last of the push, taken while he is on his way into the seat. */
  private seatingShot: TableShot
  private clock = 0
  private stateAt = 0

  private summonResolve: (() => void) | null = null
  private summonPromise: Promise<void> | null = null
  private dismissResolve: (() => void) | null = null
  private dismissPromise: Promise<void> | null = null

  private verbQueue: GameVerb[] = []
  private verbReadyAt = 0
  /** The flourish covers one lap of flicks; the deal runs until this time. */
  private dealUntil = 0
  /** Remembered so an exit knows which way the game went even if not told. */
  private result: GameResult = null
  private fast = false
  /** Set while a pose is meant to hold rather than settle back to the seat. */
  private holdingPose = false
  private glanceUntil = 0
  private lastChatSeen = 0
  private gazeIsGlance = false

  constructor(deps: ChoreoDeps, game: TableGame) {
    this.rig = deps.rig
    this.director = deps.director
    this.game = game
    const shot = game.surface.camera
    this.approachShot = { ...shot, lambda: shot.lambda * 0.28 }
    this.seatingShot = { ...shot, lambda: shot.lambda * 0.6 }
  }

  /** True while he owes the game his body. */
  get busy(): boolean {
    return this.state !== 'idle'
  }

  /** Which table this one seats him at. */
  get surface(): TableSurface {
    return this.game.surface
  }

  // ── the contract ────────────────────────────────────────────────────

  summon(): Promise<void> {
    if (this.state !== 'idle') return this.summonPromise ?? Promise.resolve()
    // The game outranks whatever the model had planned for the body, the same
    // way a human clicking a station does.
    bodyController.humanTakeover()
    this.director.manual = true
    this.director.holdGaze(true)
    this.result = null
    this.fast = false
    this.verbQueue.length = 0
    this.rig.play('perk', { force: true, restart: true })
    this.enter('perk')
    this.summonPromise = new Promise<void>((res) => {
      this.summonResolve = res
    })
    return this.summonPromise
  }

  seatInstantly() {
    if (this.state !== 'idle') return
    bodyController.humanTakeover()
    this.director.manual = true
    this.director.holdGaze(true)
    this.result = null
    this.verbQueue.length = 0
    // Straight into the seat: a reload is not an arrival.
    this.director.goTo('table')
    this.rig.worldX = station('table').x
    this.rig.facing = station('table').facing
    this.rig.play('sitTable', { force: true, restart: true })
    this.rig.setGaze(TABLE_GAZE)
    this.presence = 1
    this.dim = this.game.surface.dim
    this.cameraTarget = this.game.surface.camera
    this.enter('playing')
    this.resolveSummon()
  }

  startDeal(cards: number): number[] {
    const laps = Math.ceil(Math.max(0, cards) / DEAL_FLICKS.length)
    if (this.state === 'playing') {
      this.verbQueue.length = 0
      this.holdingPose = false
      this.rig.play('dealFlick', { force: true, restart: true })
      // The clip is one lap of flicks but the deal runs for several: it is
      // restarted in drainBeats until the last card has left, or he sits
      // motionless through most of his own deal.
      this.dealUntil = this.clock + laps * DEAL_DURATION
      this.verbReadyAt = this.clock + DEAL_DURATION + 0.2
    }
    // One flick per card, cycling if he is dealing more than the clip has
    // beats for — the last hand is eight cards and the clip has four.
    return Array.from({ length: Math.max(0, cards) }, (_, i) => {
      const lap = Math.floor(i / DEAL_FLICKS.length)
      const beat = DEAL_FLICKS[i % DEAL_FLICKS.length]
      return (lap * DEAL_DURATION + beat * DEAL_DURATION) * 1000
    })
  }

  dismiss(opts: { fast?: boolean; result?: GameResult } = {}): Promise<void> {
    if (this.state === 'idle') return Promise.resolve()
    if (this.state === 'exiting' || this.state === 'standing' || this.state === 'releasing') {
      return this.dismissPromise ?? Promise.resolve()
    }
    this.fast = !!opts.fast
    if (opts.result !== undefined && opts.result !== null) this.result = opts.result
    this.verbQueue.length = 0
    this.dismissPromise = new Promise<void>((res) => {
      this.dismissResolve = res
    })
    // He never sat down, so there is nothing to get up from.
    this.enter(this.state === 'perk' || this.state === 'walk' ? 'releasing' : 'exiting')
    return this.dismissPromise
  }

  /**
   * Drop whatever he is holding and go back to sitting there.
   *
   * Only from the seat: called during the walk it would be releasing a pose he
   * has not struck yet, and during an exit it would be undoing the last beat of
   * the game while he is still playing it.
   */
  settle() {
    if (this.state !== 'playing') return
    this.verbQueue.length = 0
    this.holdingPose = false
  }

  observe(verbs: GameVerb[]) {
    if (this.state === 'idle') return
    for (const v of verbs) {
      if (v === 'cheer') this.result = 'loss'
      if (v === 'slump') this.result = 'win'
      if (this.game.interrupting.has(v)) this.verbQueue.length = 0
      // A burst that repeats itself is one thing happening, not two.
      if (this.verbQueue[this.verbQueue.length - 1] === v) continue
      this.verbQueue.push(v)
      if (this.verbQueue.length > MAX_QUEUE) this.verbQueue.shift()
    }
  }

  // ── the loop ────────────────────────────────────────────────────────

  update(dt: number, scene: Scene) {
    this.clock += dt

    if (this.state === 'idle') {
      this.presence = damp(this.presence, 0, 4, dt)
      this.dim = damp(this.dim, 0, 3, dt)
      return
    }

    const shot = this.game.surface.camera
    const fullDim = this.game.surface.dim
    const table = station('table')
    const distance = Math.abs(table.x - this.rig.worldX)

    switch (this.state) {
      case 'perk':
        // Long enough to read as him noticing, short enough not to be a wait.
        if (this.clock - this.stateAt > 0.55) {
          this.director.goTo('table', { hurry: distance > HURRY_FROM })
          this.enter('walk')
        }
        break

      case 'walk':
        // The table arrives with him rather than waiting for him, so he is
        // never walking toward furniture that is not there yet.
        if (distance < TABLE_NEAR) {
          this.presence = damp(this.presence, 1, 2.4, dt)
          // And the camera leaves with him. Held until he was seated, the
          // push-in was a separate event that began after the walk ended —
          // one move, then a pause, then another move. Started here it is
          // the same move: the shot is already closing as he arrives, and
          // the room dims around a character who is still walking into it.
          // Slow at this range on purpose, so the arrival is what finishes
          // the push rather than the push finishing before he does.
          this.cameraTarget = this.approachShot
          this.dim = damp(this.dim, fullDim * 0.55, 1.6, dt)
        }
        if (this.director.isArrived) {
          this.rig.play('sit', { force: true, restart: true })
          this.enter('sitting')
        }
        break

      case 'sitting':
        this.presence = damp(this.presence, 1, 3, dt)
        this.dim = damp(this.dim, fullDim, 2, dt)
        // The camera closes the rest of the way as he goes down — quicker
        // than the approach, still slow enough that it is arriving *with*
        // him rather than waiting for him with the shot already set.
        this.cameraTarget = this.seatingShot
        // The walk stops within a deadband of the station, which is fine for
        // standing about and not fine here: his hands are the middle of the
        // shot, so the last unit is closed while he is on his way down.
        this.rig.worldX = damp(this.rig.worldX, table.x, 6, dt)
        if (!this.rig.busy) {
          this.rig.play('sitTable', { force: true, restart: true })
          this.rig.setGaze(TABLE_GAZE)
          this.enter('framing')
        }
        break

      case 'framing':
        this.presence = damp(this.presence, 1, 3, dt)
        this.dim = damp(this.dim, fullDim, 2.2, dt)
        // Tighter than the old 0.06: with the push already most of the way
        // done by the time he sits, a loose threshold would hand the deal a
        // camera that is still visibly moving.
        if (Math.abs(scene.camera.zoom - shot.zoom) < 0.02) {
          // Back to the canonical shot now the slow approach has done its
          // work: anything that nudges the camera during the hand should get
          // the full response, not the walking-in one.
          this.cameraTarget = shot
          this.enter('playing')
          this.resolveSummon()
        }
        break

      case 'playing':
        this.presence = damp(this.presence, 1, 3, dt)
        this.dim = damp(this.dim, fullDim, 2.2, dt)
        this.updateGaze()
        this.drainBeats()
        break

      case 'exiting':
        // One last beat for how it went, then out of the seat.
        if (!this.fast && this.result && !this.rig.busy && this.clock - this.stateAt < 0.1) {
          this.rig.play(this.result === 'loss' ? 'sitCheer' : 'slumpLoss', {
            force: true,
            restart: true,
          })
        }
        this.dim = damp(this.dim, 0, this.fast ? 4 : 2, dt)
        if (!this.rig.busy) {
          this.cameraTarget = null
          this.rig.setGaze(null)
          this.rig.play('standUp', { force: true, restart: true })
          this.enter('standing')
        }
        break

      case 'standing':
        this.dim = damp(this.dim, 0, this.fast ? 4 : 2, dt)
        if (!this.rig.busy) {
          this.presence = damp(this.presence, 0, this.fast ? 5 : 2.6, dt)
          if (this.presence < 0.02) {
            // He gets to be pleased about it on his feet, too.
            if (!this.fast && this.result === 'loss') {
              this.rig.play('celebrate', { force: true, restart: true })
            }
            this.enter('releasing')
          }
        }
        break

      case 'releasing':
        this.presence = damp(this.presence, 0, 5, dt)
        this.dim = damp(this.dim, 0, 4, dt)
        this.cameraTarget = null
        this.release()
        break
    }
  }

  // ── internals ───────────────────────────────────────────────────────

  private enter(state: ChoreoState) {
    this.state = state
    this.stateAt = this.clock
  }

  private resolveSummon() {
    const done = this.summonResolve
    this.summonResolve = null
    this.summonPromise = null
    done?.()
  }

  /**
   * Hand the room back.
   *
   * `manual` has to come off here and nowhere else: leaving it set is how a
   * game that ended badly turns into a character who never moves again.
   */
  private release() {
    this.director.manual = false
    this.director.holdGaze(false)
    // The walk over was a directed goTo: with the table gone the destination
    // is too, and finishing the trip would sit him down at bare floor.
    this.director.cancelDirected()
    this.rig.setGaze(null)
    this.rig.play('idle', { force: true })
    this.gazeIsGlance = false
    this.verbQueue.length = 0
    this.holdingPose = false
    this.result = null
    this.enter('idle')
    // A begin() still awaiting its seat is answered too — the game it was
    // walking to is gone, and waiting on it would wedge the table for good.
    this.resolveSummon()
    const done = this.dismissResolve
    this.dismissResolve = null
    this.dismissPromise = null
    done?.()
  }

  private drainBeats() {
    if (this.verbQueue.length === 0) {
      // A finished one-shot holds its last frame for as long as you let it,
      // so without this every beat ends with him frozen mid-gesture until the
      // next one happens to arrive. The terminal poses are the exception: he
      // is meant to still be slumped when you read the result, and still
      // reaching over the board while he decides where to put the piece.
      if (!this.rig.busy && !this.holdingPose && this.rig.currentMotion !== 'sitTable') {
        if (this.clock < this.dealUntil) {
          // One clip is one lap of flicks; the deal runs for several.
          this.rig.play('dealFlick', { force: true, restart: true })
        } else {
          this.rig.play('sitTable', { force: true })
        }
      }
      return
    }
    if (this.rig.busy || this.clock < this.verbReadyAt) return
    const verb = this.verbQueue.shift()
    if (!verb) return
    const clip = this.game.verbClips[verb]
    // A verb this table has no clip for is a wiring bug on the game side, and
    // silently doing nothing is better than throwing inside the render loop.
    if (!clip) return
    this.holdingPose = this.game.terminal.has(verb)
    this.rig.play(clip, { force: true, restart: true })
    this.verbReadyAt = this.clock + BEAT_GAP
  }

  /**
   * Where he is looking.
   *
   * A card the player is hovering is handled by the room, which hands the rig
   * a `lookAt` point that outranks any aim set here. This covers the other
   * two cases: glancing up when spoken to, and otherwise watching the table.
   */
  private updateGaze() {
    if (gameBridge.userChattedAt > this.lastChatSeen) {
      this.lastChatSeen = gameBridge.userChattedAt
      this.glanceUntil = this.clock + GLANCE_HOLD
    }
    const glancing = this.clock < this.glanceUntil
    if (glancing === this.gazeIsGlance) return
    this.gazeIsGlance = glancing
    this.rig.setGaze(glancing ? GLANCE_GAZE : TABLE_GAZE)
  }
}
