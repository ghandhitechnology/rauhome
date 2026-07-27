/**
 * The room Clawd lives in.
 *
 * A side-on interior drawn in the same square-pixel language as the sprite,
 * composed back-to-front: wall, window and its light, wall furniture, floor,
 * then the standing furniture, then lighting and grade passes over the top.
 * Everything is laid out in a fixed 160 x 90 unit stage and scaled to fit the
 * viewport, so the composition holds at any window size.
 *
 * Three rules do most of the work of making it feel like somewhere real
 * rather than a diagram of somewhere real:
 *
 *   1. No surface is one flat colour. Every material gets a body tone, a lit
 *      edge, a shade, and a texture pass (see `texture.ts`).
 *   2. Everything touching the floor casts a contact shadow. Objects that do
 *      not are objects that float, and the eye notices immediately even when
 *      it cannot say why.
 *   3. Light is drawn as something in the air, not just something on surfaces:
 *      the shaft from the window, the cone from the lamp and the spill from
 *      the monitor are all volumes, and they tint what is near them.
 */

import { clamp, clamp01 } from './easing'
import { mixHex, ROOM, SPINES, skyAt } from './palette'
import { bakeBackdrop, bakeForeground, blitBackdrop, unitKey } from './backdrop'
import { drawWallPanels, panelsOwnPosterSlot, wallPanelsKey } from './panelsLayer'
import { quality } from './quality'
import { drawLivingProps, drawRestingProps, restingPropsKey } from './propsLayer'
import { contactShadow, FLOOR_Y, STAGE, WALK_RANGE } from './stage'
import { hash2, textureRect } from './texture'

export { STAGE, FLOOR_Y, WALK_RANGE }

/**
 * How far past the stage the room is painted.
 *
 * The camera pans up to ±18 units while following, so a room drawn exactly
 * 160 wide shows a hard edge of nothing at the extremes. Cheap to paint, and
 * the alternative is a black bar sliding in from the side.
 */
const BLEED = 26
const ROOM_LEFT = -BLEED
const ROOM_W = STAGE.w + BLEED * 2

export type StationId =
  | 'desk'
  | 'window'
  | 'shelf'
  | 'rug'
  | 'centre'
  | 'plant'
  | 'table'

export type Station = {
  id: StationId
  /** Where Clawd stands, in stage units. */
  x: number
  /** Which way he faces once he arrives. */
  facing: 1 | -1
  label: string
}

export const STATIONS: Station[] = [
  { id: 'window', x: 34, facing: -1, label: 'the window' },
  { id: 'plant', x: 55, facing: 1, label: 'the plant' },
  // Far enough from centre to be a different place: the walk deadband is 1.2
  // units, so a rug at 79 and a centre at 80 were the same spot with two names.
  { id: 'rug', x: 70, facing: 1, label: 'the rug' },
  // Where he sits to play. Far enough from centre that being sent here is a
  // walk you can watch rather than a shuffle, and it must match
  // `GAME_TABLE.x` — he has to end up behind the table, not beside it.
  { id: 'table', x: 72, facing: 1, label: 'the card table' },
  { id: 'centre', x: 80, facing: 1, label: 'the middle of the room' },
  { id: 'desk', x: 108, facing: 1, label: 'the desk' },
  { id: 'shelf', x: 138, facing: 1, label: 'the shelf' },
]

export function station(id: StationId): Station {
  return STATIONS.find((s) => s.id === id) || STATIONS.find((s) => s.id === 'centre')!
}

export type RoomState = {
  /** 0..24, drives the window sky and the light temperature. */
  hour: number
  /** Desk lamp on/off, 0..1 for the fade. */
  lamp: number
  /** Monitor glow, 0..1 — pulses when Rau is working. */
  screen: number
  /** Seconds since the scene started, for dust and parallax. */
  time: number
}

type Ctx = CanvasRenderingContext2D

// ── primitives ────────────────────────────────────────────────────────

/** Fill a rect in stage units. */
function r(ctx: Ctx, u: number, x: number, y: number, w: number, h: number, fill: string) {
  ctx.fillStyle = fill
  ctx.fillRect(x * u, y * u, w * u, h * u)
}

/**
 * A solid with a lit top edge and a shaded bottom, which is the cheapest way
 * to make a rectangle read as having a thickness.
 */
function slab(
  ctx: Ctx,
  u: number,
  x: number,
  y: number,
  w: number,
  h: number,
  body: string,
  lit: string,
  shade: string,
  edge = 0.5,
) {
  r(ctx, u, x, y, w, h, body)
  r(ctx, u, x, y, w, edge, lit)
  r(ctx, u, x, y + h - edge, w, edge, shade)
}

/** Additive glow, for anything that is itself a light source. */
function glow(
  ctx: Ctx,
  u: number,
  cx: number,
  cy: number,
  radius: number,
  colour: string,
  alpha: number,
) {
  if (alpha <= 0.004) return
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = alpha
  const g = ctx.createRadialGradient(cx * u, cy * u, 0, cx * u, cy * u, radius * u)
  g.addColorStop(0, colour)
  g.addColorStop(0.45, colour)
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.fillRect((cx - radius) * u, (cy - radius) * u, radius * 2 * u, radius * 2 * u)
  ctx.restore()
}

/** How much daylight there is, 0..1. */
function daylightAt(hour: number): number {
  return 1 - clamp01((Math.abs(hour - 13) - 3.5) / 5.5)
}

/** How dark it is outside, 0..1 — drives lit city windows and stars. */
function nightAt(hour: number): number {
  return clamp01((Math.abs(hour - 13) - 4) / 5)
}

// ── window ────────────────────────────────────────────────────────────

const WINDOW = { x: 20, y: 10, w: 34, h: 34 }

/** Sky, city and glass, inside the window opening. */
function drawSky(ctx: Ctx, u: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const { x, y, w, h } = WINDOW
  const night = nightAt(s.hour)

  ctx.save()
  ctx.beginPath()
  ctx.rect(x * u, y * u, w * u, h * u)
  ctx.clip()

  // Sky: cool above, hazy where it meets the city.
  const grad = ctx.createLinearGradient(0, y * u, 0, (y + h) * u)
  grad.addColorStop(0, sky.top)
  grad.addColorStop(0.62, sky.bottom)
  grad.addColorStop(1, sky.haze)
  ctx.fillStyle = grad
  ctx.fillRect(x * u, y * u, w * u, h * u)

  // Stars and cloud drift are the only parts of the view that move, so they
  // are drawn live over this bake by `drawSkyLife`.

  // Sun or moon, tracking an arc across the opening through the day.
  const dayT = clamp01((s.hour - 6) / 12)
  const up = Math.sin(dayT * Math.PI)
  if (s.hour > 5.4 && s.hour < 18.6 && up > 0) {
    const sx = x + 4 + dayT * (w - 8)
    const sy = y + h * 0.66 - up * h * 0.5
    glow(ctx, u, sx, sy, 11, sky.light, 0.5 * up)
    r(ctx, u, sx - 1.4, sy - 1.4, 2.8, 2.8, '#FFF8E8')
  } else if (night > 0.3) {
    const moonT = clamp01(((s.hour + 12) % 24) / 24)
    const mx = x + 5 + moonT * (w - 10)
    const my = y + 6 + Math.cos(moonT * Math.PI) * 3
    glow(ctx, u, mx, my, 9, '#BFD0F0', 0.36 * night)
    r(ctx, u, mx - 1.3, my - 1.3, 2.6, 2.6, '#E8EEFF')
    r(ctx, u, mx - 0.1, my - 1.1, 1.4, 2.2, mixHex('#E8EEFF', sky.top, 0.55))
  }


  // Skyline in two layers, the near one darker — the whole reason a city
  // reads as having depth rather than being a cut-out.
  const far = mixHex(sky.haze, '#0B0A12', 0.5)
  const near = mixHex(sky.bottom, '#08070E', 0.78)
  const layers: { tone: string; base: number; blocks: number[][]; lit: number }[] = [
    { tone: far, base: y + h - 2, blocks: [[1, 6, 8], [8, 4, 12], [13, 7, 6], [21, 5, 11], [27, 6, 7], [34, 5, 9]], lit: 0.5 },
    { tone: near, base: y + h, blocks: [[-1, 7, 6], [7, 5, 9], [13, 4, 5], [18, 8, 8], [27, 4, 6], [32, 7, 10]], lit: 1 },
  ]
  for (const layer of layers) {
    for (const [bx, bw, bh] of layer.blocks) {
      r(ctx, u, x + bx, layer.base - bh, bw, bh, layer.tone)
      // Roofline lip, so towers do not read as bare rectangles.
      r(ctx, u, x + bx, layer.base - bh, bw, 0.4, mixHex(layer.tone, '#FFFFFF', 0.12))
      if (night <= 0.2) continue
      for (let wy = 1; wy < bh - 1; wy += 2.2) {
        for (let wx = 0.8; wx < bw - 1.2; wx += 1.9) {
          if (hash2(bx + wx, wy + bh, 5) > 0.52) continue
          ctx.globalAlpha = night * layer.lit * (0.35 + hash2(bx + wx, wy, 6) * 0.65)
          r(ctx, u, x + bx + wx, layer.base - bh + wy, 0.7, 0.9, ROOM.lamp)
        }
      }
      ctx.globalAlpha = 1
    }
  }

  // Glass: a diagonal sheen and a cool cast, so the opening reads as glazed
  // rather than as a hole in the wall.
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 0.06 + daylightAt(s.hour) * 0.07
  const sheen = ctx.createLinearGradient(x * u, y * u, (x + w) * u, (y + h) * u)
  sheen.addColorStop(0, 'rgba(0,0,0,0)')
  sheen.addColorStop(0.42, ROOM.glass)
  sheen.addColorStop(0.52, 'rgba(0,0,0,0)')
  sheen.addColorStop(0.72, ROOM.glass)
  sheen.addColorStop(0.82, 'rgba(0,0,0,0)')
  ctx.fillStyle = sheen
  ctx.fillRect(x * u, y * u, w * u, h * u)
  ctx.globalCompositeOperation = 'source-over'
  ctx.globalAlpha = 1

  // Condensation gathering in the bottom corners on a cold night.
  if (night > 0.5) {
    ctx.globalAlpha = night * 0.25
    for (let i = 0; i < 40; i++) {
      const dx = x + 1 + hash2(i, 21, 2) * (w - 2)
      const dy = y + h - 1 - hash2(i, 22, 2) * h * 0.3
      r(ctx, u, dx, dy, 0.35, 0.35, '#CFE0F0')
    }
    ctx.globalAlpha = 1
  }

  ctx.restore()
}

