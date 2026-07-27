/**
 * Draws Clawd from a parameter set.
 *
 * Geometry follows the mascot as Anthropic draws it — a sprite made only of
 * squares on a 14 x 9.5 unit grid:
 *
 *   shell   x 2..12, y 0..7        (10 x 7)
 *   claws   2 x 2 at x 0 and x 12, y 2..4, pivoting on their inner edge
 *   legs    1 x 2.5 at x 2, 4, 9, 11, hanging from y 7
 *   eyes    1 x 1 at (4, 1.5) and (9, 1.5)
 *
 * One unit is one pixel block. Everything is drawn in unit space and scaled by
 * the caller, so the same code serves a 40px avatar and a full-screen scene.
 */

import { clamp01 } from './easing'
import { CLAWD, mixHex } from './palette'
import type { ParamSet } from './params'

export const GRID = { w: 14, h: 9.5 }

/** Where the sprite's feet sit, in unit space. Transforms anchor here. */
export const ANCHOR = { x: 7, y: 9.5 }

const SHELL = { x: 2, y: 0, w: 10, h: 7 }
const CLAW = { w: 2, h: 2, y: 2 }
const LEG_X = [2, 4, 9, 11]
const LEG = { y: 7, w: 1, h: 2.5 }
const EYE = { lx: 4, rx: 9, y: 1.5, s: 1 }

/** Sub-unit used for the curved "happy" eye overlay. */
const SUB = 0.4

export type DrawOpts = {
  /** Pixels per unit. */
  unit: number
  /** Where ANCHOR lands, in canvas pixels. */
  x: number
  y: number
  /** Tint multiplied over the sprite, for room lighting. */
  light?: string
  /** 0..1 — how strongly `light` is applied. */
  lightAmount?: number
  /** Drop the contact shadow (the room draws its own). */
  noShadow?: boolean
  /** Rim light colour from a nearby lamp or window. */
  rim?: string
  rimAmount?: number
}

function rect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  ctx.fillRect(x, y, w, h)
}

/** Legs alternate front/back pairs, so index parity picks the phase. */
function legAngle(p: ParamSet, index: number): number {
  const phase = p.legPhase + (index % 2 === 0 ? 0 : 0.5)
  return Math.sin(phase * Math.PI * 2) * p.legSwing
}

