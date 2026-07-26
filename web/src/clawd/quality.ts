/**
 * How much work the room is allowed to do per frame.
 *
 * The scene is drawn on a 2D canvas at the full size of the window, so its cost
 * scales with the machine it is running on and nothing else. On a laptop with
 * integrated graphics the difference between "every surface has grain" and "the
 * character animates smoothly" is not a close call — a room that stutters does
 * not read as alive however good the still frame looks.
 *
 * Three tiers, and the default is chosen for the machine rather than for the
 * screenshot. Everything here is a *budget*, not a switch: the composition,
 * the architecture and the props are identical at every tier. What changes is
 * how much incidental detail is spent on top.
 */

export type QualityTier = 'low' | 'balanced' | 'high'

export type QualityBudget = {
  tier: QualityTier
  /** Per-pixel material grain (plaster, wood, weave). The costliest pass. */
  textures: boolean
  /** Soft damp/wear stains on the wall — nine radial gradients. */
  stains: boolean
  /** Dust in the light shaft and the lamp cone. */
  motes: number
  /** Stars in the window after dark. */
  stars: number
  /** Drifting cloud bands. */
  clouds: number
  /** Nail heads and staggered board ends in the floor. */
  floorDetail: boolean
  /** Film grain over the finished frame. */
  grain: boolean
}

const BUDGETS: Record<QualityTier, QualityBudget> = {
  high: {
    tier: 'high',
    textures: true,
    stains: true,
    motes: 46,
    stars: 46,
    clouds: 7,
    floorDetail: true,
    grain: true,
  },
  balanced: {
    tier: 'balanced',
    textures: true,
    stains: true,
    motes: 20,
    stars: 24,
    clouds: 4,
    floorDetail: true,
    grain: true,
  },
  low: {
    tier: 'low',
    // The baked backdrop keeps the architecture and the tones; what goes is
    // the per-pixel grain over the top of it and the per-frame atmospherics.
    textures: false,
    stains: false,
    motes: 0,
    stars: 12,
    clouds: 2,
    floorDetail: false,
    grain: false,
  },
}

const KEY = 'rau.quality'

/**
 * Guess the machine before the first frame is drawn.
 *
 * Core count and memory are crude, but they are the only signals available
 * without rendering something first and timing it — and a first second of
 * stutter while we measure is exactly what this is trying to avoid. The
 * automatic answer is deliberately conservative; the user can override.
 */
export function detectTier(): QualityTier {
  if (typeof navigator === 'undefined') return 'balanced'
  const nav = navigator as Navigator & { deviceMemory?: number }
  const cores = nav.hardwareConcurrency || 4
  const memory = nav.deviceMemory || 4
  const pixels =
    typeof window !== 'undefined' ? window.innerWidth * window.innerHeight : 1e6

  if (cores <= 2 || memory <= 2) return 'low'
  // A big display on a modest machine is the classic stutter case: cost scales
  // with pixels, and there are a lot of them.
  if (cores <= 4 && pixels > 1.6e6) return 'low'
  if (cores <= 4 || memory <= 4) return 'balanced'
  if (pixels > 4e6 && cores < 8) return 'balanced'
  return 'high'
}

function stored(): QualityTier | null {
  try {
    const value = localStorage.getItem(KEY)
    if (value === 'low' || value === 'balanced' || value === 'high') return value
  } catch {
    /* private mode */
  }
  return null
}

/**
 * Both answers are resolved once and kept.
 *
 * `quality()` is read several times per frame — by the sky, the light shaft,
 * the lamp cone, the film grain and both cache keys. Asking localStorage each
 * time would put a synchronous storage read on the hot path, and `detectTier`
 * reads `window.innerWidth`, which can force a layout. Either would be a
 * per-frame cost in the middle of a change whose whole point is removing them.
 */
let chosen: QualityTier | null = stored()
let detected: QualityTier | null = null

/** The tier in force: the user's choice, else what the machine looks like. */
export function currentTier(): QualityTier {
  if (chosen) return chosen
  // Deliberately not re-detected on resize: a tier that flips mid-session
  // would repaint every baked layer at the moment the window is being dragged.
  if (!detected) detected = detectTier()
  return detected
}

export function quality(): QualityBudget {
  return BUDGETS[currentTier()]
}

export function setTier(tier: QualityTier): void {
  chosen = tier
  try {
    localStorage.setItem(KEY, tier)
  } catch {
    /* ignore — the choice still holds for this session */
  }
}

/** Forget an explicit choice and go back to judging the machine. */
export function clearTier(): void {
  chosen = null
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

/** For the settings UI: whether the current tier was chosen or detected. */
export function tierIsAutomatic(): boolean {
  return chosen === null
}

/** Another tab changed the setting. Only the UI needs telling; see `Face`. */
export function adoptStoredTier(): QualityTier {
  chosen = stored()
  return currentTier()
}