/** The opening's recess and its sill — masonry, so it bakes. */
function drawWindowRecess(ctx: Ctx, u: number) {
  const { x, y, w, h } = WINDOW

  // Reveal: the wall has thickness, so the opening sits in a recess. The lip
  // is a shadow, not a black bar — at full contrast it detaches from the wall
  // and floats across the top of the frame as a stripe of nothing.
  r(ctx, u, x - 2.2, y - 2.2, w + 4.4, h + 4.4, ROOM.wallShade)
  ctx.save()
  const lip = ctx.createLinearGradient(0, (y - 2.2) * u, 0, (y + 1.5) * u)
  lip.addColorStop(0, mixHex(ROOM.wallShade, '#000000', 0.45))
  lip.addColorStop(1, ROOM.wallShade)
  ctx.fillStyle = lip
  ctx.fillRect((x - 2.2) * u, (y - 2.2) * u, (w + 4.4) * u, 3.7 * u)
  ctx.restore()
  // A hairline of light on the reveal's outer edge, where it catches the room.
  r(ctx, u, x - 2.2, y - 2.2, w + 4.4, 0.28, mixHex(ROOM.wallWarm, '#FFFFFF', 0.1))

  // Sill with a nosing and the shadow it throws on the wall below.
  slab(ctx, u, x - 3, y + h, w + 6, 2.2, ROOM.wood, ROOM.woodLit, ROOM.woodShade, 0.5)
  textureRect(ctx, 'wood', u, x - 3, y + h, w + 6, 2.2, 0.5)
  ctx.save()
  ctx.globalAlpha = 0.4
  const sillShadow = ctx.createLinearGradient(0, (y + h + 2.2) * u, 0, (y + h + 7) * u)
  sillShadow.addColorStop(0, 'rgba(0,0,0,0.6)')
  sillShadow.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = sillShadow
  ctx.fillRect((x - 3) * u, (y + h + 2.2) * u, (w + 6) * u, 4.8 * u)
  ctx.restore()
}

/**
 * The parts of the view that move: stars breathing, cloud bands drifting.
 *
 * Everything else behind the glass — the gradient, the city, the sun — is
 * baked with the hour, because it only changes as the light does.
 */
function drawSkyLife(ctx: Ctx, u: number, s: RoomState) {
  const { x, y, w, h } = WINDOW
  const night = nightAt(s.hour)
  const budget = quality()
  if (night <= 0.15 && budget.clouds === 0) return

  ctx.save()
  ctx.beginPath()
  ctx.rect(x * u, y * u, w * u, h * u)
  ctx.clip()

  if (night > 0.15) {
    for (let i = 0; i < budget.stars; i++) {
      const sx = x + hash2(i, 1, 7) * w
      const sy = y + hash2(i, 2, 7) * h * 0.62
      const tw = 0.45 + 0.55 * (Math.sin(s.time * 0.9 + i * 2.1) * 0.5 + 0.5)
      ctx.globalAlpha = night * 0.8 * tw * (0.35 + hash2(i, 3, 7) * 0.65)
      r(ctx, u, sx, sy, 0.42, 0.42, '#FFF6E0')
    }
  }

  const sky = skyAt(s.hour)
  ctx.globalAlpha = 0.16 + (1 - night) * 0.16
  ctx.fillStyle = mixHex(sky.haze, '#FFFFFF', 0.35)
  for (let i = 0; i < budget.clouds; i++) {
    const drift = (s.time * (0.22 + (i % 3) * 0.12) + i * 13) % (w + 30)
    const cx = x - 14 + drift
    const cy = y + 3 + hash2(i, 9, 3) * h * 0.42
    const cw = 7 + hash2(i, 10, 3) * 12
    ctx.fillRect(cx * u, cy * u, cw * u, 1.6 * u)
    ctx.fillRect((cx + 2) * u, (cy - 1.1) * u, (cw - 5) * u, 1.2 * u)
  }
  ctx.restore()
}

/**
 * Joinery over the glass.
 *
 * Not baked: the sky behind it is drawn live, so the bars have to go back on
 * top afterwards or the view covers its own window.
 */
function drawWindowFrame(ctx: Ctx, u: number) {
  const { x, y, w, h } = WINDOW

  const bar = (bx: number, by: number, bw: number, bh: number) => {
    r(ctx, u, bx, by, bw, bh, ROOM.woodShade)
    r(ctx, u, bx, by, bw, Math.min(0.45, bh), mixHex(ROOM.wood, '#FFFFFF', 0.18))
  }
  bar(x + w / 2 - 0.7, y, 1.4, h)
  bar(x, y + h * 0.44 - 0.7, w, 1.4)

  ctx.strokeStyle = ROOM.woodShade
  ctx.lineWidth = 2.2 * u
  ctx.strokeRect(x * u, y * u, w * u, h * u)
  ctx.strokeStyle = mixHex(ROOM.wood, '#FFFFFF', 0.22)
  ctx.lineWidth = 0.5 * u
  ctx.strokeRect((x + 1.1) * u, (y + 1.1) * u, (w - 2.2) * u, (h - 2.2) * u)
}

/** A little pot and a forgotten mug on the sill — signs of use. */
function drawSillObjects(ctx: Ctx, u: number, s: RoomState) {
  const { x, y, h } = WINDOW
  const base = y + h

  // Small pot, left of the opening.
  const px = x + 2
  r(ctx, u, px, base - 3.4, 3.6, 3.4, ROOM.fabricDeep)
  r(ctx, u, px, base - 3.4, 3.6, 0.5, ROOM.fabric)
  r(ctx, u, px - 0.4, base - 4, 4.4, 0.8, ROOM.fabricLit)
  r(ctx, u, px + 0.4, base - 4, 2.8, 0.5, ROOM.soil)
  for (let i = 0; i < 5; i++) {
    const sway = Math.sin(s.time * 0.7 + i * 1.4) * 0.5
    const lean = (i - 2) * 0.55
    for (let seg = 0; seg < 4 + (i % 2) * 2; seg += 1.1) {
      const t = seg / 6
      r(
        ctx, u,
        px + 1.5 + lean * t * 1.8 + sway * t * t,
        base - 4.4 - seg,
        0.85, 1.05,
        t > 0.55 ? ROOM.leafLit : ROOM.leaf,
      )
    }
  }

  // The mug is a movable prop now — see props.ts.
}

/** Curtains hung either side, breathing very slightly. */
function drawCurtains(ctx: Ctx, u: number, s: RoomState) {
  const { x, y, w, h } = WINDOW
  const top = y - 5
  const bottom = y + h + 8

  // Rod and finials.
  r(ctx, u, x - 7, top, w + 14, 0.9, ROOM.metalDark)
  r(ctx, u, x - 7, top, w + 14, 0.3, ROOM.metalLit)
  r(ctx, u, x - 8.2, top - 0.7, 1.6, 2.3, ROOM.brass)
  r(ctx, u, x + w + 6.6, top - 0.7, 1.6, 2.3, ROOM.brass)

  const panel = (originX: number, dir: 1 | -1) => {
    const folds = 5
    const width = 8.5
    for (let i = 0; i < folds; i++) {
      const t = i / (folds - 1)
      // Each fold sways a touch out of phase with its neighbours.
      const sway = Math.sin(s.time * 0.42 + i * 0.8 + originX) * 0.32 * t
      const fw = width / folds
      const fx = originX + dir * (i * fw) + sway
      // Alternating tones are what make cloth read as gathered rather than flat.
      const tone = i % 2 === 0 ? ROOM.fabricDeep : mixHex(ROOM.fabricDeep, '#000000', 0.3)
      ctx.fillStyle = tone
      ctx.beginPath()
      ctx.moveTo(fx * u, top * u)
      ctx.lineTo((fx + dir * fw * 1.02) * u, top * u)
      ctx.lineTo((fx + dir * fw * 1.02 + sway * 2.4) * u, bottom * u)
      ctx.lineTo((fx + sway * 2.4) * u, bottom * u)
      ctx.closePath()
      ctx.fill()
      // Highlight down the crest of each fold.
      if (i % 2 === 0) {
        ctx.fillStyle = mixHex(tone, ROOM.fabricLit, 0.4)
        ctx.fillRect(fx * u, top * u, 0.45 * u, (bottom - top) * u)
      }
    }
    textureRect(
      ctx, 'weave', u,
      dir === 1 ? originX : originX - width,
      top, width, bottom - top, 0.4,
    )
  }
  panel(x - 8.5, 1)
  panel(x + w + 8.5, -1)
}

/** Cast-iron radiator under the window. */
function drawRadiator(ctx: Ctx, u: number) {
  const x = WINDOW.x + 4
  const y = 56
  const w = 26
  const h = FLOOR_Y - y - 1.5

  contactShadow(ctx, u, x + w / 2, FLOOR_Y + 0.6, w * 0.6, 1.6, 0.5)
  // Fins: the whole read of a radiator is the vertical rhythm.
  for (let i = 0; i < 13; i++) {
    const fx = x + i * 2
    r(ctx, u, fx, y, 1.5, h, ROOM.metal)
    r(ctx, u, fx, y, 0.4, h, ROOM.metalLit)
    r(ctx, u, fx + 1.2, y, 0.3, h, ROOM.metalDark)
  }
  // Top and bottom manifolds tie the fins together.
  slab(ctx, u, x - 0.6, y - 1.2, w + 1.2, 1.6, ROOM.metal, ROOM.metalLit, ROOM.metalDark, 0.4)
  slab(ctx, u, x - 0.6, y + h - 1, w + 1.2, 1.6, ROOM.metal, ROOM.metalLit, ROOM.metalDark, 0.4)
  textureRect(ctx, 'metal', u, x - 0.6, y - 1.2, w + 1.2, h + 2, 0.35)
  // Valve.
  r(ctx, u, x - 1.6, y + h - 4, 1.6, 1.4, ROOM.brass)
  r(ctx, u, x - 2.2, y + h - 4.4, 1, 2.2, ROOM.brassLit)
}

