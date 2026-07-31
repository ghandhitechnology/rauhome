/**
 * The stage: owns the canvas, the camera, and the back-to-front draw order.
 *
 * The room is authored in a fixed 160 x 90 unit space and letterboxed into
 * whatever canvas it is given, so the composition survives any window size.
 */

import { clamp, clamp01, damp } from './easing'
import { quality } from './quality'
import { drawCarriedProp } from './propsLayer'
import { CLAWD } from './palette'
import type { ParamSet } from './params'
import {
  FLOOR_Y,
  STAGE,
  drawRoomBack as drawEnhancedBack,
  drawRoomFore as drawEnhancedFore,
  drawRoomGrade as drawEnhancedGrade,
  lightingAt as lightingEnhanced,
  type RoomState,
} from './room'
import {
  drawRoomBack as drawClassicBack,
  drawRoomFore as drawClassicFore,
  drawRoomGrade as drawClassicGrade,
  lightingAt as lightingClassic,
} from './roomClassic'
import type { RoomVisual } from './roomVisual'
import { drawGameTable, GAME_TABLE } from './gameTableLayer'
import { clawdBounds, drawClawd } from './sprite'

export type Camera = {
  /** Stage-unit offset applied to everything. */
  x: number
  y: number
  zoom: number
}

/**
 * Radial table-dim gradients, shared across frames.
 *
 * Keyed by pixel radius and 1/24 alpha steps. Built at the origin; callers
 * translate the context onto the light, so a moving camera never invalidates
 * the entry. The working set is one radius per window size and a handful of
 * alpha steps — the cap is a leak guard, not a policy.
 */
const dimGradients = new Map<string, CanvasGradient>()

function dimGradient(
  ctx: CanvasRenderingContext2D,
  radius: number,
  alphaStep: number,
): CanvasGradient {
  const key = `${radius}|${alphaStep}`
  const cached = dimGradients.get(key)
  if (cached) return cached
  const a = alphaStep / 24
  const g = ctx.createRadialGradient(0, 0, radius * 0.16, 0, 0, radius)
  g.addColorStop(0, 'rgba(6, 5, 8, 0)')
  g.addColorStop(0.55, `rgba(6, 5, 8, ${a * 0.45})`)
  g.addColorStop(1, `rgba(6, 5, 8, ${a})`)
  dimGradients.set(key, g)
  if (dimGradients.size > 32) {
    const oldest = dimGradients.keys().next().value
    if (oldest !== undefined) dimGradients.delete(oldest)
  }
  return g
}

export type SceneOptions = {
  /** Follow the character instead of holding a wide shot. */
  follow?: boolean
  /** Parallax target from the pointer, -1..1 on each axis. */
  parallax?: { x: number; y: number }
  /** Draw the room, or just the character on transparent background. */
  showRoom?: boolean
  /** Character scale multiplier. */
  charScale?: number
  /**
   * Somewhere specific to point the camera, overriding the follow shot.
   *
   * Set while the card table is up: an over-the-shoulder shot has to hold
   * still, because the cards are DOM elements glued to it and a camera that
   * swam with the pointer would unglue them from the table.
   */
  cameraTarget?: { x: number; y: number; zoom: number; lambda?: number } | null
  /** 0..1 presence of the card table prop. */
  gameTable?: number
  /** 0..1 darkness outside the light over the table. */
  gameDim?: number
}

export class Scene {
  readonly camera: Camera = { x: 0, y: 0, zoom: 1 }
  private grainSeed = 0
  private grainTime = 0
  /** classic = original flat room; enhanced = materials/architecture pass. */
  roomVisual: RoomVisual = 'enhanced'

  /** Canvas pixels per stage unit, recomputed each resize. */
  unit = 1
  private offsetX = 0
  private offsetY = 0

