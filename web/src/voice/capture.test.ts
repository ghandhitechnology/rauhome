import { afterEach, describe, expect, it, vi } from 'vitest'

import { MicCapture } from './capture'

class FakeGain {
  gain = { value: 1 }
  connect(target: unknown) {
    return target
  }
}

class FakeCaptureNode {
  port = { onmessage: null, postMessage: () => {} }
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
})
