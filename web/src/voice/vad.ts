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
  // Browser RMS after echo cancellation is commonly 0.02–0.05 for normal
  // speech. The old 0.055 margin required shouting on many laptop mics.
  threshold: 0.012,
  onsetMs: 100,
  hangoverMs: 520,
  bargeMs: 240,
}

export class Vad {
  private opts: Required<VadOptions>
  private floor = 0.003
  private speechMs = 0
  private silenceMs = 0
  private active = false
  private hangoverScale = 1

  constructor(opts: VadOptions = {}) {
    this.opts = { ...DEFAULTS, ...opts }
  }

  reset() {
    this.speechMs = 0
    this.silenceMs = 0
    this.active = false
    this.hangoverScale = 1
  }

  /**
   * How long to wait before calling the utterance finished, this time.
   *
   * Fed from the partial transcript, which arrives a beat before the silence
   * runs out — so a sentence that trails off on "and…" gets room to continue
   * while a finished question is answered promptly. Clamped rather than
   * trusted: a bad transcript should shade the timing, never own it.
   */
  setHangoverScale(scale: number) {
    this.hangoverScale = Math.min(3, Math.max(0.5, Number.isFinite(scale) ? scale : 1))
  }

  /** The silence currently required to end the utterance, ms. */
  get hangoverMs() {
    return this.opts.hangoverMs * this.hangoverScale
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
    const enter = Math.max(this.floor + this.opts.threshold, this.floor * 1.8)
    // Hysteresis. Speech is not a steady tone — it has gaps at every stop
    // consonant, and a single gate at the entry level drops out inside words
    // like "st-op", restarting the hangover mid-syllable. Staying in costs
    // less evidence than getting in, which is how the ear works too.
    const loud = level > (this.active ? enter * 0.62 : enter)

    if (loud) {
      this.speechMs += dtMs
      this.silenceMs = 0
      if (!this.active && this.speechMs >= this.opts.onsetMs) {
        this.active = true
        return 'start'
      }
    } else {
      this.silenceMs += dtMs
      if (this.active && this.silenceMs >= this.hangoverMs) {
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
