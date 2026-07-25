/** Easing curves for motion keyframes. All take and return 0..1. */

export type Ease = keyof typeof EASES

export const EASES = {
  linear: (t: number) => t,
  in: (t: number) => t * t,
  out: (t: number) => 1 - (1 - t) * (1 - t),
  inOut: (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2),
  inCubic: (t: number) => t * t * t,
  outCubic: (t: number) => 1 - (1 - t) ** 3,
  inOutCubic: (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
  /** Overshoots past the target then settles — good for anticipation snaps. */
  outBack: (t: number) => {
    const c1 = 1.70158
    const c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
  },
  /** Fast rise, small wobble. Reads as elastic without the long tail. */
  outSpring: (t: number) => {
    if (t >= 1) return 1
    return 1 - Math.cos(t * Math.PI * 2.2) * Math.exp(-t * 5.2)
  },
  /** Bounces to rest — used for landings. */
  outBounce: (t: number) => {
    const n1 = 7.5625
    const d1 = 2.75
    if (t < 1 / d1) return n1 * t * t
    if (t < 2 / d1) return n1 * (t -= 1.5 / d1) * t + 0.75
    if (t < 2.5 / d1) return n1 * (t -= 2.25 / d1) * t + 0.9375
    return n1 * (t -= 2.625 / d1) * t + 0.984375
  },
} satisfies Record<string, (t: number) => number>

export function ease(name: Ease | undefined, t: number): number {
  return (EASES[name || 'inOut'] || EASES.inOut)(t)
}

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t

export const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v)

export const clamp01 = (v: number) => clamp(v, 0, 1)

/** Frame-rate independent exponential approach. `speed` is roughly 1/seconds. */
export function damp(current: number, target: number, speed: number, dt: number): number {
  return lerp(current, target, 1 - Math.exp(-speed * dt))
}
