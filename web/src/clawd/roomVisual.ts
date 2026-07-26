/**
 * Which room look to draw: the original flat square-pixel set, or the
 * enhanced materials/architecture pass.
 */

export type RoomVisual = 'classic' | 'enhanced'

const KEY = 'rau.roomVisual'

export function loadRoomVisual(): RoomVisual {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'classic' || v === 'enhanced') return v
  } catch {
    /* private mode */
  }
  return 'classic'
}

export function saveRoomVisual(visual: RoomVisual): void {
  try {
    localStorage.setItem(KEY, visual)
  } catch {
    /* ignore */
  }
}
