/**
 * TTS playback worklet.
 *
 * Holds a queue of PCM16 chunks and plays them back seamlessly. The reason
 * this is a worklet rather than scheduled AudioBufferSourceNodes: `flush`
 * takes effect within one render quantum (~2.7ms at 48 kHz), which is what
 * makes interrupting Rau feel like interrupting a person rather than waiting
 * for the current buffer to drain.
 *
 * Also reports how many milliseconds it has actually played, which the server
 * uses to trim history to what the user really heard.
 */

const SOURCE_RATE = 24000

class PlaybackWorklet extends AudioWorkletProcessor {
  constructor() {
    super()
    this._queue = []
    this._chunk = null
    this._pos = 0
    this._ratio = SOURCE_RATE / sampleRate
    this._playedSamples = 0
    this._level = 0
    this._reported = 0

    this.port.onmessage = (e) => {
      const msg = e.data
      if (msg.pcm) {
        this._queue.push(new Int16Array(msg.pcm))
        return
      }
      if (msg.cmd === 'flush') {
        // Drop everything pending, immediately.
        this._queue.length = 0
        this._chunk = null
        this._pos = 0
        this._level = 0
        this.port.postMessage({ flushed: true, playedMs: this.playedMs() })
        return
      }
      if (msg.cmd === 'reset') {
        this._queue.length = 0
        this._chunk = null
        this._pos = 0
        this._playedSamples = 0
        this._level = 0
      }
    }
  }

  playedMs() {
    return (this._playedSamples / SOURCE_RATE) * 1000
  }

  _next() {
    if (this._chunk && this._pos < this._chunk.length) return true
    this._chunk = this._queue.shift() || null
    this._pos = 0
    return this._chunk !== null
  }

  process(_inputs, outputs) {
    const out = outputs[0]
    if (!out || !out[0]) return true
    const ch = out[0]

    let peak = 0
    for (let i = 0; i < ch.length; i++) {
      if (!this._next()) {
        ch[i] = 0
        continue
      }
      const idx = Math.floor(this._pos)
      const s = this._chunk[Math.min(idx, this._chunk.length - 1)] / 32768
      ch[i] = s
      const a = Math.abs(s)
      if (a > peak) peak = a
      this._pos += this._ratio
      this._playedSamples += this._ratio
    }

    // Copy mono to any other channels.
    for (let c = 1; c < out.length; c++) out[c].set(ch)

    this._level = peak > this._level ? peak : this._level * 0.8 + peak * 0.2

    // Report ~every 50ms; this drives Clawd's audio-reactive body.
    this._reported += ch.length
    if (this._reported >= sampleRate / 20) {
      this._reported = 0
      this.port.postMessage({
        level: this._level,
        playedMs: this.playedMs(),
        idle: this._chunk === null && this._queue.length === 0,
      })
    }

    return true
  }
}

registerProcessor('rau-playback', PlaybackWorklet)
