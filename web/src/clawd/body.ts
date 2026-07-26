/**
 * Model-authored body choreography, client side.
 *
 * The face model plans a handful of cues for the reply it is about to speak
 * (see `rau/face/choreography.py`); this is the piece that decides *when* each
 * one fires and hands it to every avatar mounted on the page at once, so the
 * character in the room and the little one in the corner do the same thing.
 *
 * A cue fires when its anchor becomes *visible* — the first token of the
 * reply, an exact phrase within it, or the end of it. In chat that means text
 * arriving; in voice it means playback crossing the character timestamp for
 * that phrase. Both paths land here as "this much of the reply has now
 * reached the user", which is the only definition under which the gesture and
 * the words line up.
 *
 * Priority, highest first:
 *   1. the human — the Direct panel, or poking the character
 *   2. an interruption, a superseded turn, or an expired plan
 *   3. the active cue
 *   4. the autonomous director
 */

import type { MotionName } from './motions'
import type { GazeAim } from './rig'
import type { StationId } from './room'

/** Clips a plan may name. Mirrors `MOTIONS` in rau/face/choreography.py. */
export const BODY_MOTIONS = [
  'idle',
  'walk',
  'wave',
  'type',
  'bounce',
  'think',
  'sleep',
  'talk',
  'celebrate',
  'startle',
  'gaze',
  'listen',
  'nod',
  'perk',
  'recoil',
  'shrug',
  'stretch',
  'shuffle',
] as const satisfies readonly MotionName[]

/** Places a plan may name. Mirrors `STATIONS` in rau/face/choreography.py. */
export const BODY_STATIONS = [
  'window',
  'plant',
  'centre',
  'desk',
  'shelf',
] as const satisfies readonly StationId[]

/** Semantic gaze targets. Mirrors `GAZE_TARGETS` in rau/face/choreography.py. */
export const GAZE_TARGETS = [
  'user',
  'away',
  'room',
  'floor',
  'up',
  'screen',
  'window',
] as const

export type GazeTarget = (typeof GAZE_TARGETS)[number]

/**
 * Where each semantic target actually points the eyes. The model never writes
 * eye coordinates — it names an intent and this is where that intent lives.
 */
export const GAZE_AIMS: Record<GazeTarget, GazeAim> = {
  user: { x: 0, y: 0.08, speed: 9, wander: 0.25 },
  away: { x: -0.6, y: -0.5, speed: 2.2, wander: 0.9 },
  room: { x: 0.7, y: 0, speed: 3, wander: 0.7 },
  floor: { x: 0, y: 0.85, speed: 4, wander: 0.3 },
  up: { x: 0, y: -0.85, speed: 3.5, wander: 0.4 },
  screen: { x: 0.8, y: 0.15, speed: 5, wander: 0.2 },
  window: { x: -0.9, y: -0.2, speed: 3, wander: 0.5 },
}

export type BodyAnchor = 'now' | 'reply_start' | 'phrase' | 'reply_end'

export type BodyCue = {
  anchor: BodyAnchor
  /** Only on anchor=phrase. Matched case- and whitespace-insensitively. */
  phrase?: string
  /** Which occurrence of a repeated phrase, 1-based. */
  occurrence?: number
  motion?: MotionName
  gaze?: GazeTarget
  station?: StationId
  /** How long this cue owns the body, milliseconds. */
  hold_ms: number
}

export type BodyPlan = {
  turn_id: string
  plan_id: string
  cues: BodyCue[]
  /** Hard lifetime of the whole plan; unfired cues are dropped past it. */
  expires_ms?: number
}

/** One mounted avatar. The controller owns the timing, the target the look. */
export type BodyTarget = {
  /** Take the body for one cue. */
  applyCue: (cue: BodyCue) => void
  /** Hand it back to autonomous behaviour. */
  releaseCue: () => void
  /**
   * True when this target walks across a room and will call `cueArrived`
   * once it lands. Station holds wait for that signal when any such target
   * is registered; compact avatars omit it and keep the immediate hold.
   */
  reportsArrival?: boolean
}

/** Where a text advance came from — audio wins, and text never overrides it. */
export type CueSource = 'text' | 'audio'

/** Matches the server's MAX_PLAN_MS; used when an event omits its own. */
export const DEFAULT_PLAN_TTL_MS = 120_000

/** Longest walk-on-the-spot a compact avatar plays in place of locomotion. */
export const WALK_IN_PLACE_MS = 900

/** What a compact avatar does with a cue: travel for a while, then gesture. */
export type CompactStep = { walkMs: number; motion: MotionName | null }

