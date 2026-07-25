/**
 * Surface texture for the room.
 *
 * Everything here exists to answer one question: why does a flat fill read as
 * paint on a wall rather than as a coloured rectangle? Because real surfaces
 * are never uniform — plaster mottles, wood runs in grain, fabric weaves, and
 * floorboards each took their own stain. This module manufactures that
 * unevenness.
 *
 * It is all built once into offscreen tiles and blitted as repeating patterns.
 * Generating noise per frame at 1920x1080 would cost more than the entire rest
 * of the scene put together, and none of it changes between frames anyway —
 * only the light falling on it does.
 */

/** Deterministic hash → 0..1. The same coordinate always gives the same value. */
export function hash2(x: number, y: number, seed = 0): number {
  const n = Math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453123
  return n - Math.floor(n)
}

/** Smoothed value noise, 0..1. */
export function valueNoise(x: number, y: number, seed = 0): number {
  const xi = Math.floor(x)
  const yi = Math.floor(y)
  const xf = x - xi
  const yf = y - yi
  // Smoothstep the interpolant so cells blend instead of showing their grid.
  const u = xf * xf * (3 - 2 * xf)
  const v = yf * yf * (3 - 2 * yf)
  const a = hash2(xi, yi, seed)
  const b = hash2(xi + 1, yi, seed)
  const c = hash2(xi, yi + 1, seed)
  const d = hash2(xi + 1, yi + 1, seed)
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v
}

/** Layered value noise. Coarse shapes with fine detail on top. */
export function fbm(x: number, y: number, octaves = 4, seed = 0): number {
  let sum = 0
  let amp = 0.5
  let total = 0
  let fx = x
  let fy = y
  for (let i = 0; i < octaves; i++) {
    sum += valueNoise(fx, fy, seed + i * 17) * amp
    total += amp
    amp *= 0.5
    fx *= 2.03
    fy *= 2.01
  }
  return sum / total
}

type Tile = HTMLCanvasElement | null

function makeTile(w: number, h: number): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } | null {
  // Tests and any non-browser host get null and simply render untextured.
  if (typeof document === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(w))
  canvas.height = Math.max(1, Math.round(h))
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  return { canvas, ctx }
}

/**
 * Per-pixel tile painter.
 *
 * `shade` returns `[luminance -1..1, alpha 0..1]` — signed, so one pass can
 * both darken and lighten and the result composites over any base colour.
 */
function paintTile(
  w: number,
  h: number,
  shade: (x: number, y: number) => [number, number],
): Tile {
  const made = makeTile(w, h)
  if (!made) return null
  const { canvas, ctx } = made
  const image = ctx.createImageData(canvas.width, canvas.height)
  const data = image.data
  for (let y = 0; y < canvas.height; y++) {
    for (let x = 0; x < canvas.width; x++) {
      const [lum, alpha] = shade(x, y)
      const i = (y * canvas.width + x) * 4
      const value = lum >= 0 ? 255 : 0
      data[i] = value
      data[i + 1] = value
      data[i + 2] = value
      data[i + 3] = Math.round(Math.min(1, Math.max(0, Math.abs(lum) * alpha)) * 255)
    }
  }
  ctx.putImageData(image, 0, 0)
  return canvas
}

// ── the tiles ─────────────────────────────────────────────────────────

/**
 * Plaster: broad mottling with a fine tooth over it.
 *
 * Painted walls are not one colour — the roller left long soft variations and
 * the plaster under it has its own tooth. Without this the wall is the single
 * biggest flat area on screen and reads as a backdrop.
 */
function plasterTile(size: number): Tile {
  return paintTile(size, size, (x, y) => {
    const broad = fbm(x / (size * 0.42), y / (size * 0.42), 3, 11) - 0.5
    // The tooth is deliberately faint: at full strength it stops reading as
    // plaster and starts reading as sensor noise over the whole frame.
    const tooth = hash2(x, y, 3) - 0.5
    return [broad * 1.7 + tooth * 0.22, 0.46]
  })
}

/**
 * Wood: long grain running one way, with occasional darker cathedral figure.
 * Drawn horizontally; callers rotate it for a vertical member.
 */
function woodTile(w: number, h: number): Tile {
  return paintTile(w, h, (x, y) => {
    // Stretched noise: 20x along the grain, so streaks run rather than blotch.
    const grain = fbm(x / (w * 0.5), y * 1.7, 3, 5)
    const rings = Math.sin(grain * 15 + y * 0.7) * 0.5 + 0.5
    const fine = hash2(x, y * 3, 9) - 0.5
    return [(rings - 0.55) * 1.25 + fine * 0.3, 0.42]
  })
}

