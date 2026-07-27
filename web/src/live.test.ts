import { beforeAll, describe, expect, it, vi } from 'vitest'
import { bodyController } from './clawd/body'
import { propStore } from './clawd/props'

/**
 * live.ts only opens its channel when window + WebSocket exist (a browser).
 * The fake below stands in for both so the connect/close paths can be driven.
 */
class FakeSocket {
  static instances: FakeSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }
  open() {
    this.onopen?.()
  }
  receive(event: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }
  close() {
    this.onclose?.()
  }
}

let live: (typeof import('./live'))['live']
let gameStore: (typeof import('./games/kittens/useGame'))['gameStore']

beforeAll(async () => {
  vi.stubGlobal('window', { location: { protocol: 'http:', host: 'test' } })
  vi.stubGlobal('WebSocket', FakeSocket)
  ;({ live } = await import('./live'))
  ;({ gameStore } = await import('./games/kittens/useGame'))
})

/** The socket live.ts is currently holding, forcing a connect if needed. */
function currentSocket(): FakeSocket {
  live.subscribe(() => {})
  const ws = FakeSocket.instances[FakeSocket.instances.length - 1]
  if (!ws) throw new Error('live did not open a socket')
  return ws
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 10))

describe('live channel stability', () => {
  it('drops the desk-work flag when the socket dies mid-tool', () => {
    const ws = currentSocket()
    ws.open()
    ws.receive({ kind: 'tool_started', watchdog_ms: 50 })
    expect(live.isWorking()).toBe(true)
    // The tool_finished for this work died with the socket; without a reset
    // the typing dots would never leave.
    ws.close()
    expect(live.isWorking()).toBe(false)
    bodyController.endSustain()
  })

  it('resyncs the game table when the socket reconnects', () => {
    expect(live.isConnected()).toBe(false)
    const spy = vi.spyOn(gameStore, 'refresh').mockResolvedValue(undefined)
    currentSocket().open()
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })
})

describe('live errand sequencer', () => {
  it('abandons a carried object when the performance is cut short', async () => {
    propStore.begin({ id: 'e-abort', prop: 'mug', from: 'desk', to: 'shelf' })
    bodyController.sustain(
      { anchor: 'now', motion: 'carry', hold_ms: 60_000, errand: { id: 'e-abort', phase: 'carry' } },
      60_000,
    )
    expect(propStore.activeErrand?.phase).toBe('carry')
    // A poke, takeover, body_cancel or game summon ends the same way: the
    // cue clears and no next step of the errand ever arrives.
    bodyController.cancel(undefined, 'test')
    await tick()
    expect(propStore.activeErrand).toBeNull()
    // The object lands where the server has it, not stuck in his claws.
    expect(propStore.spotOf('mug')).toBe('shelf')
  })

  it('does not abandon the errand in the gap between two of its own steps', async () => {
    propStore.begin({ id: 'e-gap', prop: 'books', from: 'floor_left', to: 'desk' })
    bodyController.sustain(
      { anchor: 'now', motion: 'carry', hold_ms: 60_000, errand: { id: 'e-gap', phase: 'carry' } },
      60_000,
    )
    // The controller announces null between cues and the next step in the
    // same tick — the cancel must not fire on that gap.
    bodyController.endSustain()
    bodyController.sustain(
      { anchor: 'now', motion: 'place', hold_ms: 60_000, errand: { id: 'e-gap', phase: 'place' } },
      60_000,
    )
    await tick()
    expect(propStore.activeErrand?.phase).toBe('place')
    // Reaching 'place' and clearing completes the errand.
    bodyController.endSustain()
    await tick()
    expect(propStore.activeErrand).toBeNull()
    expect(propStore.spotOf('books')).toBe('desk')
  })
})
