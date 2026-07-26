/**
 * The room Clawd lives in.
 *
 * A side-on interior drawn in the same square-pixel language as the sprite,
 * composed back-to-front: wall, window and its light shaft, furniture, floor,
 * then lighting and grade passes over the top. Everything is laid out in a
 * fixed 160 x 90 unit stage and scaled to fit the viewport, so the composition
 * holds at any window size.
 */

import { bakeBackdrop, blitBackdrop, ROOM_LEFT, ROOM_TOP, ROOM_W, unitKey } from './backdrop'
import { clamp, clamp01 } from './easing'
import { drawWallPanels } from './panelsLayer'
import { mixHex, ROOM, skyAt } from './paletteClassic'
import { panelStore } from '../panels'
import { PROP_IDS, propStore } from './props'
import { drawLivingProps, drawRestingProps } from './propsLayer'
import { quality } from './quality'
import { hash2 } from './texture'
import { FLOOR_Y, STAGE, WALK_RANGE } from './stage'

export { STAGE, FLOOR_Y, WALK_RANGE }

export type StationId = 'desk' | 'window' | 'shelf' | 'rug' | 'centre' | 'plant'

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
  { id: 'rug', x: 79, facing: 1, label: 'the rug' },
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

/** Fill a rect in stage units. */
function r(ctx: Ctx, u: number, x: number, y: number, w: number, h: number, fill: string) {
  ctx.fillStyle = fill
  ctx.fillRect(x * u, y * u, w * u, h * u)
}

// ── window ────────────────────────────────────────────────────────────

const WINDOW = { x: 22, y: 12, w: 30, h: 32 }

/** The opening's recess and its sill. Masonry, so it bakes. */
function drawWindowRecess(ctx: Ctx, u: number) {
  const { x, y, w, h } = WINDOW
  r(ctx, u, x - 1.5, y - 1.5, w + 3, h + 3, ROOM.wallShade)
  r(ctx, u, x - 2, y + h, w + 4, 1.6, ROOM.wood) // sill
  r(ctx, u, x - 2, y + h, w + 4, 0.4, ROOM.woodLit)
}

/** The view. Redrawn because the sky turns with the hour. */
function drawWindowGlass(ctx: Ctx, u: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const { x, y, w, h } = WINDOW

  const grad = ctx.createLinearGradient(0, y * u, 0, (y + h) * u)
  grad.addColorStop(0, sky.top)
  grad.addColorStop(1, sky.bottom)
  ctx.fillStyle = grad
  ctx.fillRect(x * u, y * u, w * u, h * u)

  // Distant skyline — a few flat blocks, darker than the sky.
  const skyline = [
    { x: 2, w: 5, h: 9 },
    { x: 8, w: 3, h: 14 },
    { x: 12, w: 6, h: 7 },
    { x: 19, w: 4, h: 12 },
    { x: 24, w: 4, h: 6 },
  ]
  const cityTone = mixHex(sky.bottom, '#0B0A12', 0.62)
  for (const b of skyline) {
    r(ctx, u, x + b.x, y + h - b.h, b.w, b.h, cityTone)
    // Lit windows appear after dark.
    const night = clamp01((Math.abs(s.hour - 13) - 4) / 5)
    if (night > 0.2) {
      ctx.globalAlpha = night * 0.75
      for (let wy = 0; wy < b.h - 2; wy += 2.5) {
        for (let wx = 0.8; wx < b.w - 1; wx += 2) {
          // Deterministic scatter so windows do not flicker every frame.
          if (((b.x + wx) * 7 + wy * 13) % 5 > 2.6) continue
          r(ctx, u, x + b.x + wx, y + h - b.h + wy + 1, 0.7, 0.7, ROOM.lamp)
        }
      }
      ctx.globalAlpha = 1
    }
  }

}

