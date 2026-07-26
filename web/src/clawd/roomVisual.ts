/**
 * Which room look to draw: the original flat square-pixel set, or the
 * enhanced materials/architecture pass.
 */

export type RoomVisual = 'classic' | 'enhanced'

const KEY = 'rau.roomVisual'

/**
 * The stored choice, or the enhanced room.
 *
 * Enhanced is the room the product is meant to show; classic is kept as an
 * escape hatch for a machine that cannot afford the texture passes, not as
 * the thing a first-time visitor sees.
 */
export function loadRoomVisual(): RoomVisual {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'classic' || v === 'enhanced') return v
  } catch {
    /* private mode */
  }
  return 'enhanced'
}

export function saveRoomVisual(visual: RoomVisual): void {
  try {
    localStorage.setItem(KEY, visual)
  } catch {
    /* ignore */
  }
}
