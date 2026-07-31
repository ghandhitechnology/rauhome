/**
 * The live rig: owns the parameter set and runs, in order,
 *
 *   1. reset to defaults
 *   2. automatic layers (breath, blink, eye tracking) — only where free
 *   3. the motion player (crossfaded clips claim their parameters)
 *   4. the voice layer, added on top of whatever the clip produced
 *   5. physics (spring lag on the claws, lean from acceleration)
 *
 * That ordering is what lets Clawd blink mid-walk but keep his eyes shut
 * through a sleep clip: the sleep clip owns eyeOpen*, so the blinker skips it.
 */

import { clamp, clamp01, damp, lerp } from './easing'
import { strideAngle } from './gait'
import { MotionPlayer, type Motion } from './motion'
import { MOTIONS, ONE_SHOTS, type MotionName } from './motions'
import { defaultParams, PARAM_IDS, setParam, type ParamSet } from './params'
import { Inertia, noise1, Spring } from './physics'

/** Reset template, built once — rebuilding it per frame would churn the GC. */
const DEFAULTS = defaultParams()

/** A deliberate place to look, in eye-parameter space rather than pixels. */
export type GazeAim = {
  /** -1..1, positive is the way he is facing. */
  x: number
  /** -1..1, positive is downward. */
  y: number
  /** Approach rate, roughly 1/seconds. High values read as a snap. */
  speed?: number
  /** 0..1 of drift around the aim, so a held gaze never freezes solid. */
  wander?: number
}

export type RigOptions = {
  /** Where the eyes should look, in viewport pixels. Null lets him wander. */
  lookAt?: { x: number; y: number } | null
  /** Sprite's own position in viewport pixels, for look-at maths. */
  screen?: { x: number; y: number }
  /**
   * Speech loudness this frame, 0..1 — normally the TTS output envelope.
   * Overrides whatever was last written to `talkLevel`.
   */
  talkLevel?: number
}

export class ClawdRig {
  readonly params: ParamSet = defaultParams()
  readonly player = new MotionPlayer()

  /** World position in sprite units. The scene decides what that maps to. */
  worldX = 0
  facing: 1 | -1 = 1

  /**
   * Run gaits on the clock when nothing is feeding them travel.
   *
   * A gait is spent in ground covered, so with no world to cross it would
   * simply freeze. The avatar panel and the motion tester both walk on the
   * spot deliberately, and this is them saying so — it stays off in the room,
   * where a walk with no travel behind it is exactly the sliding being fixed.
   */
  treadmill = false

  /** Speech loudness, 0..1. Also settable per frame through RigOptions. */
  talkLevel = 0
  /** Multiplier on the breathing rate — raised when he is working or keyed up. */
  breathRate = 1

  private clock = 0
  /** Ground covered since the last update, in sprite units. Gaits run off it. */
  private travel = 0
  /**
   * Fraction of the active gait's authored stride he is actually taking.
   * The director sets it from real speed; 1 is the clip exactly as authored.
   */
  private strideScale = 1
  private breathPhase = 0
  private blinkAt = 2.5
  private blinkPhase = -1
  private doubleBlink = false
  private lookX = 0
  private lookY = 0
  private gazeAim: GazeAim | null = null
  private voiceFast = 0
  private voiceSlow = 0
  private clawSpringL = new Spring(0, 190, 0.55)
  private clawSpringR = new Spring(0, 190, 0.55)
  /**
   * Acceleration lean. Softer and less damped than it was, so getting going and
   * coming to rest both show as weight rather than as a twitch — this is what
   * carries the whole continuum of speeds the wind-up clip cannot cover.
   */
  private leanInertia = new Inertia(26, 0.62)
  private seed = Math.random() * 1000

  constructor() {
    this.player.play(MOTIONS.idle)
  }

  get currentMotion(): string | null {
    return this.player.currentId
  }

  play(name: MotionName, opts: { force?: boolean; restart?: boolean } = {}): boolean {
    return this.player.play(MOTIONS[name], opts)
  }

  playMotion(motion: Motion, opts: { force?: boolean; restart?: boolean } = {}): boolean {
    return this.player.play(motion, opts)
  }

  /**
   * Aim the eyes deliberately. A pointer passed to `update` still wins — being
   * looked at by the user outranks anything the behaviour layer wanted.
   */
  setGaze(aim: GazeAim | null) {
    this.gazeAim = aim
  }

