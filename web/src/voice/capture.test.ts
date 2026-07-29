import { afterEach, describe, expect, it, vi } from 'vitest'

import { MicCapture } from './capture'

class FakeGain {
  gain = { value: 1 }
  connect(target: unknown) {
    return target
  }
}

class FakeCaptureNode {
  port: {
    onmessage: ((event: MessageEvent<any>) => void) | null
    postMessage: () => void
  } = { onmessage: null, postMessage: () => {} }
  connect(target: unknown) {
    return target
  }
  disconnect() {}
}

class FakeCaptureContext {
  state = 'running'
  destination = {}
  audioWorklet = { addModule: () => Promise.resolve() }
  resume() {
    return Promise.resolve()
  }
  close() {
    return Promise.resolve()
  }
  createMediaStreamSource() {
    return { connect: (node: unknown) => node }
  }
  createGain() {
    return new FakeGain()
  }
}

describe('MicCapture', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('retries start() after a transient getUserMedia failure', async () => {
    let attempts = 0
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: () => {
          attempts += 1
          if (attempts === 1) return Promise.reject(new Error('permission dismissed'))
          return Promise.resolve({ getTracks: () => [] })
        },
      },
    })
    vi.stubGlobal('AudioContext', function () {
      return new FakeCaptureContext()
    })
    vi.stubGlobal('AudioWorkletNode', function () {
      return new FakeCaptureNode()
    })

    const capture = new MicCapture()
    await expect(capture.start()).rejects.toThrow('permission dismissed')
    // A cached rejection would fail this retry with the first error again,
    // bricking voice until the mode is toggled.
    await capture.start()
    expect(attempts).toBe(2)
    await capture.stop()
  })

  it('keeps smoothed display level separate from raw VAD evidence', async () => {
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: () => Promise.resolve({ getTracks: () => [] }),
      },
    })
    vi.stubGlobal('AudioContext', function () {
      return new FakeCaptureContext()
    })
    const node = new FakeCaptureNode()
    vi.stubGlobal('AudioWorkletNode', function () {
      return node
    })

    const capture = new MicCapture()
    const received: unknown[][] = []
    capture.onFrame((...frame) => received.push(frame))
    await capture.start()

    const pcm = new ArrayBuffer(640)
    node.port.onmessage?.({
      data: { pcm, level: 0.4, speechLevel: 0.015, transient: true },
    } as MessageEvent)
    expect(received).toEqual([[pcm, 0.4, 0.015, true]])
    await capture.stop()
  })
})