// ── wall ──────────────────────────────────────────────────────────────

function drawWallSurface(ctx: Ctx, u: number) {
  // Base gradient: light pools near the ceiling and falls away to the floor.
  const wall = ctx.createLinearGradient(0, 0, 0, FLOOR_Y * u)
  wall.addColorStop(0, ROOM.wallLit)
  wall.addColorStop(0.55, ROOM.wall)
  wall.addColorStop(1, mixHex(ROOM.wall, '#000000', 0.12))
  ctx.fillStyle = wall
  ctx.fillRect(ROOM_LEFT * u, -10 * u, ROOM_W * u, (FLOOR_Y + 10) * u)

  textureRect(ctx, 'plaster', u, ROOM_LEFT, -10, ROOM_W, FLOOR_Y + 10, 0.5)

  // Wallpaper: a wide, very low-contrast stripe. It should be something you
  // only find by looking for it — at any strength where you can name it as a
  // stripe, it stops being a wall and becomes a pattern.
  ctx.save()
  ctx.globalAlpha = 0.016
  for (let x = ROOM_LEFT; x < ROOM_LEFT + ROOM_W; x += 13) {
    r(ctx, u, x, -10, 6.5, FLOOR_Y + 10, '#FFE8D0')
    r(ctx, u, x + 6.5, -10, 0.6, FLOOR_Y + 10, '#000000')
  }
  ctx.restore()

  // Crown moulding.
  slab(ctx, u, ROOM_LEFT, 1.5, ROOM_W, 2.4, ROOM.wallWarm, mixHex(ROOM.wallWarm, '#FFFFFF', 0.3), ROOM.wallShade, 0.5)
  slab(ctx, u, ROOM_LEFT, 4.4, ROOM_W, 0.8, ROOM.wallShade, ROOM.wallWarm, '#00000066', 0.25)

  drawWainscot(ctx, u)

  // Age: soft stains where damp and hands have got at it.
  ctx.save()
  for (let i = 0; i < (quality().stains ? 9 : 0); i++) {
    const sx = ROOM_LEFT + hash2(i, 41, 13) * ROOM_W
    const sy = 8 + hash2(i, 42, 13) * (FLOOR_Y - 16)
    const rad = 5 + hash2(i, 43, 13) * 12
    ctx.globalAlpha = 0.05 + hash2(i, 44, 13) * 0.05
    const g = ctx.createRadialGradient(sx * u, sy * u, 0, sx * u, sy * u, rad * u)
    g.addColorStop(0, i % 2 ? '#000000' : ROOM.wallWarm)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fillRect((sx - rad) * u, (sy - rad) * u, rad * 2 * u, rad * 2 * u)
  }
  ctx.restore()

  // Ambient occlusion where wall meets ceiling and where it meets the floor.
  ctx.save()
  const ceiling = ctx.createLinearGradient(0, 0, 0, 9 * u)
  ceiling.addColorStop(0, 'rgba(0,0,0,0.55)')
  ceiling.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = ceiling
  ctx.fillRect(ROOM_LEFT * u, 0, ROOM_W * u, 9 * u)
  ctx.restore()

}

/**
 * Panelled dado below the picture rail.
 *
 * The lower half of a wall is the largest unbroken area in the frame and the
 * hardest to make interesting — left plain it reads as a void behind the
 * furniture. Panelling gives it architecture: a repeating rhythm of stiles and
 * recessed fields, each catching light on its top-left bevel and dropping a
 * shadow on its bottom-right, so the wall has depth before anything is put
 * against it.
 */
function drawWainscot(ctx: Ctx, u: number) {
  const railY = 46
  const top = railY + 1.4
  const bottom = FLOOR_Y - 3.4
  const height = bottom - top

  // Painted timber, a shade warmer and lighter than the plaster above it.
  const field = mixHex(ROOM.wall, ROOM.wallWarm, 0.55)
  r(ctx, u, ROOM_LEFT, top, ROOM_W, height, field)
  textureRect(ctx, 'wood', u, ROOM_LEFT, top, ROOM_W, height, 0.3, true)

  const pitch = 17
  const stile = 3.4
  const inset = 1.6
  for (let x = ROOM_LEFT; x < ROOM_LEFT + ROOM_W; x += pitch) {
    const px = x + stile
    const pw = pitch - stile * 2
    const py = top + inset + 0.8
    const ph = height - (inset + 0.8) * 2
    if (pw <= 0 || ph <= 0) continue

    // Recessed field, darker than the frame around it.
    r(ctx, u, px, py, pw, ph, mixHex(field, '#000000', 0.3))
    // Bevel: lit on the top and left, shadowed on the bottom and right.
    r(ctx, u, px, py, pw, 0.5, mixHex(field, '#000000', 0.55))
    r(ctx, u, px, py, 0.5, ph, mixHex(field, '#000000', 0.5))
    r(ctx, u, px, py + ph - 0.5, pw, 0.5, mixHex(field, '#FFFFFF', 0.16))
    r(ctx, u, px + pw - 0.5, py, 0.5, ph, mixHex(field, '#FFFFFF', 0.12))
    // Inner shadow, so the panel reads as sunk rather than drawn on.
    ctx.save()
    ctx.globalAlpha = 0.3
    const sink = ctx.createLinearGradient(0, py * u, 0, (py + ph * 0.4) * u)
    sink.addColorStop(0, 'rgba(0,0,0,0.7)')
    sink.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = sink
    ctx.fillRect(px * u, py * u, pw * u, ph * 0.4 * u)
    ctx.restore()
  }

  // Dado rail: a proper moulding, not a stripe.
  slab(ctx, u, ROOM_LEFT, railY, ROOM_W, 1.5, ROOM.wallWarm, mixHex(ROOM.wallWarm, '#FFFFFF', 0.34), ROOM.wallShade, 0.35)
  r(ctx, u, ROOM_LEFT, railY + 1.5, ROOM_W, 0.5, mixHex(ROOM.wallWarm, '#FFFFFF', 0.18))
  r(ctx, u, ROOM_LEFT, railY + 2, ROOM_W, 0.4, ROOM.wallShade)
  // The shadow the rail throws down the panelling.
  ctx.save()
  ctx.globalAlpha = 0.4
  const railShadow = ctx.createLinearGradient(0, (railY + 2.4) * u, 0, (railY + 6) * u)
  railShadow.addColorStop(0, 'rgba(0,0,0,0.55)')
  railShadow.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = railShadow
  ctx.fillRect(ROOM_LEFT * u, (railY + 2.4) * u, ROOM_W * u, 3.6 * u)
  ctx.restore()
}

/** Skirting board with a moulded profile, plus the scuffs it has collected. */
function drawSkirting(ctx: Ctx, u: number) {
  const top = FLOOR_Y - 3.4
  r(ctx, u, ROOM_LEFT, top, ROOM_W, 3.4, ROOM.skirting)
  r(ctx, u, ROOM_LEFT, top, ROOM_W, 0.5, ROOM.skirtingLit)
  r(ctx, u, ROOM_LEFT, top + 0.8, ROOM_W, 0.35, mixHex(ROOM.skirting, '#000000', 0.6))
  r(ctx, u, ROOM_LEFT, top + 1.3, ROOM_W, 0.3, ROOM.skirtingLit)
  textureRect(ctx, 'wood', u, ROOM_LEFT, top, ROOM_W, 3.4, 0.4)

  // Scuffs, thickest where a room actually gets kicked.
  ctx.save()
  for (let i = 0; i < 26; i++) {
    const sx = ROOM_LEFT + hash2(i, 61, 17) * ROOM_W
    ctx.globalAlpha = 0.1 + hash2(i, 62, 17) * 0.16
    r(ctx, u, sx, top + 1.6 + hash2(i, 63, 17) * 1.4, 1 + hash2(i, 64, 17) * 3, 0.4, '#000000')
  }
  ctx.restore()

  // Contact shadow along the whole junction.
  ctx.save()
  const junction = ctx.createLinearGradient(0, (FLOOR_Y - 1.2) * u, 0, (FLOOR_Y + 3) * u)
  junction.addColorStop(0, 'rgba(0,0,0,0.5)')
  junction.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = junction
  ctx.fillRect(ROOM_LEFT * u, (FLOOR_Y - 1.2) * u, ROOM_W * u, 4.2 * u)
  ctx.restore()
}

/** Outlet, switch and the cable that actually reaches the desk. */
function drawFittings(ctx: Ctx, u: number) {
  // Socket near the desk.
  const ox = 92
  const oy = FLOOR_Y - 8
  r(ctx, u, ox, oy, 3, 3.6, mixHex(ROOM.paper, '#000000', 0.35))
  r(ctx, u, ox, oy, 3, 0.4, ROOM.paperShade)
  r(ctx, u, ox + 0.7, oy + 1, 0.6, 0.9, '#141010')
  r(ctx, u, ox + 1.8, oy + 1, 0.6, 0.9, '#141010')
  r(ctx, u, ox + 1.1, oy + 2.3, 0.9, 0.6, '#141010')

  // Light switch by the right edge.
  r(ctx, u, 150, 40, 3, 4, mixHex(ROOM.paper, '#000000', 0.35))
  r(ctx, u, 150.8, 41, 1.4, 2, ROOM.paperShade)

  // Cable from the socket, sagging to the desk. Two strands, because one
  // perfectly placed wire is the least convincing thing in any room.
  ctx.save()
  ctx.strokeStyle = '#15100E'
  ctx.lineWidth = 0.5 * u
  ctx.lineCap = 'round'
  for (const drop of [0, 0.9]) {
    ctx.beginPath()
    ctx.moveTo((ox + 1.5) * u, (oy + 3.6) * u)
    ctx.bezierCurveTo(
      (ox + 4) * u, (FLOOR_Y - 1 + drop) * u,
      (ox + 10) * u, (FLOOR_Y - 0.5 + drop) * u,
      (ox + 14) * u, (FLOOR_Y - 3) * u,
    )
    ctx.stroke()
  }
  ctx.restore()
}

