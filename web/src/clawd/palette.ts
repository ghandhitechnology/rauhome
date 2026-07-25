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

/**
 * Warm interior palette for the room scene.
 *
 * Built as a lived-in flat at dusk: warm greys on the walls, oiled walnut for
 * the furniture, and a small number of saturated accents (the rug, the books,
 * the lamp) that the eye can rest on. Every surface gets at least three tones —
 * a body, a lit edge and a shade — because a single flat colour is what makes
 * canvas art look like canvas art.
 */
export const ROOM = {
  wall: '#2A2320',
  wallLit: '#3A302B',
  wallShade: '#1C1714',
  wallWarm: '#453730',
  floor: '#2C2118',
  floorLit: '#42301F',
  floorWarm: '#543D26',
  floorSeam: '#170F09',
  skirting: '#171210',
  skirtingLit: '#33291F',
  wood: '#6B4A33',
  woodLit: '#87613F',
  woodShade: '#4A3122',
  woodDeep: '#33210F',
  walnut: '#553A28',
  walnutLit: '#71503A',
  metal: '#4A4440',
  metalLit: '#6A625C',
  metalDark: '#2C2926',
  brass: '#B08B4F',
  brassLit: '#DCB878',
  fabric: '#7A4436',
  fabricLit: '#955644',
  fabricDeep: '#572E24',
  rugInk: '#2E3F52',
  rugSand: '#C4A278',
  leaf: '#4C6B4A',
  leafLit: '#688A5F',
  leafDeep: '#2F4630',
  soil: '#2E241C',
  paper: '#E8E2D6',
  paperShade: '#B9B2A4',
  cork: '#8A6A44',
  screen: '#0E1418',
  screenGlow: '#D4634A',
  screenCode: '#7A8B96',
  screenKey: '#7FB8D4',
  screenString: '#C7A06A',
  lamp: '#FFC97A',
  lampDeep: '#C98A3A',
  glass: '#9FC4D8',
  dust: '#FFE9C4',
} as const

/** Book spines on the shelf: enough variety to read as a real collection. */
export const SPINES = [
  '#8A4B3A',
  '#5C6B7A',
  '#7A6A44',
  '#6B4A5C',
  '#4A6355',
  '#8A6A4A',
  '#3F5470',
  '#94614A',
  '#5A5342',
  '#7B4550',
] as const

/**
 * Sky gradients keyed to hour-of-day, for the window.
 *
 * `haze` is the band that sits right on the horizon behind the skyline —
 * always warmer and lighter than the sky above it, because that is where the
 * city's own light and the last of the sun collect.
 */
export const SKIES: {
  hour: number
  top: string
  bottom: string
  light: string
  haze: string
}[] = [
  { hour: 0, top: '#080C1A', bottom: '#161530', light: '#5C6BA8', haze: '#2A2440' },
  { hour: 4, top: '#101733', bottom: '#2C2745', light: '#6A6FA0', haze: '#463453' },
  { hour: 6, top: '#2A3560', bottom: '#7A5570', light: '#B08098', haze: '#B4715F' },
  { hour: 7.5, top: '#4A5B87', bottom: '#C88A6A', light: '#E0A070', haze: '#F0A878' },
  { hour: 10, top: '#6E93C4', bottom: '#AFC9DE', light: '#FFF2DC', haze: '#D8E4EC' },
  { hour: 14, top: '#7BA0CE', bottom: '#BFD6E6', light: '#FFF6E4', haze: '#E2EAF0' },
  { hour: 17, top: '#6B84B4', bottom: '#D8A177', light: '#FFC98E', haze: '#F0B584' },
  { hour: 18.5, top: '#5A6DA0', bottom: '#D98A5E', light: '#FFB472', haze: '#E8875A' },
  { hour: 20, top: '#2A2E52', bottom: '#6B4258', light: '#9A6A80', haze: '#8A4A55' },
  { hour: 22, top: '#111634', bottom: '#2A2340', light: '#6A6EA0', haze: '#3E2E48' },
  { hour: 24, top: '#080C1A', bottom: '#161530', light: '#5C6BA8', haze: '#2A2440' },
]

function mixHex(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  const r = Math.round((pa >> 16) + (((pb >> 16) - (pa >> 16)) * t))
  const g = Math.round(((pa >> 8) & 255) + ((((pb >> 8) & 255) - ((pa >> 8) & 255)) * t))
  const bl = Math.round((pa & 255) + (((pb & 255) - (pa & 255)) * t))
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0')}`
}

export function skyAt(hour: number): {
  top: string
  bottom: string
  light: string
  haze: string
} {
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
        haze: mixHex(a.haze, b.haze, t),
      }
    }
  }
  return SKIES[0]
}

export { mixHex }