  layout(width: number, height: number, dpr: number, opts: SceneOptions = {}) {
    void dpr
    // Desktop pet: fit a narrow band around centre so walking stays on-screen
    // (full-stage cover crops the sides and lets him walk out of the window).
    if (opts.showRoom === false) {
      const viewW = 72
      const viewH = 86
      const scale = Math.min(width / viewW, height / viewH)
      this.unit = scale
      const viewLeft = STAGE.w / 2 - viewW / 2
      // Bias the crop so feet sit near the bottom and the bubble has headroom.
      const viewTop = FLOOR_Y - viewH * 0.78
      this.offsetX = (width - viewW * scale) / 2 - viewLeft * scale
      this.offsetY = (height - viewH * scale) / 2 - viewTop * scale
      return
    }

    // Cover the viewport rather than fit, so there are never letterbox bars;
    // the composition is authored with slack at the edges for exactly this.
    const scale = Math.max(width / STAGE.w, height / STAGE.h)
    this.unit = scale
    this.offsetX = (width - STAGE.w * scale) / 2
    this.offsetY = (height - STAGE.h * scale) / 2
  }

  update(dt: number, worldX: number, opts: SceneOptions) {
    const par = opts.parallax || { x: 0, y: 0 }
    const aim = opts.cameraTarget
    if (aim) {
      // Parallax is kept, at about a third of its usual travel: enough that
      // the shot is not dead, little enough that the cards stay put.
      const lambda = aim.lambda ?? 2.4
      this.camera.x = damp(this.camera.x, aim.x + par.x * 0.7, lambda, dt)
      this.camera.y = damp(this.camera.y, aim.y + par.y * 0.45, lambda, dt)
      this.camera.zoom = damp(this.camera.zoom, aim.zoom, lambda, dt)
    } else {
      const followX = opts.follow ? clamp((worldX - STAGE.w / 2) * 0.22, -18, 18) : 0
      this.camera.x = damp(this.camera.x, followX + par.x * 2.2, 2.4, dt)
      this.camera.y = damp(this.camera.y, par.y * 1.4, 2.4, dt)
      this.camera.zoom = damp(this.camera.zoom, opts.follow ? 1.14 : 1, 2, dt)
    }
    this.grainTime += dt
    // Grain re-scatters on a film cadence, not a display one: tied to the draw
    // rate it shimmers at 120Hz on a fast panel, which reads as buzzing
    // rather than as film.
    this.grainSeed = Math.floor(this.grainTime * 24) % 1000
  }

  /**
   * Render one frame.
   *
   * `worldX` is where Clawd stands in stage units; the rig's own posX/posY
   * offsets are applied on top by the sprite itself.
   */
  render(
    ctx: CanvasRenderingContext2D,
    params: ParamSet,
    worldX: number,
    room: RoomState,
    opts: SceneOptions = {},
  ) {
    const u = this.unit
    const showRoom = opts.showRoom ?? true

    ctx.save()

    // Camera.
    ctx.translate(this.offsetX, this.offsetY)
    const cz = this.camera.zoom
    ctx.translate((STAGE.w * u) / 2, (STAGE.h * u) / 2)
    ctx.scale(cz, cz)
    ctx.translate(-(STAGE.w * u) / 2, -(STAGE.h * u) / 2)
    ctx.translate(-this.camera.x * u, -this.camera.y * u)

    const classic = this.roomVisual === 'classic'
    if (showRoom) {
      if (classic) drawClassicBack(ctx, u, room)
      else drawEnhancedBack(ctx, u, room)
    }

    // Character sits between the wall and the near furniture.
    const light = showRoom
      ? classic
        ? lightingClassic(worldX, room)
        : lightingEnhanced(worldX, room)
      : null
    // 1.25 puts him at ~12 stage units tall — small enough to read as a desk
    // creature, tall enough to clear the desk top and the rug.
    const charUnit = u * 1.25 * (opts.charScale ?? 1)
    const spriteAt = { unit: charUnit, x: worldX * u, y: FLOOR_Y * u }
    drawClawd(ctx, params, {
      ...spriteAt,
      light: light?.tint,
      lightAmount: light?.tintAmount,
      rim: light?.rim,
      rimAmount: light?.rimAmount,
    })

    // Whatever he is holding rides in front of him, so it reads as carried
    // rather than as something moving alongside him. It is placed off the same
    // transform the sprite was just drawn with, so it sits in the claws that
    // are actually on screen rather than near where they usually are.
    if (showRoom) drawCarriedProp(ctx, u, room.time, { params, ...spriteAt })

    // The card table comes after him: he sits behind it, and the top edge
    // taking his lap is what puts him *at* the table rather than next to it.
    if (showRoom && (opts.gameTable ?? 0) > 0.002) {
      drawGameTable(ctx, u, opts.gameTable as number, room.time)
    }

    if (showRoom) {
      if (classic) {
        drawClassicFore(ctx, u)
        drawClassicGrade(ctx, u, room)
      } else {
        drawEnhancedFore(ctx, u)
        drawEnhancedGrade(ctx, u, room)
      }
    }

    ctx.restore()

    // Painted here rather than as a DOM overlay so it lands *under* the speech
    // bubble, which is drawn after this: he keeps trash-talking at full
    // brightness while the rest of the room goes quiet around the table.
    if (showRoom && (opts.gameDim ?? 0) > 0.002) {
      this.drawTableDim(ctx, opts.gameDim as number)
    }

    if (showRoom) this.drawGrain(ctx)
  }