/**
 * Read a cue at the size of an avatar with no room to walk across.
 *
 * A station becomes a bounded walk on the spot before the gesture, so the same
 * command reads the same way in the corner of the dashboard as it does in the
 * full scene — never longer than the cue's own hold, and never so long that
 * the gesture it was leading up to gets cut off.
 */
export function compactCue(cue: BodyCue): CompactStep {
  const motion = cue.motion ?? null
  if (!cue.station) return { walkMs: 0, motion }
  return {
    walkMs: Math.max(0, Math.min(WALK_IN_PLACE_MS, cue.hold_ms * 0.45)),
    motion,
  }
}

/**
 * Case- and whitespace-insensitive form used on both sides of a phrase match.
 * Model output and rendered text disagree about runs of whitespace far more
 * often than they disagree about words.
 */
export function normalizePhrase(text: string): string {
  return text.toLowerCase().replace(/\s+/g, ' ').trim()
}

/**
 * Whether the nth occurrence of `phrase` has fully arrived in `visible`.
 * Occurrences do not overlap: "ha" occurs twice in "hahaha", not three times.
 */
export function phraseVisible(visible: string, phrase: string, occurrence = 1): boolean {
  const needle = normalizePhrase(phrase)
  if (!needle) return false
  const hay = normalizePhrase(visible)
  const nth = Math.max(1, Math.floor(occurrence) || 1)
  let from = 0
  for (let i = 0; i < nth; i++) {
    const at = hay.indexOf(needle, from)
    if (at < 0) return false
    from = at + needle.length
  }
  return true
}

type Timeout = ReturnType<typeof setTimeout>

export class BodyController {
  private targets = new Set<BodyTarget>()

  private plan: BodyPlan | null = null
  /** Per-cue: already fired (or deliberately skipped). */
  private handled: boolean[] = []
  /** Cue indices waiting for the body, in plan order. */
  private queue: number[] = []
  private active: BodyCue | null = null
  /** Waiting for a room target to report arrival before starting hold_ms. */
  private holdPending = false
  private holdTimer: Timeout | null = null
  private expiryTimer: Timeout | null = null

  private turnId: string | null = null
  private visible = ''
  private started = false
  private ended = false
  /**
   * Turns whose progress is being driven by audio. Once a turn has been
   * advanced from playback, text deltas for it are ignored — otherwise the
   * words would arrive over the socket long before they are spoken and every
   * gesture would land early.
   */
  private audioTurns = new Set<string>()

  /** Test seam: the clock the plan deadline is measured against. */
  now: () => number = () => Date.now()

  private planDeadline = 0

  /** Currently playing cue, for tests and debugging. */
  get activeCue(): BodyCue | null {
    return this.active
  }

  get currentTurn(): string | null {
    return this.turnId
  }

  registerTarget(target: BodyTarget): () => void {
    this.targets.add(target)
    // A target mounted mid-cue joins it rather than standing there idle.
    if (this.active) target.applyCue(this.active)
    return () => {
      this.targets.delete(target)
    }
  }

  /** A new reply is starting. Anything the previous turn planned is over. */
  startTurn(turnId: string): void {
    if (!turnId) return
    if (this.turnId === turnId) return
    this.dropPlan()
    this.turnId = turnId
    this.visible = ''
    this.started = false
    this.ended = false
  }

  applyPlan(plan: BodyPlan): void {
    if (!plan?.turn_id || !Array.isArray(plan.cues) || plan.cues.length === 0) return
    // A plan for a turn we never saw start still belongs to a live reply —
    // a page opened mid-turn should not sit the whole thing out.
    if (this.turnId !== plan.turn_id) this.startTurn(plan.turn_id)
    this.clearTimers()
    this.plan = plan
    this.handled = plan.cues.map(() => false)
    this.queue = []
    this.planDeadline = this.now() + (plan.expires_ms ?? DEFAULT_PLAN_TTL_MS)
    this.expiryTimer = setTimeout(
      () => this.dropPlan(),
      Math.max(0, this.planDeadline - this.now()),
    )
    // The plan normally lands before the first token, but a model that spoke
    // first must not lose the cues that its own opening already passed.
    this.evaluate()
  }

  /**
   * Report how much of the reply has reached the user.
   *
   * `visible` is cumulative, not a delta: a dropped intermediate event then
   * costs nothing, and a phrase can never be split across two updates.
   */
  advance(turnId: string, visible: string, source: CueSource = 'text'): void {
    if (!turnId) return
    if (source === 'audio') this.audioTurns.add(turnId)
    else if (this.audioTurns.has(turnId)) return
    if (this.turnId !== turnId) this.startTurn(turnId)
    // Cumulative by contract, but an out-of-order frame must not rewind it.
    if (visible.length < this.visible.length) return
    this.visible = visible
    if (visible.length > 0) this.started = true
    this.evaluate()
  }

