/**
 * Which table gets painted, and when there is no longer one.
 *
 * `drawGameTable` is called every frame by the room, which does not know or
 * care which game is on. It asks the bridge. The interesting case is the gap:
 * a game hands its surface back the instant it ends, but the table is still on
 * screen and still fading, so there are frames with a real presence and no
 * surface to look it up in.
 *
 * That gap used to fall back to the card table. At the tail of an ordinary
 * dismissal that is invisible — presence is already a rounding error — which is
 * exactly why it survived. It is not invisible on the paths that hand the
 * surface back early: an aborted start, or a leave taken while he is still
 * walking over, give it back with most of the presence still up, and a chess
 * dismissal would spend those frames painting a card table over the board the
 * user was looking at a moment ago.
 *
 * The layer remembers the last surface for exactly this, which is module state,
 * so every case here loads the modules fresh rather than inheriting whatever
 * the previous one left behind.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

/** `drawGameTable` only ever forwards, so a stub the calls land on is enough. */
const ctx = {} as CanvasRenderingContext2D

/**
 * A fresh copy of the layer, its bridge, and both surfaces.
 *
 * They have to be imported together: the bridge is a singleton the layer reads
 * through, so a reset that gave the layer a new one and the test the old one
 * would be testing two different rooms.
 */
async function freshRoom() {
  vi.resetModules()
  const [{ drawGameTable, KITTENS_SURFACE }, { CHESS_SURFACE }, { gameBridge }] = await Promise.all([
    import('./gameTableLayer'),
    import('./chessTableLayer'),
    import('./gameBridge'),
  ])
  const chess = vi.spyOn(CHESS_SURFACE, 'draw').mockImplementation(() => {})
  const kittens = vi.spyOn(KITTENS_SURFACE, 'draw').mockImplementation(() => {})
  return {
    gameBridge,
    CHESS_SURFACE,
    KITTENS_SURFACE,
    chess,
    kittens,
    paint: (presence: number) => drawGameTable(ctx, 4, presence, 0),
  }
}

describe('which table is painted', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('paints the surface the bridge is holding', async () => {
    const room = await freshRoom()
    room.gameBridge.activate(room.CHESS_SURFACE)
    room.paint(1)

    expect(room.chess).toHaveBeenCalledTimes(1)
    expect(room.kittens).not.toHaveBeenCalled()
  })

  it('keeps painting the board through a dismissal that hands the surface back early', async () => {
    const room = await freshRoom()
    room.gameBridge.activate(room.CHESS_SURFACE)
    room.paint(1)
    // A leave taken mid-walk: the surface goes back while he is still most of
    // the way through the ritual, so the fade that follows is fully visible.
    room.gameBridge.activate(null)
    room.paint(0.8)
    room.paint(0.4)

    expect(room.chess).toHaveBeenCalledTimes(3)
    expect(room.kittens).not.toHaveBeenCalled()
  })

  it('does not paint a table before either game has ever put one out', async () => {
    const room = await freshRoom()
    room.paint(0)
    room.paint(0.5)

    expect(room.chess).not.toHaveBeenCalled()
    expect(room.kittens).not.toHaveBeenCalled()
  })

  it('follows the handover when the other game takes the table', async () => {
    const room = await freshRoom()
    room.gameBridge.activate(room.CHESS_SURFACE)
    room.paint(1)
    room.gameBridge.activate(room.KITTENS_SURFACE)
    room.paint(1)

    expect(room.chess).toHaveBeenCalledTimes(1)
    expect(room.kittens).toHaveBeenCalledTimes(1)
  })
})