/** Fabric: a visible over-under weave plus slub irregularity. */
function weaveTile(size: number): Tile {
  return paintTile(size, size, (x, y) => {
    const warp = (x % 4 < 2 ? 1 : -1) * 0.5
    const weft = (y % 4 < 2 ? 1 : -1) * 0.5
    const slub = fbm(x / 5, y / 5, 2, 23) - 0.5
    return [warp * weft * 1.4 + slub * 0.9, 0.34]
  })
}

/** Paper/card: a soft tooth, nothing directional. */
function paperTile(size: number): Tile {
  return paintTile(size, size, (x, y) => {
    const tooth = fbm(x / 3, y / 3, 2, 41) - 0.5
    return [tooth * 1.2, 0.3]
  })
}

/** Metal: fine brushed striations along x. */
function metalTile(w: number, h: number): Tile {
  return paintTile(w, h, (x, y) => {
    const brushed = hash2(Math.floor(x / 2), y * 7, 31) - 0.5
    const sweep = fbm(x / (w * 0.6), y / 3, 2, 51) - 0.5
    return [brushed * 0.8 + sweep * 0.9, 0.3]
  })
}

// ── cache ─────────────────────────────────────────────────────────────

export type TextureKind = 'plaster' | 'wood' | 'weave' | 'paper' | 'metal'

type Cache = {
  unit: number
  tiles: Partial<Record<TextureKind, Tile>>
  /**
   * Built patterns, kept alongside the tiles they wrap.
   *
   * `createPattern` is not free, and `textureRect` runs a dozen times a frame:
   * rebuilding the same handful of patterns sixty times a second is pure waste
   * when neither the tile nor the context has changed underneath them.
   */
  patterns: Partial<Record<TextureKind, CanvasPattern | null>>
  ctx: CanvasRenderingContext2D | null
}

let cache: Cache = { unit: -1, tiles: {}, patterns: {}, ctx: null }

/**
 * Texture tiles sized for the current zoom.
 *
 * Tiles are built in canvas pixels, so a resize has to rebuild them or the
 * grain would visibly stretch. Rebuilds are keyed on a quantised unit: a
 * one-pixel window drag must not repaint every tile in the room.
 */
function tile(kind: TextureKind, unit: number): Tile {
  const key = Math.max(1, Math.round(unit * 4) / 4)
  if (cache.unit !== key) cache = { unit: key, tiles: {}, patterns: {}, ctx: null }
  if (kind in cache.tiles) return cache.tiles[kind] ?? null

  // Tiles are sized in stage units so the grain keeps a constant physical
  // scale: wood grain must not get coarser because the window got bigger.
  const px = (units: number) => Math.max(2, Math.round(units * key))
  let built: Tile = null
  switch (kind) {
    case 'plaster':
      built = plasterTile(px(24))
      break
    case 'wood':
      built = woodTile(px(20), px(5))
      break
    case 'weave':
      built = weaveTile(px(3))
      break
    case 'paper':
      built = paperTile(px(6))
      break
    case 'metal':
      built = metalTile(px(8), px(4))
      break
  }
  cache.tiles[kind] = built
  return built
}

/**
 * Lay a texture over the rect just filled.
 *
 * `alpha` is deliberately low everywhere it is used: texture should be
 * something you notice only when it is removed.
 */
export function textureRect(
  ctx: CanvasRenderingContext2D,
  kind: TextureKind,
  unit: number,
  x: number,
  y: number,
  w: number,
  h: number,
  alpha = 0.5,
  rotate = false,
) {
  if (w <= 0 || h <= 0) return
  const source = tile(kind, unit)
  if (!source) return
  // A pattern belongs to the context that made it, so a changed context
  // invalidates the lot rather than silently painting from the wrong canvas.
  if (cache.ctx !== ctx) {
    cache.ctx = ctx
    cache.patterns = {}
  }
  let pattern = cache.patterns[kind]
  if (pattern === undefined) {
    pattern = ctx.createPattern(source, 'repeat')
    cache.patterns[kind] = pattern
  }
  if (!pattern) return

  ctx.save()
  ctx.globalAlpha = alpha
  ctx.beginPath()
  ctx.rect(x * unit, y * unit, w * unit, h * unit)
  ctx.clip()
  if (rotate) {
    // Rotating the pattern rather than the tile keeps one cached bitmap
    // serving both a table top and its legs.
    ctx.translate(x * unit, y * unit)
    ctx.rotate(Math.PI / 2)
    ctx.fillStyle = pattern
    ctx.fillRect(0, -(w * unit), h * unit, w * unit)
  } else {
    ctx.fillStyle = pattern
    ctx.fillRect(x * unit, y * unit, w * unit, h * unit)
  }
  ctx.restore()
}

/** Drop the cache. Only needed if a host swaps the canvas out from under us. */
export function resetTextures() {
  cache = { unit: -1, tiles: {}, patterns: {}, ctx: null }
}