  /**
   * Project a point in canvas-stage pixels onto the screen, in CSS pixels.
   *
   * The one place the camera maths lives. Everything that needs to know where
   * something in the room lands on screen goes through here.
   */
  project(px: number, py: number) {
    const u = this.unit
    const cz = this.camera.zoom
    const cx = STAGE.w * u * 0.5
    const cy = STAGE.h * u * 0.5
    return {
      x: this.offsetX + cx + (px - cx - this.camera.x * u) * cz,
      y: this.offsetY + cy + (py - cy - this.camera.y * u) * cz,
    }
  }

  /** Project a point authored in stage units. */
  stagePoint(x: number, y: number) {
    return this.project(x * this.unit, y * this.unit)
  }

  /**
   * The same projection as one uniform transform: `screen = stage * k + t`.
   *
   * There is no rotation and one shared scale, which is what lets a whole
   * layer of DOM cards ride the camera on a single CSS matrix instead of a
   * per-element write every frame.
   */
  viewTransform(): { k: number; tx: number; ty: number } {
    const u = this.unit
    const cz = this.camera.zoom
    const k = u * cz
    return {
      k,
      tx: this.offsetX + STAGE.w * u * 0.5 * (1 - cz) - this.camera.x * k,
      ty: this.offsetY + STAGE.h * u * 0.5 * (1 - cz) - this.camera.y * k,
    }
  }

  /** Where the sprite lands on screen, for speech bubbles and hit testing. */
  screenRect(params: ParamSet, worldX: number, charScale = 1) {
    const b = clawdBounds(params, {
      unit: this.unit * 1.25 * charScale,
      x: worldX * this.unit,
      y: FLOOR_Y * this.unit,
    })
    const tl = this.project(b.x, b.y)
    const br = this.project(b.x + b.w, b.y + b.h)
    return { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y }
  }

  /**
   * Project a rect authored in stage units onto the screen.
   *
   * For things whose position is known in the room's own coordinates rather
   * than derived from the rig — the framed panels on the back wall being the
   * reason this exists.
   */
  stageRect(x: number, y: number, w: number, h: number) {
    const tl = this.stagePoint(x, y)
    const br = this.stagePoint(x + w, y + h)
    return { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y }
  }

