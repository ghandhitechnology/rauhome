/**
 * Secondary motion. Cubism ships a physics system that drives parameters from
 * the model's own movement; this is the same idea at a much smaller scale —
 * critically-damped springs that let the claws lag behind the body and settle
 * with a little overshoot instead of snapping to their keyframed pose.
 */

export class Spring {
  value: number
  private velocity = 0
  /** Higher = snappier. Roughly the natural frequency in rad/s. */
  private stiffness: number
  /** 1 is critically damped; below 1 overshoots. */
  private damping: number

  constructor(initial: number, stiffness = 120, damping = 0.65) {
    this.value = initial
    this.stiffness = stiffness
    this.damping = damping
  }

  set(v: number) {
    this.value = v
    this.velocity = 0
  }

  update(target: number, dt: number): number {
    // Sub-step so a dropped frame cannot make the spring explode.
    const steps = Math.min(4, Math.max(1, Math.ceil(dt / 0.016)))
    const h = dt / steps
    const k = this.stiffness
    const c = 2 * this.damping * Math.sqrt(k)
    for (let i = 0; i < steps; i++) {
      const accel = k * (target - this.value) - c * this.velocity
      this.velocity += accel * h
      this.value += this.velocity * h
    }
    return this.value
  }
}

/**
 * A trailing value that only reacts to how fast its driver is moving — used to
 * tip Clawd into a lean when he accelerates, then let it wash out.
 */
export class Inertia {
  private last: number | null = null
  private spring: Spring

  constructor(stiffness = 60, damping = 0.7) {
    this.spring = new Spring(0, stiffness, damping)
  }

  update(driver: number, dt: number, scale = 1): number {
    // Seed on the first sample. Without this, a driver that starts at a
    // non-zero value reads as one enormous velocity spike and rings the
    // spring against its clamp for seconds.
    if (this.last === null) this.last = driver
    const velocity = dt > 0 ? (driver - this.last) / dt : 0
    this.last = driver
    return this.spring.update(velocity * scale, dt)
  }
}

/** Deterministic 1D value noise — smooth wander without Math.random jitter. */
export function noise1(x: number): number {
  const i = Math.floor(x)
  const f = x - i
  const h = (n: number) => {
    const s = Math.sin(n * 127.1) * 43758.5453
    return s - Math.floor(s)
  }
  const a = h(i)
  const b = h(i + 1)
  const u = f * f * (3 - 2 * f)
  return (a + (b - a) * u) * 2 - 1
}