/** Wall clock, with hands that actually tell the room's time. */
const CLOCK = { cx: 66, cy: 15, rad: 4.6 }

/** The dial. Never changes, so it bakes with the wall. */
function drawClockFace(ctx: Ctx, u: number) {
  const cx = 66
  const cy = 15
  const rad = 4.6

  ctx.save()
  ctx.globalAlpha = 0.4
  ctx.beginPath()
  ctx.ellipse((cx + 0.8) * u, (cy + 1) * u, rad * u, rad * u, 0, 0, Math.PI * 2)
  ctx.fillStyle = '#000000'
  ctx.fill()
  ctx.restore()

  ctx.beginPath()
  ctx.ellipse(cx * u, cy * u, rad * u, rad * u, 0, 0, Math.PI * 2)
  ctx.fillStyle = ROOM.woodShade
  ctx.fill()
  ctx.beginPath()
  ctx.ellipse(cx * u, cy * u, (rad - 0.8) * u, (rad - 0.8) * u, 0, 0, Math.PI * 2)
  ctx.fillStyle = mixHex(ROOM.paper, ROOM.wall, 0.52)
  ctx.fill()
  // Glass dome: a crescent of reflection down one side of the dial.
  ctx.save()
  ctx.globalAlpha = 0.09
  ctx.fillStyle = '#DFF0FF'
  ctx.beginPath()
  ctx.ellipse((cx - 1.1) * u, (cy - 1.1) * u, (rad - 1.6) * u, (rad - 1.6) * u, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // Hour ticks.
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2 - Math.PI / 2
    const rr = rad - 1.4
    r(
      ctx, u,
      cx + Math.cos(a) * rr - 0.2, cy + Math.sin(a) * rr - 0.2,
      0.45, 0.45,
      i % 3 === 0 ? '#241C16' : '#6A5A4C',
    )
  }

}

/** The hands, which are the only part of a clock that is worth redrawing. */
function drawClockHands(ctx: Ctx, u: number, s: RoomState) {
  const { cx, cy, rad } = CLOCK
  const hand = (angle: number, length: number, width: number, colour: string) => {
    ctx.save()
    ctx.translate(cx * u, cy * u)
    ctx.rotate(angle)
    ctx.fillStyle = colour
    ctx.fillRect(-width * u * 0.5, -length * u, width * u, length * u)
    ctx.restore()
  }
  const minutes = (s.hour % 1) * 60
  hand((s.hour / 12) * Math.PI * 2, rad - 2.2, 0.5, '#241C16')
  hand((minutes / 60) * Math.PI * 2, rad - 1.3, 0.35, '#241C16')
  r(ctx, u, cx - 0.3, cy - 0.3, 0.6, 0.6, ROOM.brass)
}

/** The framed poster: mat board, bevel and a sheen on the glass. */
function drawPoster(ctx: Ctx, u: number) {
  const x = 76
  const y = 12
  const w = 15
  const h = 21

  ctx.save()
  ctx.globalAlpha = 0.45
  ctx.fillStyle = '#000000'
  ctx.fillRect((x + 1) * u, (y + 1.4) * u, w * u, h * u)
  ctx.restore()

  // Frame, mat, then the print itself.
  slab(ctx, u, x - 1, y - 1, w + 2, h + 2, '#1A1512', '#3A2E26', '#0C0A08', 0.4)
  // The mat has to sit down in the room's value range: a bright white card on
  // a dim wall pulls the eye off the character and never gives it back.
  r(ctx, u, x, y, w, h, mixHex(ROOM.paper, ROOM.wall, 0.62))
  textureRect(ctx, 'paper', u, x, y, w, h, 0.4)
  const px = x + 2.2
  const py = y + 2.4
  const pw = w - 4.4
  const ph = h - 6
  r(ctx, u, px, py, pw, ph, '#3A3028')
  r(ctx, u, px, py, pw, 0.3, '#0F0C0A')

  // A tiny Clawd silhouette on the poster — a nod, not a duplicate.
  const gx = px + pw / 2
  const gy = py + ph * 0.42
  r(ctx, u, gx - 3, gy - 2.2, 6, 4.5, ROOM.screenGlow)
  r(ctx, u, gx - 4.2, gy - 0.7, 1.2, 1.2, ROOM.screenGlow)
  r(ctx, u, gx + 3, gy - 0.7, 1.2, 1.2, ROOM.screenGlow)
  r(ctx, u, gx - 1.6, gy - 0.8, 0.9, 0.9, '#1A1512')
  r(ctx, u, gx + 0.7, gy - 0.8, 0.9, 0.9, '#1A1512')
  for (const lx of [-2.2, -0.8, 0.6, 2]) r(ctx, u, gx + lx, gy + 2.3, 0.7, 1.6, ROOM.screenGlow)
  // Caption lines on the mat.
  r(ctx, u, px + 1, py + ph + 1.6, pw - 6, 0.5, '#6A5E52')
  r(ctx, u, px + 1, py + ph + 2.8, pw - 9, 0.4, '#4A4038')

  // Glass sheen: one hard diagonal, which is what says "there is glass here".
  ctx.save()
  ctx.globalAlpha = 0.035
  ctx.fillStyle = '#DFF0FF'
  ctx.beginPath()
  ctx.moveTo(x * u, (y + h) * u)
  ctx.lineTo((x + w * 0.55) * u, y * u)
  ctx.lineTo((x + w * 0.85) * u, y * u)
  ctx.lineTo((x + w * 0.3) * u, (y + h) * u)
  ctx.closePath()
  ctx.fill()
  ctx.restore()
}

/** Pinboard above the desk: notes, a photo, a stray postcard. */
function drawPinboard(ctx: Ctx, u: number) {
  const x = 98
  const y = 16
  const w = 26
  const h = 18

  ctx.save()
  ctx.globalAlpha = 0.4
  ctx.fillStyle = '#000000'
  ctx.fillRect((x + 0.8) * u, (y + 1.2) * u, w * u, h * u)
  ctx.restore()

  slab(ctx, u, x - 0.8, y - 0.8, w + 1.6, h + 1.6, ROOM.woodShade, ROOM.wood, ROOM.woodDeep, 0.4)
  r(ctx, u, x, y, w, h, ROOM.cork)
  textureRect(ctx, 'paper', u, x, y, w, h, 0.55)
  ctx.save()
  ctx.globalAlpha = 0.25
  r(ctx, u, x, y, w, 1.2, '#000000')
  ctx.restore()

  // Muted card, not fresh stationery: on a wall this dim, saturated notes are
  // the brightest thing in the frame and steal the eye from the character.
  const notes: [number, number, number, number, string, number][] = [
    [2, 2, 6, 5.5, '#A99B5E', -0.05],
    [10, 1.6, 5.5, 5, '#A2706F', 0.06],
    [17.5, 2.6, 6.5, 6, '#748C9E', -0.03],
    [3, 9.5, 7.5, 6.5, '#B3ADA0', 0.04],
    [13, 10, 5, 4.5, '#A99B5E', -0.07],
    [19.5, 10.5, 5, 5.5, '#93A07C', 0.05],
  ]
  for (const [nx, ny, nw, nh, tone, tilt] of notes) {
    ctx.save()
    ctx.translate((x + nx + nw / 2) * u, (y + ny + nh / 2) * u)
    ctx.rotate(tilt)
    ctx.globalAlpha = 0.4
    ctx.fillStyle = '#000000'
    ctx.fillRect((-nw / 2 + 0.3) * u, (-nh / 2 + 0.4) * u, nw * u, nh * u)
    ctx.globalAlpha = 1
    ctx.fillStyle = tone
    ctx.fillRect((-nw / 2) * u, (-nh / 2) * u, nw * u, nh * u)
    ctx.fillStyle = mixHex(tone, '#FFFFFF', 0.3)
    ctx.fillRect((-nw / 2) * u, (-nh / 2) * u, nw * u, 0.3 * u)
    // Scribbled lines standing in for handwriting.
    ctx.fillStyle = mixHex(tone, '#000000', 0.45)
    for (let l = 0; l < Math.floor(nh / 1.6); l++) {
      const lw = nw * (0.5 + hash2(nx + l, ny, 71) * 0.35)
      ctx.fillRect((-nw / 2 + 0.7) * u, (-nh / 2 + 1.2 + l * 1.5) * u, lw * u, 0.3 * u)
    }
    // Pin.
    ctx.fillStyle = l0Pin(nx)
    ctx.fillRect(-0.45 * u, (-nh / 2 + 0.3) * u, 0.9 * u, 0.9 * u)
    ctx.restore()
  }
}

/** Deterministic pin colour, so the board looks collected over time. */
function l0Pin(seed: number): string {
  const pins = ['#D4634A', '#4A7BA8', '#C8A83A', '#5FA05A']
  return pins[Math.floor(hash2(seed, 3, 91) * pins.length) % pins.length]
}

// ── floor ─────────────────────────────────────────────────────────────

/** Where a floorboard joint sits at depth `t` (0 at the wall, 1 at the front). */
function jointX(index: number, t: number): number {
  // Joints fan out toward the viewer. Narrow boards near the wall, wide near
  // the front, is the whole illusion of a floor receding.
  return STAGE.w / 2 + index * (7 + t * 13)
}