  /** True when a one-shot clip is still playing and should not be interrupted. */
  get busy(): boolean {
    const id = this.player.currentId
    if (!id) return false
    if (!ONE_SHOTS.includes(id as MotionName)) return false
    return !this.player.isFinished
  }

  update(dt: number, opts: RigOptions = {}) {
    this.clock += dt
    const p = this.params
    const owned = this.player.owned

    // ── 1. reset ─────────────────────────────────────────────────────
    for (const k of PARAM_IDS) p[k] = DEFAULTS[k]
    p.facing = this.facing

    // ── 2. automatic layers ──────────────────────────────────────────
    // Breathing: a slow swell that motions may override. The phase is
    // accumulated rather than derived from the clock so that changing the rate
    // speeds him up instead of jumping him to a different point in the breath.
    this.breathPhase += dt * 1.15 * this.breathRate
    if (!owned.has('breath')) {
      p.breath = (Math.sin(this.breathPhase + this.seed) * 0.5 + 0.5) * 0.75
    }

    // Eye tracking. Without a target he drifts on smooth noise instead of
    // sitting perfectly still, which reads as alive rather than frozen.
    let targetLX: number
    let targetLY: number
    let aimSpeed = 6
    if (opts.lookAt && opts.screen) {
      const dx = opts.lookAt.x - opts.screen.x
      const dy = opts.lookAt.y - opts.screen.y
      targetLX = clamp(dx / 260, -1, 1)
      targetLY = clamp(dy / 200, -1, 1)
    } else if (this.gazeAim) {
      const aim = this.gazeAim
      const w = aim.wander ?? 0
      aimSpeed = aim.speed ?? 6
      targetLX = clamp(aim.x + noise1(this.clock * 0.34 + this.seed) * 0.3 * w, -1, 1)
      targetLY = clamp(aim.y + noise1(this.clock * 0.26 + this.seed + 50) * 0.2 * w, -1, 1)
    } else {
      targetLX = noise1(this.clock * 0.22 + this.seed) * 0.75
      targetLY = noise1(this.clock * 0.17 + this.seed + 50) * 0.4
    }
    this.lookX = damp(this.lookX, targetLX, aimSpeed, dt)
    this.lookY = damp(this.lookY, targetLY, aimSpeed, dt)
    if (!owned.has('eyeX')) p.eyeX = this.lookX
    if (!owned.has('eyeY')) p.eyeY = this.lookY

    // Blinking on an irregular schedule, occasionally doubled.
    this.updateBlink(dt)
    if (this.blinkPhase >= 0) {
      const shut = this.blinkCurve()
      if (!owned.has('eyeOpenL')) p.eyeOpenL = shut
      if (!owned.has('eyeOpenR')) p.eyeOpenR = shut
    }

    // ── 3. motions ───────────────────────────────────────────────────
    // A gait's timeline is spent travel, not elapsed time, so the legs, the
    // bob and the claw swing all come off one phase and cannot drift apart.
    let travel = this.travel
    if (travel <= 0 && this.treadmill && this.player.isDistanceDriven) {
      travel = this.player.cruise * dt
    }
    this.player.update(dt, p, travel, this.strideScale)
    this.travel = 0

    // The walk cycle *is* the clip's phase — there is no second leg clock to
    // keep in sync with it, which is the whole point.
    if (this.player.isDistanceDriven) {
      p.legPhase = this.player.progress
      this.applyStride(p)
    }

    // ── 4. voice ─────────────────────────────────────────────────────
    // Added on top of the clip rather than layered underneath it: the talk
    // clip owns posY and the claws, so anything applied before the player
    // would simply be blended away. Clawd has no mouth — the line has to be
    // carried by the whole body, over whatever he happens to be doing.
    const accent = this.updateVoice(dt, opts)
    if (this.voiceFast > 0.002) {
      p.talkLevel = this.voiceFast
      setParam(p, 'posY', p.posY - this.voiceFast * 0.4)
      setParam(p, 'scaleY', p.scaleY + this.voiceFast * 0.06)
      setParam(p, 'scaleX', p.scaleX - this.voiceFast * 0.025)
      // Claw lift lands before the springs below, so accents arrive with lag.
      setParam(p, 'clawL', p.clawL + accent * 9)
      setParam(p, 'clawR', p.clawR + accent * 7)
      // A raised voice narrows the eyes. Scaled rather than set, so a blink or
      // a clip holding the eyes shut still wins.
      const squint = 1 - accent * 0.2
      setParam(p, 'eyeOpenL', p.eyeOpenL * squint)
      setParam(p, 'eyeOpenR', p.eyeOpenR * squint)
    }

    // ── 5. physics ───────────────────────────────────────────────────
    // Claws chase their keyframed angle rather than hitting it exactly. The
    // springs keep their own unclamped state so the overshoot survives, but
    // what lands in the parameter set still respects its declared bounds.
    setParam(p, 'clawL', this.clawSpringL.update(p.clawL, dt))
    setParam(p, 'clawR', this.clawSpringR.update(p.clawR, dt))

    // Acceleration tips the body; the spring washes it back out. Deliberately
    // undamped enough to overshoot: settling back upright a beat after he stops
    // is the difference between arriving somewhere and being switched off.
    const lean = this.leanInertia.update(this.worldX, dt, 0.5)
    setParam(p, 'angle', p.angle + clamp(lean, -7, 7) * this.facing)

    p.facing = this.facing
  }