export function drawClawd(ctx: CanvasRenderingContext2D, p: ParamSet, o: DrawOpts) {
  const u = o.unit
  const facing = p.facing < 0 ? -1 : 1

  // Room lighting is mixed into the palette rather than composited over the
  // sprite. A source-atop overlay clips to whatever is already opaque on the
  // canvas, which — when drawing onto the room — is everything.
  const lit = o.light && (o.lightAmount ?? 0) > 0.01
  const amt = lit ? clamp01(o.lightAmount ?? 0) : 0
  const tone = (c: string) => (lit ? mixHex(c, o.light as string, amt) : c)
  const shell = tone(CLAWD.shell)
  const shellLit = tone(CLAWD.shellLit)
  const shellShade = tone(CLAWD.shellShade)
  const ink = tone(CLAWD.ink)

  ctx.save()
  ctx.translate(o.x, o.y)

  // Contact shadow lives in world space, so it is drawn before the body's
  // own rotation and squash are applied.
  if (!o.noShadow && p.shadow > 0.01) {
    const lift = clamp01(-p.posY / 8)
    const spread = 1 - lift * 0.45
    ctx.save()
    ctx.globalAlpha = 0.34 * p.shadow * (1 - lift * 0.5)
    ctx.fillStyle = '#000'
    ctx.beginPath()
    ctx.ellipse(p.posX * u, 0.35 * u, 5.4 * u * spread, 1.05 * u * spread, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }

  ctx.translate(p.posX * u, p.posY * u)
  ctx.rotate((p.angle * Math.PI) / 180)
  ctx.scale(p.scaleX * facing, p.scaleY)

  // Breathing is a gentle vertical swell centred on the shell.
  const breath = p.breath * 0.16
  ctx.translate(0, -breath * u * 0.5)

  // Move into sprite space: ANCHOR is now the origin.
  ctx.translate(-ANCHOR.x * u, -ANCHOR.y * u)

  const shellTop = SHELL.y - breath
  const shellH = SHELL.h + breath

  // ── legs ────────────────────────────────────────────────────────────
  LEG_X.forEach((lx, i) => {
    const angle = legAngle(p, i)
    ctx.save()
    ctx.translate((lx + LEG.w / 2) * u, LEG.y * u)
    ctx.rotate((angle * Math.PI) / 180)
    // Back pair sits a shade darker so the silhouette reads with depth.
    ctx.fillStyle = i % 2 === 0 ? shellShade : shell
    rect(ctx, (-LEG.w / 2) * u, 0, LEG.w * u, LEG.h * u)
    ctx.restore()
  })

  // ── claws ───────────────────────────────────────────────────────────
  const drawClaw = (side: -1 | 1, angleDeg: number) => {
    // Left claw hinges on its right edge, right claw on its left.
    const pivotX = side < 0 ? SHELL.x : SHELL.x + SHELL.w
    ctx.save()
    ctx.translate(pivotX * u, (CLAW.y + CLAW.h / 2) * u)
    ctx.rotate((angleDeg * side * -1 * Math.PI) / 180)
    ctx.fillStyle = shell
    const x = side < 0 ? -CLAW.w * u : 0
    rect(ctx, x, (-CLAW.h / 2) * u, CLAW.w * u, CLAW.h * u)
    // Pincer notch — one block of background carved out of the outer edge.
    ctx.fillStyle = shellShade
    const notchX = side < 0 ? -CLAW.w * u : (CLAW.w - 0.5) * u
    rect(ctx, notchX, (-CLAW.h / 2) * u, 0.5 * u, (CLAW.h / 2) * u)
    ctx.restore()
  }
  drawClaw(-1, p.clawL)
  drawClaw(1, p.clawR)

  // ── shell ───────────────────────────────────────────────────────────
  ctx.fillStyle = shell
  rect(ctx, SHELL.x * u, shellTop * u, SHELL.w * u, shellH * u)

  // Top-lit edge and grounded underside, one block each. The lit edge swells
  // with the voice — with no mouth to move, the shell itself has to read as
  // the thing that is speaking.
  ctx.fillStyle = shellLit
  rect(ctx, SHELL.x * u, shellTop * u, SHELL.w * u, (0.5 + clamp01(p.talkLevel) * 0.3) * u)
  ctx.fillStyle = shellShade
  rect(ctx, SHELL.x * u, (shellTop + shellH - 0.5) * u, SHELL.w * u, 0.5 * u)

  // Rim light from the window, lamp or monitor. These blocks already sit
  // inside the shell, so they need no clipping.
  if (o.rim && (o.rimAmount ?? 0) > 0.01) {
    ctx.save()
    ctx.globalAlpha = clamp01(o.rimAmount ?? 0)
    ctx.fillStyle = o.rim
    rect(ctx, SHELL.x * u, shellTop * u, 0.5 * u, shellH * u)
    rect(ctx, SHELL.x * u, shellTop * u, SHELL.w * u, 0.5 * u)
    ctx.restore()
  }

  // ── eyes ────────────────────────────────────────────────────────────
  const eyeDX = p.eyeX * 0.45
  const eyeDY = p.eyeY * 0.35
  const smile = clamp01(p.eyeSmile)

  const drawEye = (ex: number, open: number) => {
    const o01 = clamp01(open)
    if (smile > 0.98) return
    const h = EYE.s * o01
    if (h <= 0.02) {
      // Fully shut: a single flat lid line so the face never goes blank.
      ctx.fillStyle = ink
      ctx.globalAlpha = 1 - smile
      rect(ctx, (ex + eyeDX) * u, (EYE.y + EYE.s / 2 - 0.12 + eyeDY) * u, EYE.s * u, 0.24 * u)
      ctx.globalAlpha = 1
      return
    }
    ctx.fillStyle = ink
    ctx.globalAlpha = 1 - smile
    rect(ctx, (ex + eyeDX) * u, (EYE.y + (EYE.s - h) / 2 + eyeDY) * u, EYE.s * u, h * u)
    ctx.globalAlpha = 1
  }

  drawEye(EYE.lx, p.eyeOpenL)
  drawEye(EYE.rx, p.eyeOpenR)

  // Happy arc eyes: four sub-blocks per eye forming an upward curve.
  if (smile > 0.02) {
    ctx.fillStyle = ink
    ctx.globalAlpha = smile
    for (const ex of [EYE.lx, EYE.rx]) {
      const bx = (ex - 0.2 + eyeDX) * u
      const by = (EYE.y + 0.2 + eyeDY) * u
      rect(ctx, bx + SUB * u, by, SUB * u, SUB * u)
      rect(ctx, bx + SUB * 2 * u, by, SUB * u, SUB * u)
      rect(ctx, bx, by + SUB * u, SUB * u, SUB * u)
      rect(ctx, bx + SUB * 3 * u, by + SUB * u, SUB * u, SUB * u)
    }
    ctx.globalAlpha = 1
  }

  ctx.restore()
}

/* ── anchors ──────────────────────────────────────────────────────────
 *
 * Where things he is *holding* have to be, in the same canvas space the
 * sprite is drawn in. Everything below re-walks `drawClawd`'s transform
 * chain rather than approximating it: the cards in his claws have to sit
 * exactly where the claws are, through squash, lean, breath and facing, or
 * they read as floating next to him instead of held by him.
 *
 * The maths is done longhand rather than with DOMMatrix so it also runs
 * under the node test environment.
 */

type Affine = { a: number; b: number; c: number; d: number; e: number; f: number }

const IDENTITY: Affine = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }

