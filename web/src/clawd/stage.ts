/**
 * The stage's fixed dimensions and the drawing primitives everything shares.
 *
 * These live apart from `room.ts` because the room now draws layers that also
 * need them — the movable props most of all — and a layer importing the room
 * while the room imports the layer is a cycle that resolves to a temporal dead
 * zone at module load, not to anything as recoverable as `undefined`.
 */

export const STAGE = { w: 160, h: 90 }

/** Y of the floor line, in stage units. Clawd's feet rest here. */
export const FLOOR_Y = 68

/** Horizontal range Clawd is allowed to walk between. */
export const WALK_RANGE = { min: 14, max: 146 }

type Ctx = CanvasRenderingContext2D

/** Fill a rect in stage units. */
export function rect(
  ctx: Ctx,
  u: number,
  x: number,
  y: number,
  w: number,
  h: number,
  fill: string,
) {
  ctx.fillStyle = fill
  ctx.fillRect(x * u, y * u, w * u, h * u)
}

/**
 * Soft dark ellipse where an object meets the surface under it.
 *
 * Anything drawn without one floats, and the eye notices immediately even
 * when it cannot say why.
 */
export function contactShadow(
  ctx: Ctx,
  u: number,
  cx: number,
  cy: number,
  rx: number,
  ry: number,
  alpha = 0.5,
) {
  if (rx <= 0 || ry <= 0) return
  ctx.save()
  const g = ctx.createRadialGradient(cx * u, cy * u, 0, cx * u, cy * u, rx * u)
  g.addColorStop(0, `rgba(0,0,0,${alpha})`)
  g.addColorStop(0.6, `rgba(0,0,0,${alpha * 0.42})`)
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.beginPath()
  ctx.ellipse(cx * u, cy * u, rx * u, ry * u, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}