function drawFloor(ctx: Ctx, u: number) {
  const depth = STAGE.h - FLOOR_Y
  const floor = ctx.createLinearGradient(0, FLOOR_Y * u, 0, STAGE.h * u)
  floor.addColorStop(0, ROOM.floor)
  floor.addColorStop(0.45, ROOM.floorLit)
  floor.addColorStop(1, mixHex(ROOM.floorWarm, '#000000', 0.22))
  ctx.fillStyle = floor
  ctx.fillRect(ROOM_LEFT * u, FLOOR_Y * u, ROOM_W * u, depth * u)

  // Each board takes its own stain. Painting them individually — rather than
  // banding the whole floor by depth — is what stops it reading as tile.
  ctx.save()
  for (let i = -18; i <= 32; i++) {
    const shift = hash2(i, 7, 55) - 0.5
    ctx.globalAlpha = 0.16 + Math.abs(shift) * 0.2
    ctx.fillStyle = shift > 0 ? ROOM.floorWarm : '#140D08'
    ctx.beginPath()
    ctx.moveTo(jointX(i, 0) * u, FLOOR_Y * u)
    ctx.lineTo(jointX(i + 1, 0) * u, FLOOR_Y * u)
    ctx.lineTo(jointX(i + 1, 1) * u, STAGE.h * u)
    ctx.lineTo(jointX(i, 1) * u, STAGE.h * u)
    ctx.closePath()
    ctx.fill()
  }
  ctx.restore()

  // Grain, run along the boards rather than across them.
  textureRect(ctx, 'wood', u, ROOM_LEFT, FLOOR_Y, ROOM_W, depth, 0.55, true)

  // Board ends, staggered so no two rows break in the same place.
  const detail = quality().floorDetail
  ctx.save()
  ctx.globalAlpha = 0.35
  ctx.fillStyle = ROOM.floorSeam
  for (let i = detail ? -18 : 33; i <= 32; i++) {
    for (let k = 0; k < 3; k++) {
      const t = 0.18 + k * 0.3 + hash2(i, k, 63) * 0.16
      const y = FLOOR_Y + t * depth
      ctx.fillRect(jointX(i, t) * u, y * u, (jointX(i + 1, t) - jointX(i, t)) * u, 0.28 * u)
    }
  }
  ctx.restore()

  // The joints themselves: a dark line with a lit bevel on one side.
  ctx.save()
  for (let i = -18; i <= 32; i++) {
    ctx.globalAlpha = 0.34
    ctx.strokeStyle = ROOM.floorSeam
    ctx.lineWidth = Math.max(1, 0.2 * u)
    ctx.beginPath()
    ctx.moveTo(jointX(i, 0) * u, FLOOR_Y * u)
    ctx.lineTo(jointX(i, 1) * u, STAGE.h * u)
    ctx.stroke()
    ctx.globalAlpha = 0.08
    ctx.strokeStyle = '#FFE4C0'
    ctx.lineWidth = Math.max(1, 0.13 * u)
    ctx.beginPath()
    ctx.moveTo((jointX(i, 0) + 0.22) * u, FLOOR_Y * u)
    ctx.lineTo((jointX(i, 1) + 0.5) * u, STAGE.h * u)
    ctx.stroke()
  }
  ctx.restore()

  // Nail heads, two to a board end.
  ctx.save()
  ctx.globalAlpha = 0.26
  ctx.fillStyle = '#0B0806'
  for (let i = detail ? -18 : 33; i <= 32; i += 1) {
    for (let k = 0; k < 3; k++) {
      const t = 0.18 + k * 0.3 + hash2(i, k, 63) * 0.16
      const y = FLOOR_Y + t * depth
      const w = jointX(i + 1, t) - jointX(i, t)
      ctx.fillRect((jointX(i, t) + w * 0.22) * u, (y - 0.5) * u, 0.3 * u, 0.3 * u)
      ctx.fillRect((jointX(i, t) + w * 0.74) * u, (y - 0.5) * u, 0.3 * u, 0.3 * u)
    }
  }
  ctx.restore()

  // Wear: the traffic path between the door and the desk has lost its finish.
  ctx.save()
  ctx.globalAlpha = 0.1
  const wear = ctx.createRadialGradient(
    92 * u, (FLOOR_Y + depth * 0.55) * u, 0,
    92 * u, (FLOOR_Y + depth * 0.55) * u, 46 * u,
  )
  wear.addColorStop(0, ROOM.floorWarm)
  wear.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = wear
  ctx.fillRect(ROOM_LEFT * u, FLOOR_Y * u, ROOM_W * u, depth * u)
  ctx.restore()

}

/**
 * Varnish catching the light. Lives outside the bake because it is the one
 * part of the floor that changes as the hour turns and the lamp comes on.
 */
function drawFloorSheen(ctx: Ctx, u: number, s: RoomState) {
  const depth = STAGE.h - FLOOR_Y
  const day = daylightAt(s.hour)
  if (day <= 0.05 && s.lamp <= 0.02) return
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  if (day > 0.05) {
    ctx.globalAlpha = 0.06 * day
    const sheen = ctx.createLinearGradient(0, FLOOR_Y * u, 0, STAGE.h * u)
    sheen.addColorStop(0, skyAt(s.hour).light)
    sheen.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = sheen
    ctx.fillRect(ROOM_LEFT * u, FLOOR_Y * u, ROOM_W * u, depth * u)
  }
  if (s.lamp > 0.02) {
    ctx.globalAlpha = 0.09 * s.lamp
    const pool = ctx.createLinearGradient(0, FLOOR_Y * u, 0, (FLOOR_Y + depth * 0.8) * u)
    pool.addColorStop(0, ROOM.lamp)
    pool.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = pool
    ctx.fillRect((DESK.x + 4) * u, FLOOR_Y * u, 26 * u, depth * 0.8 * u)
  }
  ctx.restore()
}

/** Volumetric shaft cast from the window onto the floor. */
function drawLightShaft(ctx: Ctx, u: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const daylight = daylightAt(s.hour)
  if (daylight < 0.04) return

  const { x, y, w } = WINDOW
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 0.15 * daylight

  const shaft = ctx.createLinearGradient(x * u, y * u, (x + w + 34) * u, FLOOR_Y * u)
  shaft.addColorStop(0, sky.light)
  shaft.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = shaft

  // Skewed quad from the window opening down to the floor.
  ctx.beginPath()
  ctx.moveTo(x * u, y * u)
  ctx.lineTo((x + w) * u, y * u)
  ctx.lineTo((x + w + 40) * u, FLOOR_Y * u)
  ctx.lineTo((x + 16) * u, FLOOR_Y * u)
  ctx.closePath()
  ctx.fill()

  // The mullion's shadow crossing the beam, so the light has structure.
  ctx.globalAlpha = 0.06 * daylight
  ctx.fillStyle = '#000000'
  ctx.beginPath()
  ctx.moveTo((x + w / 2 - 0.7) * u, y * u)
  ctx.lineTo((x + w / 2 + 0.7) * u, y * u)
  ctx.lineTo((x + w / 2 + 20) * u, FLOOR_Y * u)
  ctx.lineTo((x + w / 2 + 18) * u, FLOOR_Y * u)
  ctx.closePath()
  ctx.fill()

  // The bright patch where it lands, and its warm bounce back up the wall.
  ctx.globalAlpha = 0.12 * daylight
  ctx.fillStyle = shaft
  ctx.beginPath()
  ctx.ellipse((x + w / 2 + 26) * u, (FLOOR_Y + 3) * u, 28 * u, 5.5 * u, 0, 0, Math.PI * 2)
  ctx.fill()

  // Motes drifting through the beam.
  ctx.fillStyle = ROOM.dust
  for (let i = 0; i < quality().motes; i++) {
    const seed = i * 12.9898
    const drift = (s.time * (0.1 + (i % 5) * 0.03) + hash2(i, 1, 2)) % 1
    const px = x + 3 + hash2(i, 2, 2) * (w + 32) + drift * 9
    const py = y + drift * (FLOOR_Y - y)
    const bob = Math.sin(s.time * 0.8 + seed) * 0.7
    ctx.globalAlpha = 0.5 * daylight * (1 - drift) * (0.35 + (i % 3) * 0.3)
    ctx.fillRect((px + bob) * u, py * u, 0.34 * u, 0.34 * u)
  }
  ctx.restore()
}

// ── furniture ─────────────────────────────────────────────────────────

/**
 * Deliberately low. Clawd is about 12 stage units tall, so a desk at the usual
 * height would hide him completely — at y 60 his head and eyes clear the top
 * while the desk still occludes his legs, which is what sells him standing
 * behind it.
 */
const DESK = { x: 96, y: 60, w: 30, h: 8 }

/** The desk carcass and its clutter — furniture, so it bakes. */
function drawDeskBody(ctx: Ctx, u: number) {
  const { x, y, w } = DESK

  contactShadow(ctx, u, x + w / 2, FLOOR_Y + 1, w * 0.65, 2.4, 0.55)

  // Legs first so the top overlaps them.
  for (const lx of [x + 1.5, x + w - 3.1]) {
    r(ctx, u, lx, y + 2, 1.6, FLOOR_Y - y - 2, ROOM.woodShade)
    r(ctx, u, lx, y + 2, 0.4, FLOOR_Y - y - 2, ROOM.wood)
    r(ctx, u, lx + 1.3, y + 2, 0.3, FLOOR_Y - y - 2, ROOM.woodDeep)
  }
  // Stretcher between them.
  r(ctx, u, x + 2.3, FLOOR_Y - 3, w - 5.4, 0.8, ROOM.woodShade)

  // A shallow drawer under the top.
  slab(ctx, u, x + 4, y + 2.6, 13, 3.2, ROOM.walnut, ROOM.walnutLit, ROOM.woodDeep, 0.4)
  textureRect(ctx, 'wood', u, x + 4, y + 2.6, 13, 3.2, 0.45)
  r(ctx, u, x + 9, y + 4, 3.2, 0.7, ROOM.brass)
  r(ctx, u, x + 9, y + 4, 3.2, 0.25, ROOM.brassLit)

  // Top: body, grain, a lit front edge and the shadow it casts on the drawer.
  r(ctx, u, x, y, w, 2.4, ROOM.wood)
  textureRect(ctx, 'wood', u, x, y, w, 2.4, 0.55)
  r(ctx, u, x, y, w, 0.5, ROOM.woodLit)
  r(ctx, u, x, y + 1.9, w, 0.5, ROOM.woodShade)
  r(ctx, u, x - 0.6, y + 0.3, 0.6, 2, ROOM.woodShade)
  r(ctx, u, x + w, y + 0.3, 0.6, 2, ROOM.woodShade)
  ctx.save()
  ctx.globalAlpha = 0.5
  const underTop = ctx.createLinearGradient(0, (y + 2.4) * u, 0, (y + 5) * u)
  underTop.addColorStop(0, 'rgba(0,0,0,0.7)')
  underTop.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = underTop
  ctx.fillRect(x * u, (y + 2.4) * u, w * u, 2.6 * u)
  ctx.restore()

  drawDeskClutter(ctx, u)
}