/** `m` then `n`, matching how canvas transforms post-multiply. */
function compose(m: Affine, n: Affine): Affine {
  return {
    a: m.a * n.a + m.c * n.b,
    b: m.b * n.a + m.d * n.b,
    c: m.a * n.c + m.c * n.d,
    d: m.b * n.c + m.d * n.d,
    e: m.a * n.e + m.c * n.f + m.e,
    f: m.b * n.e + m.d * n.f + m.f,
  }
}

const translated = (m: Affine, x: number, y: number) =>
  compose(m, { a: 1, b: 0, c: 0, d: 1, e: x, f: y })

const scaled = (m: Affine, x: number, y: number) =>
  compose(m, { a: x, b: 0, c: 0, d: y, e: 0, f: 0 })

function rotated(m: Affine, deg: number): Affine {
  const r = (deg * Math.PI) / 180
  const cos = Math.cos(r)
  const sin = Math.sin(r)
  return compose(m, { a: cos, b: sin, c: -sin, d: cos, e: 0, f: 0 })
}

const at = (m: Affine, x: number, y: number) => ({
  x: m.a * x + m.c * y + m.e,
  y: m.b * x + m.d * y + m.f,
})

export type Anchors = {
  /** Outer tip of each claw. */
  pawL: { x: number; y: number }
  pawR: { x: number; y: number }
  /** Where a held fan of cards sits — between the claws, a shade below them. */
  fan: { x: number; y: number }
  head: { x: number; y: number }
  chest: { x: number; y: number }
  /** Body tilt in degrees, so held things lean with him. */
  angle: number
  /** Vertical squash, so held things move with a flinch. */
  squash: number
}

/**
 * Points on the drawn sprite, in the same canvas pixels `clawdBounds` returns.
 *
 * Breathing is inside the chain, so anything anchored here rises and falls
 * with him without a line of code spent on it.
 */
export function clawdAnchors(
  p: ParamSet,
  o: Pick<DrawOpts, 'unit' | 'x' | 'y'>,
): Anchors {
  const u = o.unit
  const facing = p.facing < 0 ? -1 : 1

  let m = translated(IDENTITY, o.x, o.y)
  m = translated(m, p.posX * u, p.posY * u)
  m = rotated(m, p.angle)
  m = scaled(m, p.scaleX * facing, p.scaleY)
  const breath = p.breath * 0.16
  m = translated(m, 0, -breath * u * 0.5)
  m = translated(m, -ANCHOR.x * u, -ANCHOR.y * u)

  // Same pivot and sign convention as `drawClaw`, so the tip lands on the
  // block the renderer actually paints.
  const clawTip = (side: -1 | 1, angleDeg: number) => {
    const pivotX = side < 0 ? SHELL.x : SHELL.x + SHELL.w
    let c = translated(m, pivotX * u, (CLAW.y + CLAW.h / 2) * u)
    c = rotated(c, angleDeg * side * -1)
    return at(c, side < 0 ? -CLAW.w * u : CLAW.w * u, 0)
  }

  const pawL = clawTip(-1, p.clawL)
  const pawR = clawTip(1, p.clawR)
  const midX = SHELL.x + SHELL.w / 2

  // A fan of cards is held against the lower body, not up at eye level — and
  // it has to be, because the whole point of him holding cards is that you
  // can still see his face over the top of them. So the anchor sits low on
  // the shell and is only pulled part way toward the claws: enough that
  // dealing visibly jostles the hand, not so much that a raised pincer lifts
  // the cards over his eyes.
  const hold = at(m, midX * u, (SHELL.y + 5) * u)
  const pawMidX = (pawL.x + pawR.x) / 2
  const pawMidY = (pawL.y + pawR.y) / 2

  return {
    pawL,
    pawR,
    fan: {
      x: hold.x * 0.55 + pawMidX * 0.45,
      y: hold.y * 0.75 + pawMidY * 0.25,
    },
    head: at(m, midX * u, (SHELL.y + EYE.y) * u),
    chest: at(m, midX * u, (SHELL.y + 4) * u),
    angle: p.angle,
    squash: p.scaleY,
  }
}

/** Bounding box of the drawn sprite in canvas pixels, for hit testing. */
export function clawdBounds(p: ParamSet, o: Pick<DrawOpts, 'unit' | 'x' | 'y'>) {
  const u = o.unit
  const w = GRID.w * u * p.scaleX
  const h = GRID.h * u * p.scaleY
  return {
    x: o.x + p.posX * u - w / 2,
    y: o.y + p.posY * u - h,
    w,
    h,
  }
}