/** Joinery, back on top of the live view. */
function drawWindowFrame(ctx: Ctx, u: number) {
  const { x, y, w, h } = WINDOW
  r(ctx, u, x + w / 2 - 0.5, y, 1, h, ROOM.wallShade)
  r(ctx, u, x, y + h / 2 - 0.5, w, 1, ROOM.wallShade)
  ctx.strokeStyle = ROOM.woodShade
  ctx.lineWidth = 1.6 * u
  ctx.strokeRect(x * u, y * u, w * u, h * u)
}

/** Volumetric shaft cast from the window onto the floor. */
function drawLightShaft(ctx: Ctx, u: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const daylight = 1 - clamp01((Math.abs(s.hour - 13) - 3.5) / 5.5)
  if (daylight < 0.04) return

  const { x, y, w } = WINDOW
  ctx.save()
  ctx.globalCompositeOperation = 'lighter'
  ctx.globalAlpha = 0.13 * daylight

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

  // The bright patch where it lands.
  ctx.globalAlpha = 0.1 * daylight
  ctx.beginPath()
  ctx.ellipse((x + w / 2 + 26) * u, FLOOR_Y * u, 26 * u, 4 * u, 0, 0, Math.PI * 2)
  ctx.fill()

  // Motes drifting through the beam.
  ctx.globalAlpha = 0.5 * daylight
  ctx.fillStyle = sky.light
  for (let i = 0; i < 34; i++) {
    const seed = i * 12.9898
    const drift = (s.time * (0.12 + (i % 5) * 0.035) + (Math.sin(seed) * 0.5 + 0.5)) % 1
    const px = x + 4 + ((Math.sin(seed * 3.1) * 0.5 + 0.5) * (w + 30)) + drift * 8
    const py = y + drift * (FLOOR_Y - y)
    const bob = Math.sin(s.time * 0.8 + seed) * 0.6
    ctx.globalAlpha = 0.45 * daylight * (1 - drift) * (0.4 + (i % 3) * 0.3)
    ctx.fillRect((px + bob) * u, py * u, 0.35 * u, 0.35 * u)
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

/** The desk carcass. Furniture, so it bakes. */
function drawDeskBody(ctx: Ctx, u: number) {
  const { x, y, w } = DESK

  // Legs first so the top overlaps them.
  r(ctx, u, x + 1.5, y + 2, 1.6, FLOOR_Y - y - 2, ROOM.woodShade)
  r(ctx, u, x + w - 3, y + 2, 1.6, FLOOR_Y - y - 2, ROOM.woodShade)
  // Top.
  r(ctx, u, x, y, w, 2, ROOM.wood)
  r(ctx, u, x, y, w, 0.6, ROOM.woodLit)
  r(ctx, u, x, y + 2, w, 0.7, ROOM.woodShade)

  drawDeskExtras(ctx, u)
}

/** The monitor, whose screen is the one thing on this desk that moves. */
function drawMonitor(ctx: Ctx, u: number, s: RoomState) {
  const { x, y } = DESK
  const mx = x + 8
  const my = y - 15
  r(ctx, u, mx + 6, my + 12, 3, 3, ROOM.metal) // stand
  r(ctx, u, mx + 3, my + 14.6, 9, 1, ROOM.metal) // foot
  r(ctx, u, mx - 1, my - 1, 17, 14, ROOM.metal)
  r(ctx, u, mx, my, 15, 12, ROOM.screen)

  // Screen content — scrolling code lines, glowing when Rau works.
  ctx.save()
  ctx.beginPath()
  ctx.rect(mx * u, my * u, 15 * u, 12 * u)
  ctx.clip()
  const scroll = (s.time * 6) % 2
  for (let i = 0; i < 8; i++) {
    const ly = my + 1 + i * 1.5 - scroll
    const lw = 3 + ((i * 37) % 9)
    ctx.globalAlpha = 0.25 + s.screen * 0.6
    r(ctx, u, mx + 1, ly, lw, 0.6, i % 3 === 0 ? ROOM.screenGlow : '#7A8B96')
  }
  ctx.restore()
  ctx.globalAlpha = 1

  // Monitor bloom.
  if (s.screen > 0.02) {
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.globalAlpha = 0.14 * s.screen
    const g = ctx.createRadialGradient(
      (mx + 7.5) * u, (my + 6) * u, 0,
      (mx + 7.5) * u, (my + 6) * u, 26 * u,
    )
    g.addColorStop(0, ROOM.screenGlow)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fillRect((mx - 20) * u, (my - 16) * u, 56 * u, 46 * u)
    ctx.restore()
  }

}

/** Keyboard and oddments. The mug left this desk to become a movable prop. */
function drawDeskExtras(ctx: Ctx, u: number) {
  const { x, y } = DESK
  r(ctx, u, x + 4, y - 1, 12, 1, ROOM.metal)
  r(ctx, u, x + 4, y - 1, 12, 0.35, ROOM.metalLit)
}

function drawLamp(ctx: Ctx, u: number, s: RoomState) {
  const x = DESK.x + 27
  const y = DESK.y - 12

  r(ctx, u, x, y + 10, 4, 1, ROOM.metal) // base
  r(ctx, u, x + 1.6, y + 2, 0.8, 8, ROOM.metal) // stem
  r(ctx, u, x - 1, y, 6, 2.5, s.lamp > 0.5 ? ROOM.metalLit : ROOM.metal) // shade

  if (s.lamp > 0.02) {
    // Bulb.
    r(ctx, u, x + 1, y + 2.5, 2, 1, ROOM.lamp)
    // Cone of light down onto the desk.
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.globalAlpha = 0.16 * s.lamp
    const g = ctx.createLinearGradient(0, (y + 2) * u, 0, DESK.y * u)
    g.addColorStop(0, ROOM.lamp)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.beginPath()
    ctx.moveTo((x - 0.5) * u, (y + 2.5) * u)
    ctx.lineTo((x + 4.5) * u, (y + 2.5) * u)
    ctx.lineTo((x + 12) * u, DESK.y * u)
    ctx.lineTo((x - 8) * u, DESK.y * u)
    ctx.closePath()
    ctx.fill()
    ctx.restore()
  }
}

function drawShelf(ctx: Ctx, u: number) {
  const x = 130
  const y = 30

  for (const sy of [y, y + 12]) {
    r(ctx, u, x, sy, 24, 1.2, ROOM.wood)
    r(ctx, u, x, sy, 24, 0.4, ROOM.woodLit)
    r(ctx, u, x, sy + 1.2, 24, 0.5, '#00000055')
  }
  r(ctx, u, x, y, 1, 24, ROOM.woodShade)
  r(ctx, u, x + 23, y, 1, 24, ROOM.woodShade)

  // Books, deterministic sizes and hues.
  const spines = [
    { w: 1.6, h: 8, c: '#8A4B3A' },
    { w: 1.2, h: 9.5, c: '#5C6B7A' },
    { w: 2, h: 7.5, c: '#7A6A44' },
    { w: 1.4, h: 9, c: '#6B4A5C' },
    { w: 1.8, h: 8.5, c: '#4A6355' },
    { w: 1.2, h: 7, c: '#8A6A4A' },
  ]
  let bx = x + 2
  for (const sp of spines) {
    r(ctx, u, bx, y - sp.h, sp.w, sp.h, sp.c)
    r(ctx, u, bx, y - sp.h, sp.w, 0.5, mixHex(sp.c, '#FFFFFF', 0.25))
    bx += sp.w + 0.4
  }
  // Second shelf: a leaning stack and a small plant.
  r(ctx, u, x + 3, y + 5.5, 7, 1.4, '#6B5A44')
  r(ctx, u, x + 3.5, y + 4.2, 6, 1.3, '#7A5C48')
  r(ctx, u, x + 15, y + 8.5, 3.5, 3.5, ROOM.fabric)
  r(ctx, u, x + 15.5, y + 5.5, 2.5, 3, ROOM.leaf)
  r(ctx, u, x + 14.4, y + 6.5, 1.2, 1.8, ROOM.leafLit)
  r(ctx, u, x + 18, y + 6.8, 1.2, 1.6, ROOM.leafLit)
}


function drawRug(ctx: Ctx, u: number) {
  const x = 62
  const y = FLOOR_Y

  ctx.save()
  ctx.globalAlpha = 0.9
  r(ctx, u, x, y, 34, 3.4, ROOM.fabric)
  r(ctx, u, x, y, 34, 0.7, ROOM.fabricLit)
  // Woven stripes.
  for (let i = 2; i < 32; i += 5) {
    r(ctx, u, x + i, y + 1, 2, 2, mixHex(ROOM.fabric, '#000000', 0.25))
  }
  // Fringe.
  for (let i = 0; i < 34; i += 2) {
    r(ctx, u, x + i, y + 3.4, 1, 0.7, ROOM.fabricLit)
  }
  ctx.restore()
}

function drawPoster(ctx: Ctx, u: number) {
  const x = 74
  const y = 16

  r(ctx, u, x - 0.8, y - 0.8, 15.6, 20.6, '#1A1512')
  r(ctx, u, x, y, 14, 19, '#3A3028')
  // A tiny Clawd silhouette on the poster — a nod, not a duplicate.
  r(ctx, u, x + 4, y + 6, 6, 4.5, ROOM.screenGlow)
  r(ctx, u, x + 2.8, y + 7.5, 1.2, 1.2, ROOM.screenGlow)
  r(ctx, u, x + 10, y + 7.5, 1.2, 1.2, ROOM.screenGlow)
  r(ctx, u, x + 5.4, y + 7.4, 0.9, 0.9, '#1A1512')
  r(ctx, u, x + 7.7, y + 7.4, 0.9, 0.9, '#1A1512')
  for (const lx of [4.4, 6, 8, 9.6]) r(ctx, u, x + lx, y + 10.5, 0.7, 1.6, ROOM.screenGlow)
  r(ctx, u, x + 3, y + 14.5, 8, 0.6, '#6A5E52')
  r(ctx, u, x + 3, y + 16, 5.5, 0.6, '#6A5E52')
}

// ── composition ───────────────────────────────────────────────────────

/**
 * Architecture, drawn in flat colour.
 *
 * The enhanced room earns its depth from per-pixel grain and stacked
 * gradients. This gets the same *shapes* — panelled dado, mouldings, a floor
 * made of boards rather than a gradient with lines on it — out of plain
 * rectangles, which cost almost nothing and, because the whole lot is baked
 * once, cost nothing at all per frame.
 *
 * That is the trade: classic is not "the room with things missing", it is the
 * room drawn with a cheaper brush.
 */
function paintClassicStatic(ctx: Ctx, u: number) {
  // Wall, with a soft top-down gradient and generous bleed for camera pans.
  const wall = ctx.createLinearGradient(0, 0, 0, FLOOR_Y * u)
  wall.addColorStop(0, ROOM.wallLit)
  wall.addColorStop(0.6, ROOM.wall)
  wall.addColorStop(1, mixHex(ROOM.wall, '#000000', 0.12))
  ctx.fillStyle = wall
  ctx.fillRect(ROOM_LEFT * u, ROOM_TOP * u, ROOM_W * u, (FLOOR_Y - ROOM_TOP) * u)

  // Crown moulding and the shadow under it.
  r(ctx, u, ROOM_LEFT, 1.5, ROOM_W, 2.4, ROOM.wallWarm)
  r(ctx, u, ROOM_LEFT, 1.5, ROOM_W, 0.5, mixHex(ROOM.wallWarm, '#FFFFFF', 0.3))
  r(ctx, u, ROOM_LEFT, 3.9, ROOM_W, 0.5, ROOM.wallShade)

  drawClassicWainscot(ctx, u)

  drawPoster(ctx, u)
  drawWallPanels(ctx, u)
  drawWindowRecess(ctx, u)
  drawShelf(ctx, u)

  // Skirting with a two-step profile, which is most of what reads as a
  // skirting rather than a dark stripe.
  const top = FLOOR_Y - 3
  r(ctx, u, ROOM_LEFT, top, ROOM_W, 3, ROOM.skirting)
  r(ctx, u, ROOM_LEFT, top, ROOM_W, 0.5, mixHex(ROOM.skirting, '#FFFFFF', 0.18))
  r(ctx, u, ROOM_LEFT, top + 1.1, ROOM_W, 0.3, mixHex(ROOM.skirting, '#000000', 0.5))

  drawClassicFloor(ctx, u)
  drawRug(ctx, u)
  drawDeskBody(ctx, u)
  // After the desk and the shelf, so a mug on either sits on top of it.
  drawRestingProps(ctx, u, 0, { still: true })
}

/** Panelled dado: stiles, recessed fields, and a rail — all flat fills. */
function drawClassicWainscot(ctx: Ctx, u: number) {
  const railY = 46
  const top = railY + 1.4
  const bottom = FLOOR_Y - 3
  const height = bottom - top
  const field = mixHex(ROOM.wall, ROOM.wallWarm, 0.55)

  r(ctx, u, ROOM_LEFT, top, ROOM_W, height, field)

  const pitch = 17
  const stile = 3.4
  for (let x = ROOM_LEFT; x < ROOM_LEFT + ROOM_W; x += pitch) {
    const px = x + stile
    const pw = pitch - stile * 2
    const py = top + 2.4
    const ph = height - 4.8
    if (pw <= 0 || ph <= 0) continue
    r(ctx, u, px, py, pw, ph, mixHex(field, '#000000', 0.3))
    // Two bevel edges are enough to read as sunk; four is a diminishing return.
    r(ctx, u, px, py, pw, 0.5, mixHex(field, '#000000', 0.55))
    r(ctx, u, px, py + ph - 0.5, pw, 0.5, mixHex(field, '#FFFFFF', 0.16))
  }

  r(ctx, u, ROOM_LEFT, railY, ROOM_W, 1.5, ROOM.wallWarm)
  r(ctx, u, ROOM_LEFT, railY, ROOM_W, 0.4, mixHex(ROOM.wallWarm, '#FFFFFF', 0.34))
  r(ctx, u, ROOM_LEFT, railY + 1.5, ROOM_W, 0.4, ROOM.wallShade)
}

/** Boards that vary board to board, rather than a gradient with lines on it. */
function drawClassicFloor(ctx: Ctx, u: number) {
  const depth = STAGE.h - FLOOR_Y
  const floor = ctx.createLinearGradient(0, FLOOR_Y * u, 0, STAGE.h * u)
  floor.addColorStop(0, ROOM.floor)
  floor.addColorStop(0.45, ROOM.floorLit)
  floor.addColorStop(1, mixHex(ROOM.floorWarm, '#000000', 0.22))
  ctx.fillStyle = floor
  ctx.fillRect(ROOM_LEFT * u, FLOOR_Y * u, ROOM_W * u, depth * u)

  const jointX = (i: number, t: number) => STAGE.w / 2 + i * (9 + t * 16)

  // Each board takes its own stain: one extra fill per board, and the single
  // biggest reason a floor stops reading as a sheet of colour.
  ctx.save()
  for (let i = -14; i <= 26; i++) {
    const shift = hash2(i, 7, 55) - 0.5
    ctx.globalAlpha = 0.14 + Math.abs(shift) * 0.18
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

  ctx.save()
  ctx.lineWidth = Math.max(1, 0.2 * u)
  for (let i = -14; i <= 26; i++) {
    ctx.globalAlpha = 0.3
    ctx.strokeStyle = ROOM.floorSeam
    ctx.beginPath()
    ctx.moveTo(jointX(i, 0) * u, FLOOR_Y * u)
    ctx.lineTo(jointX(i, 1) * u, STAGE.h * u)
    ctx.stroke()
  }
  ctx.restore()
}

/** Names every input the baked classic painting depends on. */
function classicKey(u: number): string {
  const layout = PROP_IDS.map((id) => `${id}:${propStore.spotOf(id)}`).join(',')
  const wall = panelStore.list().map((panel) => `${panel.panel_id}:${panel.kind}`).join(',')
  return ['classic', unitKey(u), quality().tier, layout, wall].join('|')
}

export function drawRoomBack(ctx: Ctx, u: number, s: RoomState) {
  const baked = bakeBackdrop(u, classicKey(u), paintClassicStatic)
  if (baked) blitBackdrop(ctx, u, baked)
  else paintClassicStatic(ctx, u)

  // Only what actually moves.
  drawWindowGlass(ctx, u, s)
  drawWindowFrame(ctx, u)
  drawLightShaft(ctx, u, s)
  drawLivingProps(ctx, u, s.time)
  drawMonitor(ctx, u, s)
  drawLamp(ctx, u, s)
}

/**
 * Out-of-focus foreground for depth. Drawn over the character, so it is kept
 * to the extreme edges where it never hides him.
 */
export function drawRoomFore(ctx: Ctx, u: number) {
  ctx.save()
  ctx.globalAlpha = 0.5
  ctx.filter = 'blur(6px)'
  // A chair back intruding from the near-left corner.
  ctx.fillStyle = '#100C0A'
  ctx.fillRect(-4 * u, 52 * u, 12 * u, 38 * u)
  ctx.fillRect(-4 * u, 48 * u, 16 * u, 5 * u)
  ctx.restore()
}

/** Grade passes applied over everything, including the character. */
export function drawRoomGrade(ctx: Ctx, u: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const daylight = 1 - clamp01((Math.abs(s.hour - 13) - 3.5) / 5.5)

  // Ambient colour wash — cool by day, warm and dim at night.
  ctx.save()
  ctx.globalCompositeOperation = 'soft-light'
  ctx.globalAlpha = 0.4
  ctx.fillStyle = daylight > 0.4 ? sky.light : mixHex(ROOM.lamp, '#2A2350', 0.55)
  ctx.fillRect(0, 0, STAGE.w * u, STAGE.h * u)
  ctx.restore()

  // Night dims the whole room; the lamp claws some of it back.
  const dark = (1 - daylight) * 0.42 * (1 - s.lamp * 0.45)
  if (dark > 0.01) {
    ctx.save()
    ctx.globalAlpha = dark
    ctx.fillStyle = '#080A16'
    ctx.fillRect(0, 0, STAGE.w * u, STAGE.h * u)
    ctx.restore()
  }

  // Vignette.
  ctx.save()
  const vig = ctx.createRadialGradient(
    (STAGE.w / 2) * u, (STAGE.h / 2) * u, STAGE.h * u * 0.34,
    (STAGE.w / 2) * u, (STAGE.h / 2) * u, STAGE.w * u * 0.72,
  )
  vig.addColorStop(0, 'rgba(0,0,0,0)')
  vig.addColorStop(1, 'rgba(0,0,0,0.55)')
  ctx.fillStyle = vig
  ctx.fillRect(0, 0, STAGE.w * u, STAGE.h * u)
  ctx.restore()
}

/**
 * How strongly the window and lamp light Clawd where he is standing, so the
 * sprite picks up the room instead of floating on top of it.
 */
export function lightingAt(x: number, s: RoomState) {
  const sky = skyAt(s.hour)
  const daylight = 1 - clamp01((Math.abs(s.hour - 13) - 3.5) / 5.5)

  const shaftCentre = WINDOW.x + WINDOW.w / 2 + 26
  const inShaft = clamp01(1 - Math.abs(x - shaftCentre) / 30) * daylight

  const lampCentre = DESK.x + 27
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
