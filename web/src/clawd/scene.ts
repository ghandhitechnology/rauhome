/**
 * The stage: owns the canvas, the camera, and the back-to-front draw order.
 *
 * The room is authored in a fixed 160 x 90 unit space and letterboxed into
 * whatever canvas it is given, so the composition survives any window size.
 */

import { clamp, clamp01, damp } from './easing'
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
import { clawdBounds, drawClawd } from './sprite'

export type Camera = {
  /** Stage-unit offset applied to everything. */
  x: number
  y: number
  zoom: number
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
}

export class Scene {
  readonly camera: Camera = { x: 0, y: 0, zoom: 1 }
  private grainSeed = 0
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
    const followX = opts.follow ? clamp((worldX - STAGE.w / 2) * 0.22, -18, 18) : 0
    this.camera.x = damp(this.camera.x, followX + par.x * 2.2, 2.4, dt)
    this.camera.y = damp(this.camera.y, par.y * 1.4, 2.4, dt)
    this.camera.zoom = damp(this.camera.zoom, opts.follow ? 1.14 : 1, 2, dt)
    this.grainSeed = (this.grainSeed + dt * 24) % 1000
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
    drawClawd(ctx, params, {
      unit: charUnit,
      x: worldX * u,
      y: FLOOR_Y * u,
      light: light?.tint,
      lightAmount: light?.tintAmount,
      rim: light?.rim,
      rimAmount: light?.rimAmount,
    })

    // Whatever he is holding rides in front of him, so it reads as carried
    // rather than as something moving alongside him.
    if (showRoom) drawCarriedProp(ctx, u, room.time, { x: worldX, y: FLOOR_Y })

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

    if (showRoom) this.drawGrain(ctx)
  }

  /** Where the sprite lands on screen, for speech bubbles and hit testing. */
  screenRect(params: ParamSet, worldX: number, charScale = 1) {
    const u = this.unit
    const cz = this.camera.zoom
    const cx = STAGE.w * u * 0.5
    const cy = STAGE.h * u * 0.5

    const project = (px: number, py: number) => ({
      x: this.offsetX + cx + (px - cx - this.camera.x * u) * cz,
      y: this.offsetY + cy + (py - cy - this.camera.y * u) * cz,
    })

    const b = clawdBounds(params, {
      unit: u * 1.25 * charScale,
      x: worldX * u,
      y: FLOOR_Y * u,
    })
    const tl = project(b.x, b.y)
    const br = project(b.x + b.w, b.y + b.h)
    return { x: tl.x, y: tl.y, w: br.x - tl.x, h: br.y - tl.y }
  }

  /** Subtle film grain, redrawn as sparse dots rather than per-pixel noise. */
  private drawGrain(ctx: CanvasRenderingContext2D) {
    const w = ctx.canvas.width
    const h = ctx.canvas.height
    ctx.save()
    ctx.globalAlpha = 0.028
    ctx.fillStyle = '#FFFFFF'
    const count = Math.min(900, Math.floor((w * h) / 5200))
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

  // Wrap.
  const words = text.split(/\s+/)
  const lines: string[] = []
  let line = ''
  for (const word of words) {
    const probe = line ? `${line} ${word}` : word
    if (ctx.measureText(probe).width > maxWidth - pad * 2 && line) {
      lines.push(line)
      line = word
    } else {
      line = probe
    }
    if (lines.length >= 4) break
  }
  if (line && lines.length < 4) lines.push(line)
  if (lines.length === 0) {
    ctx.restore()
    return null
  }

  const w = Math.min(
    maxWidth,
    Math.max(...lines.map((l) => ctx.measureText(l).width)) + pad * 2,
  )
  const h = lines.length * lineH + pad * 2
  const x = clamp(anchorX - w / 2, 12, ctx.canvas.width - w - 12)
  const y = anchorY - h - 14 * scale
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
