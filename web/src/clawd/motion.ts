/**
 * Keyframed motion clips and the player that blends between them.
 *
 * Follows the Cubism motion model: a clip owns a subset of parameters, plays on
 * a timeline, and crossfades against whatever was playing before. Parameters a
 * clip does not declare are left alone, so automatic layers (blink, breathing,
 * eye tracking) can keep running underneath without fighting it.
 */

import { ease, type Ease } from './easing'
import { clampParam, type ParamId, type ParamSet } from './params'

export type Key = { t: number; v: number; ease?: Ease }

export type Track = { param: ParamId; keys: Key[] }

export type Motion = {
  id: string
  /** Seconds for one pass of the clip. */
  duration: number
  loop: boolean
  /** Crossfade in/out durations, seconds. */
  fadeIn: number
  fadeOut: number
  /** Higher wins when something asks to play over the top. */
  priority: number
  tracks: Track[]
  /**
   * Horizontal travel while this clip plays, in sprite units per second.
   * The director multiplies it by facing to move Clawd through the world.
   */
  locomotion?: number
}

export function defineMotion(m: Partial<Motion> & Pick<Motion, 'id' | 'duration' | 'tracks'>): Motion {
  return {
    loop: false,
    fadeIn: 0.22,
    fadeOut: 0.22,
    priority: 1,
    ...m,
  }
}

/** Sample one track at normalized time `t` (0..1 across the clip). */
function sampleTrack(track: Track, t: number): number {
  const keys = track.keys
  if (keys.length === 0) return 0
  if (keys.length === 1) return keys[0].v
  if (t <= keys[0].t) return keys[0].v
  const last = keys[keys.length - 1]
  if (t >= last.t) return last.v

  // Keys are authored in ascending order; a short linear scan beats a binary
  // search at these lengths and keeps the hot loop allocation-free.
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i]
    const b = keys[i + 1]
    if (t >= a.t && t <= b.t) {
      const span = b.t - a.t
      if (span <= 0) return b.v
      const local = (t - a.t) / span
      return a.v + (b.v - a.v) * ease(b.ease ?? a.ease, local)
    }
  }
  return last.v
}

type Instance = {
  motion: Motion
  /** Elapsed seconds since the clip started. */
  time: number
  /** 0..1 blend weight. */
  weight: number
  /** Set when the clip is being faded out by a successor. */
  releasing: boolean
  finished: boolean
}

/**
 * Sample a clip straight into `out`, blended by `weight`.
 *
 * Only the parameters this clip declares are touched. Blending against a shared
 * union of owned parameters would read stale scratch values for anything the
 * clip does not animate, so each instance is applied through its own tracks.
 */
function applyInstance(inst: Instance, out: ParamSet, weight: number) {
  if (weight <= 0) return
  const w = weight > 1 ? 1 : weight
  const m = inst.motion
  const raw = m.duration > 0 ? inst.time / m.duration : 1
  const t = m.loop ? raw % 1 : raw > 1 ? 1 : raw
  for (const track of m.tracks) {
    const v = sampleTrack(track, t)
    out[track.param] = clampParam(track.param, out[track.param] + (v - out[track.param]) * w)
  }
}

export class MotionPlayer {
  private current: Instance | null = null
  private previous: Instance | null = null

  /** Parameters currently driven by a clip — automatic layers must skip these. */
  readonly owned = new Set<ParamId>()

  get currentId(): string | null {
    return this.current?.motion.id ?? null
  }

  get isFinished(): boolean {
    return !this.current || this.current.finished
  }

  /** Normalized progress of the active clip, 0..1 (loops wrap). */
  get progress(): number {
    if (!this.current) return 0
    const d = this.current.motion.duration
    if (d <= 0) return 1
    const raw = this.current.time / d
    return this.current.motion.loop ? raw % 1 : Math.min(1, raw)
  }

  /**
   * Start a clip. Returns false when a higher-priority clip is still running,
   * so callers can politely fail instead of stomping a deliberate animation.
   */
  play(motion: Motion, opts: { force?: boolean; restart?: boolean } = {}): boolean {
    const cur = this.current
    if (cur && !cur.finished && !opts.force) {
      if (cur.motion.id === motion.id) {
        if (opts.restart) cur.time = 0
        return true
      }
      if (cur.motion.priority > motion.priority) return false
    }
    if (cur && cur.motion.id === motion.id && !opts.restart) return true

    if (cur) {
      cur.releasing = true
      this.previous = cur
    }
    this.current = {
      motion,
      time: 0,
      weight: motion.fadeIn > 0 ? 0 : 1,
      releasing: false,
      finished: false,
    }
    return true
  }

  /** Stop everything immediately; automatic layers take over all parameters. */
  clear() {
    this.current = null
    this.previous = null
    this.owned.clear()
  }

  update(dt: number, out: ParamSet) {
    const cur = this.current
    const prev = this.previous

    if (prev) {
      prev.time += dt
      const fade = prev.motion.fadeOut
      prev.weight = fade > 0 ? Math.max(0, prev.weight - dt / fade) : 0
      if (prev.weight <= 0) this.previous = null
    }

    if (!cur) {
      this.owned.clear()
      if (this.previous) {
        // Still fading a released clip out over the automatic layers.
        this.collectOwned(this.previous)
        applyInstance(this.previous, out, this.previous.weight)
      }
      return
    }

    cur.time += dt
    const fadeIn = cur.motion.fadeIn
    cur.weight = fadeIn > 0 ? Math.min(1, cur.weight + dt / fadeIn) : 1

    if (!cur.motion.loop && cur.motion.duration > 0 && cur.time >= cur.motion.duration) {
      cur.finished = true
    }

    this.owned.clear()
    if (this.previous) this.collectOwned(this.previous)
    this.collectOwned(cur)

    // Outgoing first so the incoming clip wins as its weight rises.
    if (this.previous) applyInstance(this.previous, out, this.previous.weight)
    applyInstance(cur, out, cur.weight)
  }

  private collectOwned(inst: Instance) {
    for (const track of inst.motion.tracks) this.owned.add(track.param)
  }
}