  /** The reply is finished: fire reply_end, then drop whatever never matched. */
  endTurn(turnId: string, finalText?: string): void {
    if (!turnId || this.turnId !== turnId) return
    if (typeof finalText === 'string' && finalText.length >= this.visible.length) {
      this.visible = finalText
    }
    this.started = true
    this.ended = true
    this.evaluate()
    // Anchors that never appeared are simply skipped — a phrase the model
    // planned for and then did not say is not a gesture worth inventing.
    this.handled = this.handled.map(() => true)
    if (!this.queue.length && !this.active) this.dropPlan()
  }

  /** Interruption, superseded turn, failed reply, or an expired plan. */
  cancel(turnId?: string, _reason = 'cancelled'): void {
    if (turnId && this.turnId && this.turnId !== turnId) return
    this.dropPlan()
  }

  /**
   * The human took the controls — the Direct panel, or a poke.
   *
   * Their input outranks the plan, and it outranks the rest of it too: once
   * someone has grabbed the character mid-choreography, playing out the
   * remaining cues over the top of what they asked for is not deference.
   */
  humanTakeover(): void {
    this.dropPlan()
  }

  /**
   * A room target reached the station named by the active cue. Starts the
   * hold clock that was deferred so long walks are not cut short mid-path.
   */
  cueArrived(): void {
    if (!this.active?.station || !this.holdPending) return
    this.holdPending = false
    this.holdTimer = setTimeout(
      () => this.releaseActive(),
      Math.max(0, this.active.hold_ms),
    )
  }

  /** Tear down timers; the page is going away. */
  dispose(): void {
    this.dropPlan()
    this.targets.clear()
    this.audioTurns.clear()
    this.turnId = null
  }

  // ── internals ───────────────────────────────────────────────────────

  private evaluate(): void {
    if (!this.plan) return
    if (this.now() > this.planDeadline) {
      this.dropPlan()
      return
    }
    const cues = this.plan.cues
    for (let i = 0; i < cues.length; i++) {
      if (this.handled[i]) continue
      if (!this.matches(cues[i])) continue
      this.handled[i] = true
      this.queue.push(i)
    }
    this.pump()
  }

  private matches(cue: BodyCue): boolean {
    if (cue.anchor === 'now') return true
    if (cue.anchor === 'reply_start') return this.started
    if (cue.anchor === 'reply_end') return this.ended
    if (!cue.phrase) return false
    return phraseVisible(this.visible, cue.phrase, cue.occurrence ?? 1)
  }

  private waitsForArrival(cue: BodyCue): boolean {
    if (!cue.station) return false
    for (const target of this.targets) {
      if (target.reportsArrival) return true
    }
    return false
  }

  /** Run the queue one cue at a time, in plan order. */
  private pump(): void {
    if (this.active || !this.queue.length || !this.plan) return
    if (this.now() > this.planDeadline) {
      this.dropPlan()
      return
    }
    const index = this.queue.shift()
    if (index === undefined) return
    const cue = this.plan.cues[index]
    this.active = cue
    this.holdPending = false
    for (const target of this.targets) {
      try {
        target.applyCue(cue)
      } catch {
        /* one broken avatar must not stall the rest of the plan */
      }
    }
    if (this.waitsForArrival(cue)) {
      // Hold starts when the room reports arrival — not when the cue fires.
      this.holdPending = true
    } else {
      this.holdTimer = setTimeout(() => this.releaseActive(), Math.max(0, cue.hold_ms))
    }
  }

  private releaseActive(): void {
    if (this.holdTimer !== null) {
      clearTimeout(this.holdTimer)
      this.holdTimer = null
    }
    this.holdPending = false
    if (!this.active) return
    this.active = null
    for (const target of this.targets) {
      try {
        target.releaseCue()
      } catch {
        /* as above */
      }
    }
    if (this.queue.length) this.pump()
    else if (this.ended || !this.plan) this.dropPlan()
  }

  private dropPlan(): void {
    this.clearTimers()
    this.holdPending = false
    this.plan = null
    this.handled = []
    this.queue = []
    if (this.active) {
      this.active = null
      for (const target of this.targets) {
        try {
          target.releaseCue()
        } catch {
          /* as above */
        }
      }
    }
  }

  private clearTimers(): void {
    if (this.holdTimer !== null) {
      clearTimeout(this.holdTimer)
      this.holdTimer = null
    }
    if (this.expiryTimer !== null) {
      clearTimeout(this.expiryTimer)
      this.expiryTimer = null
    }
  }
}

/** One controller per page: every mounted avatar shares this plan. */
export const bodyController = new BodyController()
