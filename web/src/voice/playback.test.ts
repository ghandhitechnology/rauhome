import { afterEach, describe, expect, it, vi } from 'vitest'

import { TtsPlayback } from './playback'

type Posted = Record<string, unknown>

class FakePort {
  onmessage: ((e: MessageEvent) => void) | null = null
  posted: Posted[] = []
  postMessage(msg: Posted) {
    this.posted.push(msg)
  }
  /** Deliver a message as the worklet would. */
  emit(msg: Posted) {
    this.onmessage?.({ data: msg } as MessageEvent)
  }
}

class FakeNode {
  port = new FakePort()
  connect() {}
  disconnect() {}
}

class FakeContext {
  state = 'running'
  destination = {}
  audioWorklet = { addModule: () => Promise.resolve() }
  resume() {
    return Promise.resolve()
  }
  close() {
    return Promise.resolve()
  }
}

/** AudioContext/AudioWorkletNode/window stand-ins; returns the fake node. */
const stubAudio = () => {
  const node = new FakeNode()
  vi.stubGlobal('AudioContext', function () {
    return new FakeContext()
  })
  vi.stubGlobal('AudioWorkletNode', function () {
    return node
  })
  vi.stubGlobal('window', { setTimeout, clearTimeout })
  return node
}

describe('TtsPlayback', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('retries start() after a transient audio failure', async () => {
    let attempts = 0
    vi.stubGlobal('AudioContext', function () {
      attempts += 1
      throw new Error(`audio start ${attempts}`)
    })

    const playback = new TtsPlayback()
    await expect(playback.start()).rejects.toThrow('audio start 1')
    // A cached rejection would fail this retry with the first error again.
    await expect(playback.start()).rejects.toThrow('audio start 2')
  })

  it('does not let a level report in flight clobber a reset', async () => {
    const node = stubAudio()
    const playback = new TtsPlayback()
    const heard: number[] = []
    playback.onLevel((_level, playedMs) => {
      heard.push(playedMs)
    })
    await playback.start()

    node.port.emit({ level: 0.5, playedMs: 120, idle: false })
    playback.reset()
    expect(node.port.posted).toContainEqual({ cmd: 'reset' })

    // Posted by the worklet before it saw the reset, delivered after it: the
    // report describes audio really played, so it still lands...
    node.port.emit({ level: 0.5, playedMs: 130, idle: false })
    expect(heard).toEqual([120, 130])
    // ...and the worklet's echo is what rewinds the counter, after it — so
    // the stale report cannot resurrect the old timeline.
    node.port.emit({ reset: true })

    const played = playback.flush()
    node.port.emit({ flushed: true })
    await expect(played).resolves.toBe(0)
  })

  it('zeroes the counter immediately when nothing has opened', async () => {
    const playback = new TtsPlayback()
    playback.reset()
    await expect(playback.flush()).resolves.toBe(0)
  })
})