  /** Everything outside the light over the table falls away. */
  private drawTableDim(ctx: CanvasRenderingContext2D, amount: number) {
    const dpr = ctx.getTransform().a || 1
    const w = ctx.canvas.width / dpr
    const h = ctx.canvas.height / dpr
    const c = this.stagePoint(GAME_TABLE.x, GAME_TABLE.topY - 5)
    // Tight, and most of the falloff spent early: the point is a lamp over a
    // table with a room going quiet around it, not an even wash over the shot.
    const r = Math.max(w, h) * 0.62
    const a = clamp01(amount)
    // The gradient is built at the origin and the context translated onto it,
    // so one cached gradient serves every camera position — the camera moves
    // on every one of these frames, and rebuilding a radial each time was
    // pure churn.
    const g = dimGradient(ctx, Math.round(r), Math.round(a * 24))
    ctx.save()
    ctx.translate(c.x, c.y)
    ctx.fillStyle = g
    ctx.fillRect(-c.x, -c.y, w, h)
    ctx.restore()
  }

  /** Subtle film grain, redrawn as sparse dots rather than per-pixel noise. */
  private drawGrain(ctx: CanvasRenderingContext2D) {
    if (!quality().grain) return
    // canvas.width counts device pixels while the transform the dots are
    // drawn through is dpr-scaled: undivided, up to half the scatter lands
    // offscreen and the rest renders at twice the intended size.
    const dpr = ctx.getTransform().a || 1
    const w = ctx.canvas.width / dpr
    const h = ctx.canvas.height / dpr
    ctx.save()
    ctx.globalAlpha = 0.028
    ctx.fillStyle = '#FFFFFF'
    // Deliberately sparse: at this alpha each dot is sub-perceptible, so the
    // density buys texture, not detail — and every dot is a fillRect on the
    // hottest path the room has.
    const count = Math.min(420, Math.floor((w * h) / 11000))
    for (let i = 0; i < count; i++) {
      const n = Math.sin((i + this.grainSeed) * 12.9898) * 43758.5453
      const m = Math.sin((i + this.grainSeed) * 78.233) * 12345.6789
      const x = (n - Math.floor(n)) * w
      const y = (m - Math.floor(m)) * h
      ctx.fillRect(x, y, 1.4, 1.4)
    }
    ctx.restore()
  }
}

export type BubbleRect = { x: number; y: number; w: number; h: number }

type BubbleLayout = { lines: string[]; w: number; h: number }

/**
 * Wrapped and measured bubble text, cached by content and box.
 *
 * A bubble sits over his head for seconds at a time — and was being wrapped
 * and measured again on every frame of those seconds, a dozen-plus
 * `measureText` calls a frame. The text only actually changes when a token
 * lands, so the layout is computed then and replayed for the frames between.
 */
const bubbleLayouts = new Map<string, BubbleLayout>()

function layoutBubble(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  scale: number,
): BubbleLayout | null {
  const key = `${Math.round(maxWidth)}|${Math.round(scale * 100)}|${text}`
  const hit = bubbleLayouts.get(key)
  if (hit) {
    // Refresh recency: the line being read should be the last thing evicted
    // while a stream keeps typing past it.
    bubbleLayouts.delete(key)
    bubbleLayouts.set(key, hit)
    return hit
  }

  const pad = 10 * scale
  const lineH = 17 * scale
  ctx.font = `${Math.round(13 * scale)}px "DM Sans", system-ui, sans-serif`

  // Word wrap (break only overlong tokens), then keep the newest lines so a
  // word-by-word stream does not freeze on the opening sentence.
  const maxInner = maxWidth - pad * 2
  const wrapped: string[] = []
  const pushWrapped = (chunk: string) => {
    if (!chunk) return
    if (ctx.measureText(chunk).width <= maxInner) {
      wrapped.push(chunk)
      return
    }
    let piece = ''
    for (const ch of chunk) {
      const probe = piece + ch
      if (piece && ctx.measureText(probe).width > maxInner) {
        wrapped.push(piece)
        piece = ch
      } else {
        piece = probe
      }
    }
    if (piece) wrapped.push(piece)
  }
  for (const paragraph of text.split('\n')) {
    const words = paragraph.split(/(\s+)/).filter((part) => part.length > 0)
    let line = ''
    for (const word of words) {
      const probe = line + word
      if (line && ctx.measureText(probe).width > maxInner) {
        pushWrapped(line.trimEnd())
        line = word.trimStart() === '' ? '' : word
      } else {
        line = probe
      }
    }
    if (line) pushWrapped(line.trimEnd())
    else if (paragraph === '' && text.includes('\n')) wrapped.push('')
  }
  const clipped = wrapped.length > 4
  const lines = clipped ? wrapped.slice(-4) : wrapped
  if (clipped && lines[0]) lines[0] = `…${lines[0]}`
  if (lines.length === 0 || (lines.length === 1 && !lines[0])) return null

  const layout = {
    lines,
    w: Math.min(
      maxWidth,
      Math.max(...lines.map((l) => ctx.measureText(l).width)) + pad * 2,
    ),
    h: lines.length * lineH + pad * 2,
  }
  bubbleLayouts.set(key, layout)
  // A streaming reply mints a key per token; only the newest few are live.
  if (bubbleLayouts.size > 16) {
    const oldest = bubbleLayouts.keys().next().value
    if (oldest !== undefined) bubbleLayouts.delete(oldest)
  }
  return layout
}

