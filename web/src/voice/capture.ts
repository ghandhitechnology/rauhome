/**
 * Microphone capture.
 *
 * Owns its own AudioContext: the mic runs at whatever rate the input device
 * prefers, which has nothing to do with the 24 kHz Rau speaks at, and sharing
 * one context would force a resample on whichever end lost.
 *
 * One instance is one session. `stop()` is terminal, so a `start()` that was
 * still in flight cannot come back with a live device nobody is listening to.
 */

/** One 20ms frame of PCM16 @16k, plus the smoothed input level. */
export type FrameHandler = (pcm: ArrayBuffer, level: number) => void

/** 320 samples at 16 kHz — the capture worklet's frame size. */
export const FRAME_MS = 20

export class MicCapture {
  private handler: FrameHandler | null = null
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private node: AudioWorkletNode | null = null
  private opening: Promise<void> | null = null
  private stopped = false

  onFrame(handler: FrameHandler | null) {
    this.handler = handler
  }

  start(): Promise<void> {
    if (this.stopped) return Promise.resolve()
    if (!this.opening) {
      this.opening = this.open().catch((e: unknown) => {
        // Don't cache the failure: one transient getUserMedia error would
        // otherwise reject every later start() with this same stale promise.
        this.opening = null
        throw e
      })
    }
    return this.opening
  }

  private async open(): Promise<void> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          // Hardware echo cancellation is what makes barge-in possible at all:
          // without it the mic hears Rau through the speakers and the VAD
          // interrupts him on his own voice.
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
      this.stream = stream

      const ctx = new AudioContext({ latencyHint: 'interactive' })
      this.ctx = ctx
      await ctx.audioWorklet.addModule(new URL('./worklets/capture-worklet.js', import.meta.url))
      if (ctx.state === 'suspended') await ctx.resume()

      const node = new AudioWorkletNode(ctx, 'rau-capture', { channelCount: 1 })
      node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; level: number }>) => {
        this.handler?.(e.data.pcm, e.data.level)
      }
      ctx.createMediaStreamSource(stream).connect(node)

      // A worklet only runs once it reaches the destination. The worklet writes
      // no output, but the silent gain makes that a guarantee rather than a
      // property of the current implementation.
      const sink = ctx.createGain()
      sink.gain.value = 0
      node.connect(sink).connect(ctx.destination)
      this.node = node
    } catch (e) {
      // The device is usually live by the time a later step fails, and a mic
      // nobody holds a reference to keeps the tab's recording indicator lit
      // until a reload.
      await this.release()
      throw e
    }

    // A stop() that arrived before the device did found nothing to release.
    if (this.stopped) await this.release()
  }

  async stop(): Promise<void> {
    this.stopped = true
    const opening = this.opening
    this.opening = null
    // Let a start still in flight finish assigning, or its stream and context
    // escape teardown and the tab keeps showing a live mic.
    if (opening) await opening.catch(() => {})
    await this.release()
  }

  private async release(): Promise<void> {
    const node = this.node
    this.node = null
    if (node) {
      node.port.postMessage('stop')
      node.port.onmessage = null
      node.disconnect()
    }

    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = null

    const ctx = this.ctx
    this.ctx = null
    if (ctx) await ctx.close().catch(() => {})
  }
}
