/**
 * Client-side voice activity detection.
 *
 * Deliberately local: barge-in has to be decided here, because a round-trip to
 * the server before cutting audio is the difference between "interrupting
 * someone" and "waiting for them to notice".
 *
 * Energy-based with an adaptive noise floor. Browser AEC has already removed
 * Rau's own output from this signal, which is the only reason a plain energy
 * gate is viable while he is speaking.
 */

export type VadOptions = {
  /** How far above the noise floor counts as speech. */
  threshold?: number
  /** Sustained speech needed before we call it real, ms. */
  onsetMs?: number
  /** Silence needed before we call the utterance finished, ms. */
  hangoverMs?: number
  /** Sustained speech needed to interrupt Rau, ms. Higher than onset — a
   *  cough or a chair creak must not cut him off. */
  bargeMs?: number
}

const DEFAULTS: Required<VadOptions> = {
  threshold: 0.055,
  onsetMs: 120,
  hangoverMs: 620,
  bargeMs: 260,
}

export class Vad {
  private opts: Required<VadOptions>
  private floor = 0.01
  private speechMs = 0
  private silenceMs = 0
  private active = false

  constructor(opts: VadOptions = {}) {
    this.opts = { ...DEFAULTS, ...opts }
  }

  reset() {
    this.speechMs = 0
    this.silenceMs = 0
    this.active = false
  }

  get speaking() {
    return this.active
  }

  /** How long the current run of speech has lasted, ms. */
  get sustainedMs() {
    return this.speechMs
  }

  /**
   * Feed one level sample.
   * Returns 'start' / 'end' on a transition, otherwise null.
   */
  push(level: number, dtMs: number): 'start' | 'end' | null {
    // Track the quietest recent level as the noise floor, rising slowly so a
    // fan or street noise stops triggering after a few seconds.
    if (!this.active) {
      this.floor = level < this.floor ? this.floor * 0.9 + level * 0.1 : this.floor * 0.995 + level * 0.005
    }
    const loud = level > this.floor + this.opts.threshold

    if (loud) {
      this.speechMs += dtMs
      this.silenceMs = 0
      if (!this.active && this.speechMs >= this.opts.onsetMs) {
        this.active = true
        return 'start'
      }
    } else {
      this.silenceMs += dtMs
      if (this.active && this.silenceMs >= this.opts.hangoverMs) {
        this.active = false
        this.speechMs = 0
        return 'end'
      }
      if (!this.active) this.speechMs = 0
    }
    return null
  }

  /** True once speech has been sustained long enough to interrupt Rau. */
  shouldBarge(): boolean {
    return this.speechMs >= this.opts.bargeMs
  }
}
