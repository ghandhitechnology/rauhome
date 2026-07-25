/**
 * TTS playback.
 *
 * Feeds PCM16 @24k into the playback worklet, which is the part that can stop
 * within a render quantum. Everything here is bookkeeping around that: how
 * loud Rau currently is, and how much of him was actually heard.
 *
 * One instance is one session: `close()` is terminal, matching MicCapture.
 */

/** Called ~20 times a second while audio is queued. */
export type LevelHandler = (level: number, playedMs: number, idle: boolean) => void

/** A flush the audio thread never answers must not hold up an interrupt. */
const FLUSH_TIMEOUT_MS = 250

type WorkletMessage = {
  level?: number
  playedMs?: number
  idle?: boolean
  flushed?: boolean
}

export class TtsPlayback {
  private handler: LevelHandler | null = null
  private ctx: AudioContext | null = null
  private node: AudioWorkletNode | null = null
  private opening: Promise<void> | null = null
  private pending: ArrayBuffer[] = []
  private waiting = new Set<() => void>()
  private playedMs = 0
  private closed = false

  onLevel(handler: LevelHandler | null) {
    this.handler = handler
  }

  start(): Promise<void> {
    if (this.closed) return Promise.resolve()
    if (!this.opening) this.opening = this.open()
    return this.opening
  }

  private async open(): Promise<void> {
    let node: AudioWorkletNode
    try {
      const ctx = new AudioContext({ latencyHint: 'interactive' })
      this.ctx = ctx
      await ctx.audioWorklet.addModule(new URL('./worklets/playback-worklet.js', import.meta.url))
      if (ctx.state === 'suspended') await ctx.resume()

      node = new AudioWorkletNode(ctx, 'rau-playback', {
        numberOfInputs: 0,
        outputChannelCount: [1],
      })
      node.port.onmessage = (e: MessageEvent<WorkletMessage>) => this.receive(e.data)
      node.connect(ctx.destination)
      this.node = node
    } catch (e) {
      // Browsers cap a tab at a handful of AudioContexts, so one abandoned by
      // a half-built playback path costs the next session its audio.
      await this.release()
      throw e
    }

    // A close() that arrived before the context opened found no node to drop.
    if (this.closed) {
      await this.release()
      return
    }

    for (const pcm of this.pending) node.port.postMessage({ pcm }, [pcm])
    this.pending.length = 0
  }

  /** Queue a chunk of TTS audio. */
  push(pcm: ArrayBuffer) {
    if (this.closed) return
    const node = this.node
    // The first sentence can land before the context has finished opening;
    // holding it beats a clipped greeting.
    if (!node) {
      this.pending.push(pcm)
      return
    }
    node.port.postMessage({ pcm }, [pcm])
  }

  /**
   * Drop everything queued and resolve with how many milliseconds of this
   * utterance the user really heard.
   */
  flush(): Promise<number> {
    this.pending.length = 0
    const node = this.node
    if (!node) return Promise.resolve(this.playedMs)
    return new Promise((resolve) => {
      const finish = () => {
        window.clearTimeout(timer)
        this.waiting.delete(finish)
        resolve(this.playedMs)
      }
      // Per-flush, not shared: a timer left over from an answered flush would
      // otherwise resolve the next one with a stale count.
      const timer = window.setTimeout(finish, FLUSH_TIMEOUT_MS)
      this.waiting.add(finish)
      node.port.postMessage({ cmd: 'flush' })
    })
  }

  /** Drop queued audio and put the played-time counter back to zero. */
  reset() {
    this.pending.length = 0
    this.playedMs = 0
    this.node?.port.postMessage({ cmd: 'reset' })
  }

  async close(): Promise<void> {
    this.closed = true
    const opening = this.opening
    this.opening = null
    if (opening) await opening.catch(() => {})
    await this.release()
  }

  private async release(): Promise<void> {
    const node = this.node
    this.node = null
    if (node) {
      node.port.onmessage = null
      node.disconnect()
    }
    this.pending.length = 0
    this.settle()

    const ctx = this.ctx
    this.ctx = null
    if (ctx) await ctx.close().catch(() => {})
  }

  private receive(msg: WorkletMessage) {
    this.playedMs = msg.playedMs ?? this.playedMs
    if (msg.flushed) {
      this.settle()
      return
    }
    this.handler?.(msg.level ?? 0, this.playedMs, !!msg.idle)
  }

  private settle() {
    for (const finish of [...this.waiting]) finish()
  }
}
