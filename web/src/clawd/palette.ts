/**
 * Clawd's palette, matching the mascot as it appears in Anthropic's own
 * material: a clay-orange sprite built from squares with two dark eyes.
 */
export const CLAWD = {
  shell: '#D4634A',
  shellLit: '#E87C60',
  shellShade: '#A8452F',
  shellDeep: '#8A3524',
  ink: '#2A1810',
  highlight: '#F4A98F',
} as const

/** Warm interior palette for the room scene. */
export const ROOM = {
  wall: '#2A2320',
  wallLit: '#3A302B',
  wallShade: '#1C1714',
  floor: '#241D1A',
  floorLit: '#332A25',
  skirting: '#171210',
  wood: '#6B4A33',
  woodLit: '#87613F',
  woodShade: '#4A3122',
  metal: '#4A4440',
  metalLit: '#6A625C',
  fabric: '#7A4436',
  fabricLit: '#955644',
  leaf: '#4C6B4A',
  leafLit: '#688A5F',
  paper: '#E8E2D6',
  screen: '#0E1418',
  screenGlow: '#D4634A',
  lamp: '#FFC97A',
} as const

/** Sky gradients keyed to hour-of-day, for the window. */
export const SKIES: { hour: number; top: string; bottom: string; light: string }[] = [
  { hour: 0, top: '#0B1020', bottom: '#1A1830', light: '#5C6BA8' },
  { hour: 5, top: '#1E2140', bottom: '#4A3550', light: '#8A6A90' },
  { hour: 7, top: '#4A5B87', bottom: '#C88A6A', light: '#E0A070' },
  { hour: 10, top: '#6E93C4', bottom: '#AFC9DE', light: '#FFF2DC' },
  { hour: 14, top: '#7BA0CE', bottom: '#BFD6E6', light: '#FFF6E4' },
  { hour: 18, top: '#5A6DA0', bottom: '#D98A5E', light: '#FFB472' },
  { hour: 20, top: '#2A2E52', bottom: '#6B4258', light: '#9A6A80' },
  { hour: 24, top: '#0B1020', bottom: '#1A1830', light: '#5C6BA8' },
]

function mixHex(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const r = Math.round((pa >> 16) + (((pb >> 16) - (pa >> 16)) * t))
  const g = Math.round(((pa >> 8) & 255) + ((((pb >> 8) & 255) - ((pa >> 8) & 255)) * t))
  const bl = Math.round((pa & 255) + (((pb & 255) - (pa & 255)) * t))
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0')}`
}

export function skyAt(hour: number): { top: string; bottom: string; light: string } {
  const h = ((hour % 24) + 24) % 24
  for (let i = 0; i < SKIES.length - 1; i++) {
    const a = SKIES[i]
    const b = SKIES[i + 1]
    if (h >= a.hour && h <= b.hour) {
      const t = b.hour === a.hour ? 0 : (h - a.hour) / (b.hour - a.hour)
      return {
        top: mixHex(a.top, b.top, t),
        bottom: mixHex(a.bottom, b.bottom, t),
        light: mixHex(a.light, b.light, t),
      }
    }
  }
  return SKIES[0]
}

export { mixHex }
