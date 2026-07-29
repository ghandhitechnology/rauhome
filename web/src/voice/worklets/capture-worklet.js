/**
 * Mic capture worklet.
 *
 * Runs on the audio thread: downsamples the context rate (usually 48 kHz) to
 * the 16 kHz PCM16 every STT backend expects, and reports a smoothed RMS level
 * so the UI and Clawd can react to how loudly you are speaking.
 *
 * Downsampling here rather than on the main thread keeps the transfer small
 * (3x less data at 48 kHz) and keeps the UI thread free.
 */

const TARGET_RATE = 16000
// ~20ms at 16 kHz. Small enough for responsive VAD, large enough not to spam
// the message port every render quantum.
const FRAME = 320

class CaptureWorklet extends AudioWorkletProcessor {
  constructor() {
    super()
    this._ratio = sampleRate / TARGET_RATE
    this._pos = 0
    this._out = new Int16Array(FRAME)
    this._n = 0
    this._frameSquares = 0
    this._framePeak = 0
    this._level = 0
    this._running = true
    this.port.onmessage = (e) => {
      if (e.data === 'stop') this._running = false
    }
  }

  process(inputs) {
    if (!this._running) return false
    const input = inputs[0]
    if (!input || !input[0]) return true
    const ch = input[0]

    // Peak-ish RMS with a fast attack and slow release, so the meter jumps on
    // a syllable but does not flicker between them.
    let sum = 0
    for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i]
    const rms = Math.sqrt(sum / ch.length)
    this._level = rms > this._level ? rms : this._level * 0.85 + rms * 0.15

    // Linear-interpolated resample. Good enough for speech at this ratio and
    // far cheaper than a windowed sinc.
    while (this._pos < ch.length) {
      const idx = Math.floor(this._pos)
      const frac = this._pos - idx
      const a = ch[idx]
      const b = idx + 1 < ch.length ? ch[idx + 1] : a
      const s = a + (b - a) * frac
      this._out[this._n++] = Math.max(-32768, Math.min(32767, s * 32767))
      this._frameSquares += s * s
      this._framePeak = Math.max(this._framePeak, Math.abs(s))
      if (this._n >= FRAME) {
        // VAD must see this frame's actual energy, not `_level`: that meter
        // intentionally has a slow release, which smears a mouse/keyboard
        // click across enough frames to look like sustained speech.
        const speechLevel = Math.sqrt(this._frameSquares / FRAME)
        const crest = this._framePeak / Math.max(speechLevel, 0.000001)
        // A click concentrates most of its energy into a few samples. Speech
        // has a much lower peak-to-RMS ratio over a 20ms frame, including
        // ordinary plosives. The absolute floor avoids classifying quiet
        // numerical noise as an impulse.
        const transient = this._framePeak >= 0.08 && crest >= 7
        // One copy, transferred — the worklet's own buffer is refilled
        // immediately, so it must not be the thing handed across.
        const copy = this._out.slice()
        this.port.postMessage(
          { pcm: copy.buffer, level: this._level, speechLevel, transient },
          [copy.buffer],
        )
        this._n = 0
        this._frameSquares = 0
        this._framePeak = 0
      }
      this._pos += this._ratio
    }
    this._pos -= ch.length

    return true
  }
}

registerProcessor('rau-capture', CaptureWorklet)