/** The parts of the desk that are lit or animated: the screen, mostly. */
function drawDeskSurface(ctx: Ctx, u: number, s: RoomState) {
  drawMonitor(ctx, u, s)
}

function drawMonitor(ctx: Ctx, u: number, s: RoomState) {
  const { x, y } = DESK
  // Left of centre on the desk, which leaves the right third clear for the
  // lamp to reach over without its arm cutting across the panel.
  const mx = x + 4
  const my = y - 17

  // Stand and foot.
  r(ctx, u, mx + 6.5, my + 13.5, 3, 3, ROOM.metalDark)
  r(ctx, u, mx + 6.5, my + 13.5, 0.6, 3, ROOM.metal)
  r(ctx, u, mx + 2.5, my + 16.2, 11, 1.1, ROOM.metalDark)
  r(ctx, u, mx + 2.5, my + 16.2, 11, 0.35, ROOM.metal)

  // Bezel with a thin lit top edge.
  slab(ctx, u, mx - 1.1, my - 1.1, 18.2, 15.6, ROOM.metalDark, ROOM.metal, '#0A0908', 0.4)
  textureRect(ctx, 'metal', u, mx - 1.1, my - 1.1, 18.2, 15.6, 0.3)
  r(ctx, u, mx, my, 16, 13.4, ROOM.screen)

  // Screen content: code lines with a syntax rhythm, scrolling slowly.
  ctx.save()
  ctx.beginPath()
  ctx.rect(mx * u, my * u, 16 * u, 13.4 * u)
  ctx.clip()
  const scroll = (s.time * 5) % 1.7
  for (let i = -1; i < 10; i++) {
    const ly = my + 1 + i * 1.7 - scroll
    const indent = (i * 7) % 3
    const lw = 3 + ((i * 37) % 9)
    ctx.globalAlpha = 0.3 + s.screen * 0.6
    const tone =
      i % 5 === 0 ? ROOM.screenGlow : i % 3 === 0 ? ROOM.screenKey : i % 4 === 0 ? ROOM.screenString : ROOM.screenCode
    r(ctx, u, mx + 1 + indent, ly, lw, 0.55, tone)
    if (i % 2 === 0) r(ctx, u, mx + 2 + indent + lw, ly, 2 + ((i * 13) % 4), 0.55, ROOM.screenCode)
  }
  // Cursor block.
  ctx.globalAlpha = (0.4 + s.screen * 0.6) * (Math.sin(s.time * 3.2) > 0 ? 1 : 0.15)
  r(ctx, u, mx + 6, my + 6.2, 0.7, 1, ROOM.paper)
  // Scanline sheen over the whole panel.
  ctx.globalAlpha = 0.05
  for (let ly = my; ly < my + 13.4; ly += 0.7) r(ctx, u, mx, ly, 16, 0.3, '#000000')
  ctx.restore()
  ctx.globalAlpha = 1

  // Reflection of the screen on the desk top directly below it.
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 0.1 + s.screen * 0.14
  const refl = ctx.createLinearGradient(0, y * u, 0, (y + 2.4) * u)
  refl.addColorStop(0, ROOM.screenGlow)
  refl.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = refl
  ctx.fillRect((mx - 1) * u, y * u, 18 * u, 2.4 * u)
  ctx.restore()

  // Monitor bloom into the room.
  glow(ctx, u, mx + 8, my + 6.7, 30, ROOM.screenGlow, 0.1 + s.screen * 0.1)
}

/** Everything that accumulates on a desk that is actually used. */
function drawDeskClutter(ctx: Ctx, u: number) {
  const { x, y } = DESK

  // Mousemat, keyboard, mouse.
  r(ctx, u, x + 3, y - 1.4, 15, 1.5, mixHex(ROOM.metalDark, '#000000', 0.3))
  slab(ctx, u, x + 3.5, y - 2.2, 13, 1.5, ROOM.metal, ROOM.metalLit, ROOM.metalDark, 0.35)
  // Key rows, so it reads as a keyboard rather than a bar.
  ctx.save()
  ctx.globalAlpha = 0.5
  for (let k = 0; k < 22; k++) r(ctx, u, x + 3.9 + k * 0.58, y - 1.9, 0.34, 0.5, '#15120F')
  for (let k = 0; k < 20; k++) r(ctx, u, x + 4.1 + k * 0.58, y - 1.2, 0.34, 0.4, '#15120F')
  ctx.restore()
  r(ctx, u, x + 18.4, y - 1.9, 1.8, 1.2, ROOM.metal)
  r(ctx, u, x + 18.4, y - 1.9, 1.8, 0.35, ROOM.metalLit)

  // A short stack of paper with a pen across it.
  r(ctx, u, x + 0.5, y - 0.8, 6.5, 0.8, ROOM.paperShade)
  r(ctx, u, x + 0.8, y - 1.3, 6.5, 0.8, ROOM.paper)
  textureRect(ctx, 'paper', u, x + 0.8, y - 1.3, 6.5, 0.8, 0.5)
  ctx.save()
  ctx.translate((x + 4) * u, (y - 1.6) * u)
  ctx.rotate(-0.22)
  r(ctx, u, -2.6, 0, 5.2, 0.4, '#2A3F52')
  r(ctx, u, 1.8, 0, 0.8, 0.4, ROOM.brass)
  ctx.restore()

  // Pen cup at the far end.
  const cupX = x + 27.5
  r(ctx, u, cupX, y - 3.2, 2.4, 3.2, ROOM.metalDark)
  r(ctx, u, cupX, y - 3.2, 0.5, 3.2, ROOM.metal)
  for (let i = 0; i < 3; i++) {
    const tilt = (i - 1) * 0.35
    r(ctx, u, cupX + 0.5 + i * 0.6 + tilt * 0.4, y - 5.4 - i * 0.3, 0.4, 2.4, ['#C8A83A', '#D4634A', '#4A7BA8'][i])
  }
}

/** Anglepoise lamp: arm, shade, bulb, and the pool it throws. */
function drawLamp(ctx: Ctx, u: number, s: RoomState) {
  const baseX = DESK.x + 25.5
  const baseY = DESK.y

  // Base and column.
  r(ctx, u, baseX - 1, baseY - 0.9, 5, 1, ROOM.metalDark)
  r(ctx, u, baseX - 1, baseY - 0.9, 5, 0.3, ROOM.metal)

  // Two-segment arm, drawn as strokes so the joints read. It reaches up and
  // back over the desk, stopping short of the monitor: an arm crossing the
  // panel reads as a plank lying on the screen.
  const elbow = { x: baseX + 3, y: baseY - 11 }
  const head = { x: baseX - 2.5, y: baseY - 13.5 }
  ctx.save()
  ctx.strokeStyle = ROOM.metalDark
  ctx.lineWidth = 0.8 * u
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo((baseX + 1.5) * u, (baseY - 1) * u)
  ctx.lineTo(elbow.x * u, elbow.y * u)
  ctx.lineTo(head.x * u, head.y * u)
  ctx.stroke()
  ctx.strokeStyle = ROOM.metal
  ctx.lineWidth = 0.3 * u
  ctx.beginPath()
  ctx.moveTo((baseX + 1.3) * u, (baseY - 1) * u)
  ctx.lineTo((elbow.x - 0.2) * u, elbow.y * u)
  ctx.stroke()
  ctx.restore()
  r(ctx, u, elbow.x - 0.7, elbow.y - 0.7, 1.4, 1.4, ROOM.metal)

  // Conical shade, angled down at the desk. Enamelled metal, not timber —
  // the tone has to stay clearly cooler than the wood around it.
  ctx.save()
  ctx.translate(head.x * u, head.y * u)
  ctx.rotate(0.42)
  ctx.fillStyle = s.lamp > 0.5 ? mixHex(ROOM.metal, ROOM.lampDeep, 0.3) : ROOM.metal
  ctx.beginPath()
  ctx.moveTo(-1.8 * u, 0)
  ctx.lineTo(1.8 * u, 0)
  ctx.lineTo(2.9 * u, 3 * u)
  ctx.lineTo(-2.9 * u, 3 * u)
  ctx.closePath()
  ctx.fill()
  ctx.fillStyle = ROOM.metalDark
  ctx.fillRect(-2.9 * u, 2.6 * u, 5.8 * u, 0.45 * u)
  ctx.fillStyle = mixHex(ROOM.metalLit, '#FFFFFF', 0.25)
  ctx.fillRect(-1.8 * u, 0, 3.6 * u, 0.35 * u)
  if (s.lamp > 0.02) {
    ctx.globalAlpha = s.lamp
    ctx.fillStyle = ROOM.lamp
    ctx.fillRect(-2.4 * u, 2.55 * u, 4.8 * u, 0.6 * u)
  }
  ctx.restore()

  if (s.lamp > 0.02) {
    // Cone of light down onto the desk.
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.globalAlpha = 0.17 * s.lamp
    const g = ctx.createLinearGradient(0, head.y * u, 0, (DESK.y + 3) * u)
    g.addColorStop(0, ROOM.lamp)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.moveTo((head.x - 2.9) * u, (head.y + 3) * u)
    ctx.lineTo((head.x + 2.9) * u, (head.y + 3) * u)
    ctx.lineTo((head.x + 12) * u, DESK.y * u)
    ctx.lineTo((head.x - 10) * u, DESK.y * u)
    ctx.closePath()
    ctx.fill()
    ctx.restore()

    glow(ctx, u, head.x, head.y + 2.8, 14, ROOM.lamp, 0.3 * s.lamp)

    // Dust turning over in the lamplight. The daylight shaft has this and the
    // lamp did not, so after dark the room's air went completely still.
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.fillStyle = ROOM.dust
    for (let i = 0; i < Math.round(quality().motes * 0.48); i++) {
      const rise = (s.time * (0.05 + (i % 4) * 0.02) + hash2(i, 11, 4)) % 1
      const spread = 3 + rise * 9
      const mx = head.x + (hash2(i, 12, 4) - 0.5) * spread * 2
      const my = DESK.y - rise * 12
      ctx.globalAlpha = 0.42 * s.lamp * rise * (1 - rise) * 3
      ctx.fillRect(
        (mx + Math.sin(s.time * 0.6 + i) * 0.5) * u,
        my * u,
        0.3 * u, 0.3 * u,
      )
    }
    ctx.restore()
    // Warm pool on the desk top.
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.globalAlpha = 0.16 * s.lamp
    const pool = ctx.createRadialGradient(
      (head.x + 1) * u, (DESK.y + 1) * u, 0,
      (head.x + 1) * u, (DESK.y + 1) * u, 15 * u,
    )
    pool.addColorStop(0, ROOM.lamp)
    pool.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = pool
    ctx.fillRect((head.x - 15) * u, DESK.y * u, 32 * u, 3 * u)
    ctx.restore()
  }
}

