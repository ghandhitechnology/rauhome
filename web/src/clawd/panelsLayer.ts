/**
 * Panels drawn on the wall of the room.
 *
 * These are representations, not the documents. The real thing is HTML written
 * by the model and it is only ever mounted in a sandboxed frame, on demand,
 * when someone opens it — see `components/PanelViewer.tsx`. Keeping a live
 * frame per panel here would cost a document, a script context and a composite
 * layer each, permanently, for something the size of a postcard.
 *
 * So the wall gets a hand-drawn stand-in: a frame, a title, and a suggestion of
 * content in the right shape for what kind of panel it is.
 */

import { mixHex, ROOM } from './palette'
import { panelStore, type PanelSummary } from '../panels'
import { hash2 } from './texture'

type Ctx = CanvasRenderingContext2D

/** Where the newest panels hang, in stage units. Newest is leftmost/largest. */
const SLOTS = [
  // The prime spot on this wall, which the decorative poster gives up as soon
  // as there is something real to hang there.
  { x: 76, y: 12, w: 15, h: 21 },
  // The gap between the curtain and the poster takes the older two.
  { x: 63, y: 12, w: 11.5, h: 10 },
  { x: 63, y: 23.5, w: 11.5, h: 10 },
]

/** True when a panel is occupying the poster's hook. */
export function panelsOwnPosterSlot(): boolean {
  return panelStore.list().length > 0
}

function r(ctx: Ctx, u: number, x: number, y: number, w: number, h: number, fill: string) {
  ctx.fillStyle = fill
  ctx.fillRect(x * u, y * u, w * u, h * u)
}

/** A few bars, a chart, or lines of prose — whichever the kind implies. */
function drawContents(
  ctx: Ctx,
  u: number,
  panel: PanelSummary,
  x: number,
  y: number,
  w: number,
  h: number,
) {
  const seed = panel.panel_id.length + panel.title.length
  const ink = mixHex(ROOM.paper, ROOM.wall, 0.45)

  if (panel.kind === 'dashboard') {
    // A row of columns of differing height.
    const bars = 6
    const bw = w / (bars + 2)
    for (let i = 0; i < bars; i++) {
      const value = 0.25 + hash2(i, seed, 3) * 0.7
      const bh = (h - 2) * value
      r(ctx, u, x + bw * (i + 1), y + h - 1 - bh, bw * 0.66, bh, i % 2 ? ROOM.screenGlow : ink)
    }
    r(ctx, u, x + bw * 0.6, y + h - 1, w - bw * 1.2, 0.3, ink)
    return
  }

  if (panel.kind === 'poster') {
    // One bold shape, centred.
    const cx = x + w / 2
    const cy = y + h * 0.42
    const size = Math.min(w, h) * 0.34
    ctx.fillStyle = ROOM.screenGlow
    ctx.beginPath()
    ctx.ellipse(cx * u, cy * u, size * u, size * u, 0, 0, Math.PI * 2)
    ctx.fill()
    r(ctx, u, x + w * 0.18, y + h * 0.74, w * 0.64, 0.5, ink)
    r(ctx, u, x + w * 0.28, y + h * 0.84, w * 0.44, 0.4, mixHex(ink, ROOM.wall, 0.4))
    return
  }

  // Report / note: ragged lines of text.
  const lines = Math.max(3, Math.floor(h / 2.2))
  for (let i = 0; i < lines; i++) {
    const lw = w * (0.45 + hash2(i, seed, 7) * 0.48)
    r(ctx, u, x + w * 0.1, y + 1.4 + i * 2, lw, 0.45, i === 0 ? ROOM.screenGlow : ink)
  }
}

export type PlacedPanel = {
  panel: PanelSummary
  x: number
  y: number
  w: number
  h: number
}

/**
 * Where the panels hang, in stage units — without drawing anything.
 *
 * Layout is a pure function of the panel list, which is why hit-testing reads
 * it from here rather than from `drawWallPanels`' return value: the wall is
 * painted into the baked backdrop, so that draw may not have run this frame,
 * or this second.
 */
export function wallPanelRects(): PlacedPanel[] {
  return panelStore
    .list()
    .slice(0, SLOTS.length)
    .map((panel, i) => ({ panel, ...SLOTS[i] }))
}

/**
 * Draw the wall. Returns the stage-unit rects it used, newest first.
 */
export function drawWallPanels(
  ctx: Ctx,
  u: number,
): PlacedPanel[] {
  const placed = wallPanelRects()
  if (!placed.length) return []

  placed.forEach(({ panel, x, y, w, h }) => {

    // Drop shadow, so it hangs off the wall rather than being painted on it.
    ctx.save()
    ctx.globalAlpha = 0.45
    ctx.fillStyle = '#000000'
    ctx.fillRect((x + 0.9) * u, (y + 1.2) * u, w * u, h * u)
    ctx.restore()

    // Frame, mount, then the stand-in contents.
    r(ctx, u, x - 0.8, y - 0.8, w + 1.6, h + 1.6, '#1A1512')
    r(ctx, u, x - 0.8, y - 0.8, w + 1.6, 0.4, '#3A2E26')
    r(ctx, u, x, y, w, h, mixHex(ROOM.paper, ROOM.wall, 0.66))

    const padX = w * 0.1
    const bodyY = y + 3.2
    const bodyH = h - 4.6
    drawContents(ctx, u, panel, x + padX, bodyY, w - padX * 2, bodyH)

    // Title bar along the top of the mount.
    r(ctx, u, x, y, w, 2.4, mixHex(ROOM.wall, '#000000', 0.25))
    const fontPx = Math.max(7, Math.round(1.5 * u))
    ctx.save()
    ctx.font = `${fontPx}px "DM Sans", system-ui, sans-serif`
    ctx.fillStyle = '#EDE6DC'
    ctx.textBaseline = 'middle'
    const maxW = (w - 1.6) * u
    let label = panel.title
    while (label.length > 4 && ctx.measureText(label).width > maxW) {
      label = label.slice(0, -2)
    }
    if (label !== panel.title) label = `${label}…`
    ctx.fillText(label, (x + 0.8) * u, (y + 1.2) * u)
    ctx.restore()

    // A faint sheen so it reads as glazed like the poster beside it.
    ctx.save()
    ctx.globalAlpha = 0.03
    ctx.fillStyle = '#DFF0FF'
    ctx.beginPath()
    ctx.moveTo(x * u, (y + h) * u)
    ctx.lineTo((x + w * 0.5) * u, y * u)
    ctx.lineTo((x + w * 0.78) * u, y * u)
    ctx.lineTo((x + w * 0.28) * u, (y + h) * u)
    ctx.closePath()
    ctx.fill()
    ctx.restore()
  })
  return placed
}

/**
 * Everything `drawWallPanels` depends on, as a cache key.
 *
 * The title is in here because it is rendered as text: `replaceAll` can change
 * a title under an existing id on reconnect, and keying on the id alone would
 * leave the old words on the wall.
 */
export function wallPanelsKey(): string {
  return panelStore
    .list()
    .map((panel) => `${panel.panel_id}:${panel.kind}:${panel.title}`)
    .join(',')
}