  /**
   * Feed the gait the ground he has just covered, in sprite units.
   *
   * `strideScale` is how much of the clip's authored stride he is taking —
   * below 1 for the creep into a stop, above 1 for a hurry. It shortens the
   * steps and quickens the cadence together, the way slowing down actually
   * looks, instead of playing the same walk at a lower rate.
   */
  advanceGait(distance: number, strideScale = 1) {
    this.travel += Math.abs(distance)
    this.strideScale = clamp(strideScale, 0.35, 1.4)
  }

  /**
   * Scale the cyclic part of a gait to the stride actually being taken.
   *
   * Only the legs and the bob: a clip's postural offsets (the backward lean of
   * a carry, the tucked claws of a tiptoe) are what he is *doing*, not how big
   * a step he is taking, and straightening him up as he slowed would undo the
   * pose the clip exists to hold.
   */
  private applyStride(p: ParamSet) {
    const s = this.strideScale
    if (Math.abs(s - 1) < 0.01) return
    setParam(p, 'legSwing', strideAngle(p.legSwing, s))
    // The body settles less on a short step, but never goes flat — a walk with
    // no vertical at all reads as gliding. A long reaching stride gets a little
    // more of it, which is what makes a hurry look like one.
    const bob = s < 1 ? lerp(0.6, 1, s) : Math.min(1.15, s)
    setParam(p, 'posY', p.posY * bob)
    setParam(p, 'scaleY', 1 + (p.scaleY - 1) * bob)
    setParam(p, 'scaleX', 1 + (p.scaleX - 1) * bob)
  }

  /**
   * Track the speech envelope and return the current syllable accent, 0..1.
   * Accents are where the fast envelope runs ahead of its own average, which
   * is roughly where a stressed syllable sits.
   */
  private updateVoice(dt: number, opts: RigOptions): number {
    if (opts.talkLevel !== undefined) this.talkLevel = opts.talkLevel
    const level = clamp01(this.talkLevel)
    // Fast attack, slow release — an amplitude envelope, not a raw sample.
    this.voiceFast = damp(this.voiceFast, level, level > this.voiceFast ? 30 : 9, dt)
    this.voiceSlow = damp(this.voiceSlow, this.voiceFast, 2.4, dt)
    return clamp01((this.voiceFast - this.voiceSlow) * 3.2)
  }

  private updateBlink(dt: number) {
    if (this.blinkPhase >= 0) {
      this.blinkPhase += dt
      const dur = 0.13
      if (this.blinkPhase > dur) {
        if (this.doubleBlink) {
          this.doubleBlink = false
          this.blinkPhase = -1
          this.blinkAt = this.clock + 0.14
        } else {
          this.blinkPhase = -1
          this.scheduleBlink()
        }
      }
      return
    }
    if (this.clock >= this.blinkAt) {
      this.blinkPhase = 0
      this.doubleBlink = Math.random() < 0.24
    }
  }

  private scheduleBlink() {
    this.blinkAt = this.clock + 2.2 + Math.random() * 4.6
  }

  /** 1 = open, 0 = shut. Fast close, slightly slower open. */
  private blinkCurve(): number {
    const t = clamp01(this.blinkPhase / 0.13)
    return t < 0.42 ? 1 - t / 0.42 : (t - 0.42) / 0.58
  }
}