function drawShelf(ctx: Ctx, u: number) {
  const x = 130
  const y = 28
  const w = 26
  const gap = 13

  for (const sy of [y, y + gap]) {
    ctx.save()
    ctx.globalAlpha = 0.45
    ctx.fillStyle = '#000000'
    ctx.fillRect(x * u, (sy + 1.4) * u, w * u, 2.2 * u)
    ctx.restore()
    slab(ctx, u, x, sy, w, 1.4, ROOM.wood, ROOM.woodLit, ROOM.woodShade, 0.4)
    textureRect(ctx, 'wood', u, x, sy, w, 1.4, 0.5)
    // Bracket under each end.
    for (const bx of [x + 1, x + w - 3]) {
      ctx.fillStyle = ROOM.metalDark
      ctx.beginPath()
      ctx.moveTo(bx * u, (sy + 1.4) * u)
      ctx.lineTo((bx + 2) * u, (sy + 1.4) * u)
      ctx.lineTo(bx * u, (sy + 4.4) * u)
      ctx.closePath()
      ctx.fill()
    }
  }

  // Upper shelf: books, some upright, one leaning into the gap.
  let bx = x + 1.5
  for (let i = 0; i < 9; i++) {
    const bw = 1.2 + hash2(i, 1, 33) * 1.1
    const bh = 7 + hash2(i, 2, 33) * 3.4
    const tone = SPINES[i % SPINES.length]
    const lean = i === 6 ? 0.22 : 0
    ctx.save()
    ctx.translate(bx * u, y * u)
    ctx.rotate(lean)
    ctx.fillStyle = tone
    ctx.fillRect(0, -bh * u, bw * u, bh * u)
    ctx.fillStyle = mixHex(tone, '#FFFFFF', 0.22)
    ctx.fillRect(0, -bh * u, bw * u, 0.4 * u)
    ctx.fillStyle = mixHex(tone, '#000000', 0.4)
    ctx.fillRect((bw - 0.3) * u, -bh * u, 0.3 * u, bh * u)
    // Title bands on the spine.
    ctx.fillStyle = mixHex(tone, '#FFFFFF', 0.45)
    ctx.fillRect(0.3 * u, (-bh + 1.4) * u, (bw - 0.8) * u, 0.3 * u)
    ctx.fillRect(0.3 * u, (-bh + 2.2) * u, (bw - 1.2) * u, 0.25 * u)
    ctx.restore()
    bx += bw + (lean ? 0.9 : 0.25)
  }
  // A ceramic thing at the end of the row.
  r(ctx, u, x + 21, y - 4.5, 3.4, 4.5, mixHex(ROOM.fabric, '#000000', 0.15))
  r(ctx, u, x + 21, y - 4.5, 3.4, 0.5, ROOM.fabricLit)
  r(ctx, u, x + 20.6, y - 5.2, 4.2, 0.8, ROOM.fabricLit)

  // Lower shelf: a flat stack, a framed photo, a small plant.
  const ly = y + gap
  for (let i = 0; i < 4; i++) {
    const sw = 8 - i * 0.6
    r(ctx, u, x + 2 + i * 0.3, ly - 1.1 - i * 1.1, sw, 1.1, SPINES[(i + 3) % SPINES.length])
    r(ctx, u, x + 2 + i * 0.3, ly - 1.1 - i * 1.1, sw, 0.3, mixHex(SPINES[(i + 3) % SPINES.length], '#FFFFFF', 0.25))
  }
  // Framed photo, leaning back against the wall.
  slab(ctx, u, x + 12, ly - 6.5, 5.5, 6.5, ROOM.woodShade, ROOM.wood, ROOM.woodDeep, 0.35)
  r(ctx, u, x + 12.8, ly - 5.7, 3.9, 4.9, mixHex(ROOM.glass, ROOM.wall, 0.45))
  r(ctx, u, x + 13.2, ly - 3.4, 3.1, 2.2, mixHex(ROOM.leaf, '#000000', 0.2))
  r(ctx, u, x + 14.2, ly - 4.6, 1.2, 1.3, ROOM.fabricLit)
  // Small plant.
  r(ctx, u, x + 20, ly - 3, 3.6, 3, ROOM.fabric)
  r(ctx, u, x + 19.7, ly - 3.5, 4.2, 0.7, ROOM.fabricLit)
  for (let i = 0; i < 4; i++) {
    r(ctx, u, x + 20.6 + i * 0.7, ly - 6.4 + (i % 2) * 0.8, 0.9, 3.2, i % 2 ? ROOM.leafLit : ROOM.leaf)
  }
}

function drawRug(ctx: Ctx, u: number) {
  const x = 60
  const y = FLOOR_Y + 0.5
  const w = 38
  const h = 5

  ctx.save()
  // Slight trapezoid: the far edge is shorter, so it lies on the floor.
  ctx.fillStyle = ROOM.fabricDeep
  ctx.beginPath()
  ctx.moveTo((x + 2) * u, y * u)
  ctx.lineTo((x + w - 2) * u, y * u)
  ctx.lineTo((x + w) * u, (y + h) * u)
  ctx.lineTo(x * u, (y + h) * u)
  ctx.closePath()
  ctx.fill()
  ctx.clip()

  textureRect(ctx, 'weave', u, x - 1, y, w + 2, h, 0.5)

  // A kilim: twin border bands and a run of diamonds down the field. A rug
  // with a pattern reads as chosen; a plain block reads as a shadow.
  r(ctx, u, x + 1.4, y + 0.5, w - 2.8, 0.4, mixHex(ROOM.rugSand, ROOM.fabricDeep, 0.3))
  r(ctx, u, x + 1.4, y + 1.2, w - 2.8, 0.25, ROOM.rugInk)
  r(ctx, u, x + 0.6, y + h - 1.5, w - 1.2, 0.4, mixHex(ROOM.rugSand, ROOM.fabricDeep, 0.3))
  r(ctx, u, x + 0.6, y + h - 0.9, w - 1.2, 0.25, ROOM.rugInk)

  for (let i = 0; i < 12; i++) {
    const cx = x + 3.4 + i * 3
    const cy = y + h * 0.5
    const size = 1.5
    // Stepped diamond, the way a loom would actually make one.
    const tone = i % 2 === 0 ? ROOM.rugInk : mixHex(ROOM.rugSand, '#000000', 0.2)
    for (let k = 0; k < 3; k++) {
      const half = size - k * 0.5
      r(ctx, u, cx - half, cy - 0.35 + k * 0.35, half * 2, 0.35, tone)
      r(ctx, u, cx - half, cy - 0.35 - k * 0.35, half * 2, 0.35, tone)
    }
    if (i % 2 === 0) r(ctx, u, cx - 0.3, cy - 0.3, 0.6, 0.6, ROOM.rugSand)
  }
  ctx.restore()

  // Fringe along the near edge, sitting in shadow rather than catching light —
  // it should read as a frayed edge, not as a row of teeth.
  const fringe = mixHex(ROOM.rugSand, '#000000', 0.45)
  for (let i = 0; i < 38; i++) {
    ctx.save()
    ctx.globalAlpha = 0.35 + hash2(i, 5, 77) * 0.3
    r(ctx, u, x + i, y + h, 0.45, 0.5 + hash2(i, 6, 77) * 0.45, fringe)
    ctx.restore()
  }

  // The rug lifts very slightly at the near edge, so it gets a shadow too.
  ctx.save()
  ctx.globalAlpha = 0.3
  const lift = ctx.createLinearGradient(0, (y + h) * u, 0, (y + h + 2) * u)
  lift.addColorStop(0, 'rgba(0,0,0,0.5)')
  lift.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = lift
  ctx.fillRect(x * u, (y + h) * u, w * u, 2 * u)
  ctx.restore()
}