/** Pixel-art speech bubble drawn in canvas space. Returns its bounds. */
export function drawBubble(
  ctx: CanvasRenderingContext2D,
  text: string,
  anchorX: number,
  anchorY: number,
  maxWidth: number,
  scale: number,
): BubbleRect | null {
  const pad = 10 * scale
  const lineH = 17 * scale
  const font = `${Math.round(13 * scale)}px "DM Sans", system-ui, sans-serif`
  ctx.save()
  ctx.font = font
  ctx.textBaseline = 'top'

  const layout = layoutBubble(ctx, text, maxWidth, scale)
  if (!layout) {
    ctx.restore()
    return null
  }
  const { lines, w, h } = layout
  // canvas.width is the bitmap size in device pixels, while every coordinate
  // here is CSS pixels — convert before clamping or a hidpi display lets the
  // bubble slide off the right edge of the screen.
  const dpr = ctx.getTransform().a || 1
  const viewW = ctx.canvas.width / dpr
  const x = clamp(anchorX - w / 2, 12, viewW - w - 12)
  // Zoomed in at the card table his head sits high in the frame, and a bubble
  // placed above it would sit off the top of the window. Overlapping him is
  // the lesser evil: an unreadable line is the same as no line.
  const y = Math.max(8, anchorY - h - 14 * scale)
  const step = Math.max(2, Math.round(3 * scale))

  // Blocky border: a stepped rectangle instead of rounded corners.
  ctx.fillStyle = 'rgba(18, 14, 12, 0.94)'
  ctx.fillRect(x + step, y, w - step * 2, h)
  ctx.fillRect(x, y + step, w, h - step * 2)

  ctx.fillStyle = CLAWD.shell
  ctx.fillRect(x + step, y, w - step * 2, step)
  ctx.fillRect(x + step, y + h - step, w - step * 2, step)
  ctx.fillRect(x, y + step, step, h - step * 2)
  ctx.fillRect(x + w - step, y + step, step, h - step * 2)

  // Tail.
  const tailX = clamp(anchorX, x + step * 4, x + w - step * 5)
  ctx.fillStyle = 'rgba(18, 14, 12, 0.94)'
  ctx.fillRect(tailX, y + h, step * 3, step)
  ctx.fillRect(tailX + step, y + h + step, step * 2, step)
  ctx.fillStyle = CLAWD.shell
  ctx.fillRect(tailX + step * 2, y + h + step, step, step)
  ctx.fillRect(tailX + step * 2, y + h + step * 2, step, step)

  ctx.fillStyle = '#F2EFE9'
  lines.forEach((l, i) => ctx.fillText(l, x + pad, y + pad + i * lineH))
  ctx.restore()
  // Include the stepped tail in the hit box.
  return { x, y, w, h: h + step * 3 }
}

export { clamp01 }