/** Loose things on the floor: a book stack, a box, a guitar by the shelf. */
function drawFloorProps(ctx: Ctx, u: number) {
  // The books, the box, the mug and the plant are movable now — see
  // props.ts. Only the fixtures are drawn here.

  // Guitar leaning against the wall past the shelf, clear of the desk — half
  // a guitar behind a desk leg reads as a dark blob, not an instrument.
  const gx = 152
  contactShadow(ctx, u, gx + 2, FLOOR_Y + 0.8, 4, 1.4, 0.45)
  ctx.save()
  ctx.translate(gx * u, FLOOR_Y * u)
  ctx.rotate(-0.12)
  // Body.
  ctx.fillStyle = ROOM.walnut
  ctx.beginPath()
  ctx.ellipse(0, -5 * u, 4.2 * u, 5.4 * u, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.ellipse(0, -11 * u, 3.2 * u, 4.2 * u, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = mixHex(ROOM.walnutLit, '#FFFFFF', 0.1)
  ctx.beginPath()
  ctx.ellipse(-1.6 * u, -6 * u, 1.1 * u, 3.4 * u, 0, 0, Math.PI * 2)
  ctx.fill()
  // Sound hole and neck.
  ctx.fillStyle = '#100C0A'
  ctx.beginPath()
  ctx.ellipse(0, -8 * u, 1.5 * u, 1.5 * u, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = ROOM.woodDeep
  ctx.fillRect(-1 * u, -26 * u, 2 * u, 12 * u)
  ctx.fillStyle = ROOM.metalDark
  ctx.fillRect(-1.6 * u, -30 * u, 3.2 * u, 4.2 * u)
  ctx.fillStyle = ROOM.metal
  ctx.fillRect(-0.4 * u, -24 * u, 0.8 * u, 18 * u)
  ctx.restore()

  // Coat hook and a hanging scarf, kept well left of the curtain — anything
  // in that band reads as pinned to the window rather than to the wall.
  const hookX = 0
  r(ctx, u, hookX, 24, 8, 1.2, ROOM.woodShade)
  r(ctx, u, hookX, 24, 8, 0.35, ROOM.wood)
  for (const hx of [hookX + 1.5, hookX + 6]) r(ctx, u, hx, 25.2, 0.8, 1.6, ROOM.brass)
  ctx.save()
  ctx.fillStyle = ROOM.rugInk
  ctx.beginPath()
  ctx.moveTo((hookX + 5.4) * u, 26 * u)
  ctx.bezierCurveTo((hookX + 3) * u, 34 * u, (hookX + 8) * u, 38 * u, (hookX + 6) * u, 46 * u)
  ctx.lineTo((hookX + 8.4) * u, 46 * u)
  ctx.bezierCurveTo((hookX + 10) * u, 38 * u, (hookX + 6) * u, 34 * u, (hookX + 8) * u, 26 * u)
  ctx.closePath()
  ctx.fill()
  ctx.fillStyle = mixHex(ROOM.rugInk, '#FFFFFF', 0.16)
  ctx.fillRect((hookX + 5.6) * u, 27 * u, 0.7 * u, 18 * u)
  ctx.restore()
}

// ── composition ───────────────────────────────────────────────────────

/**
 * Everything that does not change between frames.
 *
 * Painted once into the backdrop cache. This is where the bulk of the room's
 * draw calls live — the floorboards alone are hundreds — so moving them here
 * is what makes the scene affordable on a slow machine, and what lets the
 * detail be generous without that being a performance decision.
 */
/**
 * The room state the bake was painted for.
 *
 * Set immediately before painting, so the baked sky and the key that names it
 * cannot disagree about which hour they belong to.
 */
let BAKED_STATE: RoomState = { hour: 12, lamp: 0, screen: 0, time: 0 }

function paintStatic(ctx: Ctx, u: number) {
  drawWallSurface(ctx, u)
  if (!panelsOwnPosterSlot()) drawPoster(ctx, u)
  drawPinboard(ctx, u)
  drawWallPanels(ctx, u)
  drawClockFace(ctx, u)
  drawWindowRecess(ctx, u)
  drawSky(ctx, u, BAKED_STATE)
  drawShelf(ctx, u)
  drawFittings(ctx, u)
  drawSkirting(ctx, u)
  drawFloor(ctx, u)
  drawRug(ctx, u)
  drawRadiator(ctx, u)
  drawFloorProps(ctx, u)
  drawDeskBody(ctx, u)
  // Last, so a mug on the desk sits on the desk and not under it.
  drawRestingProps(ctx, u, 0, { still: true })
}

/** Names every input the baked painting depends on. */
/** Twelve-minute buckets: the sky is baked, and it moves slowly. */
function hourBucket(hour: number): number {
  return Math.round(hour * 5)
}

function backdropKey(u: number): string {
  return [
    'enhanced',
    unitKey(u),
    quality().tier,
    // The view through the window is baked, so the hour is an input to it.
    String(BAKED_STATE_BUCKET),
    // Resting props and wall panels are painted into the bake. Both keys are
    // owned by the layers that draw them, so the two cannot drift apart.
    restingPropsKey(),
    wallPanelsKey(),
  ].join('|')
}

let BAKED_STATE_BUCKET = -1

export function drawRoomBack(ctx: Ctx, u: number, s: RoomState) {
  BAKED_STATE = s
  BAKED_STATE_BUCKET = hourBucket(s.hour)
  const baked = bakeBackdrop(u, backdropKey(u), paintStatic)
  if (baked) blitBackdrop(ctx, u, baked)
  else paintStatic(ctx, u)

  // ── everything that actually moves ───────────────────────────────
  drawSkyLife(ctx, u, s)
  drawWindowFrame(ctx, u)
  drawSillObjects(ctx, u, s)
  drawCurtains(ctx, u, s)
  drawClockHands(ctx, u, s)
  drawFloorSheen(ctx, u, s)
  drawLightShaft(ctx, u, s)
  drawLivingProps(ctx, u, s.time)
  drawDeskSurface(ctx, u, s)
  drawLamp(ctx, u, s)
}

/**
 * Out-of-focus foreground for depth. Drawn over the character, so it is kept
 * to the extreme edges where it never hides him.
 */
/**
 * Out-of-focus foreground for depth. Drawn over the character, so it is kept
 * to the extreme edges where it never hides him.
 *
 * Baked: it never changes, and `ctx.filter = 'blur(...)'` forces its own
 * compositing pass — one of the few genuinely expensive things a 2D canvas
 * can be asked to do, and it was being asked every frame.
 */
export function drawRoomFore(ctx: Ctx, u: number) {
  const baked = bakeForeground(u, `enhanced|${unitKey(u)}`, paintFore)
  if (baked) blitBackdrop(ctx, u, baked)
  else paintFore(ctx, u)
}

function paintFore(ctx: Ctx, u: number) {
  ctx.save()
  ctx.globalAlpha = 0.55
  ctx.filter = 'blur(7px)'

  // A chair back intruding from the near-left corner.
  ctx.fillStyle = '#0E0A08'
  ctx.fillRect(-14 * u, 52 * u, 16 * u, 40 * u)
  ctx.fillRect(-14 * u, 47 * u, 22 * u, 5.5 * u)
  ctx.fillRect(2 * u, 62 * u, 4 * u, 30 * u)

  // A trailing plant from the top-right, framing the other corner.
  ctx.fillStyle = '#16281A'
  ctx.fillRect(150 * u, -6 * u, 16 * u, 10 * u)
  for (let i = 0; i < 7; i++) {
    const lx = 150 + i * 2.2
    const len = 8 + Math.sin(i * 2.1) * 6 + 6
    ctx.fillRect(lx * u, 2 * u, 1.6 * u, len * u)
    ctx.fillRect((lx - 0.8) * u, (2 + len * 0.6) * u, 3 * u, 3 * u)
  }
  ctx.restore()
}

/** Grade passes applied over everything, including the character. */
export function drawRoomGrade(ctx: Ctx, u: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const daylight = daylightAt(s.hour)
  const x = ROOM_LEFT * u
  const w = ROOM_W * u
  const y = -10 * u
  const h = (STAGE.h + 20) * u

  // Ambient colour wash — cool by day, warm and dim at night.
  ctx.save()
  ctx.globalCompositeOperation = 'soft-light'
  ctx.globalAlpha = 0.42
  ctx.fillStyle = daylight > 0.4 ? sky.light : mixHex(ROOM.lamp, '#2A2350', 0.55)
  ctx.fillRect(x, y, w, h)
  ctx.restore()

  // Night dims the whole room; the lamp claws some of it back.
  const dark = (1 - daylight) * 0.44 * (1 - s.lamp * 0.42)
  if (dark > 0.01) {
    ctx.save()
    ctx.globalAlpha = dark
    const fall = ctx.createLinearGradient(0, 0, 0, STAGE.h * u)
    fall.addColorStop(0, '#05070F')
    fall.addColorStop(0.65, '#080A16')
    fall.addColorStop(1, '#0A0710')
    ctx.fillStyle = fall
    ctx.fillRect(x, y, w, h)
    ctx.restore()
  }

  // Warm bounce rising off the floor, so the room is lit from within.
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 0.05 + s.lamp * 0.05
  const bounce = ctx.createLinearGradient(0, STAGE.h * u, 0, (FLOOR_Y - 12) * u)
  bounce.addColorStop(0, ROOM.lampDeep)
  bounce.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = bounce
  ctx.fillRect(x, (FLOOR_Y - 12) * u, w, (STAGE.h - FLOOR_Y + 12) * u)
  ctx.restore()

  // Vignette.
  ctx.save()
  const vig = ctx.createRadialGradient(
    (STAGE.w / 2) * u, (STAGE.h / 2) * u, STAGE.h * u * 0.3,
    (STAGE.w / 2) * u, (STAGE.h / 2) * u, STAGE.w * u * 0.74,
  )
  vig.addColorStop(0, 'rgba(0,0,0,0)')
  vig.addColorStop(1, 'rgba(0,0,0,0.62)')
  ctx.fillStyle = vig
  ctx.fillRect(x, y, w, h)
  ctx.restore()
}

/**
 * How strongly the window and lamp light Clawd where he is standing, so the
 * sprite picks up the room instead of floating on top of it.
 */
export function lightingAt(x: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const daylight = daylightAt(s.hour)

  const shaftCentre = WINDOW.x + WINDOW.w / 2 + 26
  const inShaft = clamp01(1 - Math.abs(x - shaftCentre) / 30) * daylight

  const lampCentre = DESK.x + 23
  const nearLamp = clamp01(1 - Math.abs(x - lampCentre) / 26) * s.lamp

  const nearScreen = clamp01(1 - Math.abs(x - (DESK.x + 15)) / 20) * s.screen

  // Ambient darkness at night, lifted by whichever source is closest.
  const ambient = clamp(0.18 + (1 - daylight) * 0.3 - inShaft * 0.2 - nearLamp * 0.22, 0, 0.5)

  let rim = sky.light
  let rimAmount = inShaft * 0.35
  if (nearLamp > inShaft) {
    rim = ROOM.lamp
    rimAmount = nearLamp * 0.4
  }
  if (nearScreen > Math.max(inShaft, nearLamp)) {
    rim = ROOM.screenGlow
    rimAmount = nearScreen * 0.3
  }

  return {
    tint: daylight > 0.4 ? mixHex(sky.light, '#20242E', 0.5) : '#1A1630',
    tintAmount: ambient,
    rim,
    rimAmount,
  }
}

export { WINDOW, DESK }
