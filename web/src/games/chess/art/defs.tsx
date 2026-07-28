/* oxlint-disable react/only-export-components -- SVG definitions and their shared geometry form one piece set */
/* ─────────────────────────────────────────────────────────────
   Chess — the blank, the lathe and the light

   Six pieces, two finishes, thirty-two of them standing on a board
   at once. Everything that has to be identical across all of that
   lives here, because the failure mode of a hand-drawn chess set is
   not that any one piece is bad — it is that the queen was drawn on
   a Tuesday and the king on a Thursday and they no longer look like
   they came out of the same box.

   Three things are shared, and they map onto how a real set is made.

   **The blank.** A Staunton piece is a surface of revolution: a
   profile held against a spinning cylinder of wood. `revolve()` takes
   that profile — half-widths up the axis — and gives back the closed
   silhouette, mirrored exactly, because a lathe is exact. Every piece
   also starts from the same `foot()`, so the six bases are the same
   turning at six diameters rather than six different guesses at what
   a base looks like.

   **The finish.** Two woods cut from the room's own palette. They are
   not selected per piece: the children of a piece never name a colour.
   They name a *role* — `cw-body`, `cw-lit`, `cw-shade` — and the
   `<svg>` root carries `data-chess-finish`, which the stylesheet in
   here turns into custom properties. One set of drawings, two sets of
   wood, and no piece file that has to be written twice.

   **The light.** The room's desk lamp sits at stage x≈119; the game
   table is at x=72. The lamp is therefore up and to the *right* of
   every piece on the board, which is why `cw-turn` darkens the left
   flank and `cw-lacquer` puts its specular at 72% of the way across.
   Get this backwards and thirty-two pieces are lit from a window that
   is on the wrong wall.

   One more number that comes from outside: `chessTableLayer.ts` draws
   a square 3.45 stage units wide and 0.58 deep, so the board is seen
   at roughly six to one. `SQUASH` is 0.18 for that reason. Every ring,
   every base, every crenellation is an ellipse at that ratio, and a
   rounder one would read as a different camera than the board's.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement, ReactNode } from 'react'
import { CLAWD, mixHex, ROOM } from '../../../clawd/palette'

/** The two finishes. One side of the set is cut from each. */
export type Finish = 'maple' | 'walnut'

/** Author space. Every piece draws into this box, base down. */
export const VIEW = { w: 120, h: 200 } as const

/** The turning axis. Everything symmetric is symmetric about this. */
export const CX = 60

/**
 * The lowest pixel of a piece's footprint.
 *
 * Not the centre of the base disc — the *front* of it. At this camera the
 * base is a disc seen almost edge-on, so its near rim hangs below its axis
 * by `rx · SQUASH`, and if `FLOOR` meant the axis then a king (base 29) would
 * belly four pixels past the bottom of the viewBox and a pawn would not.
 * Measuring from the front instead makes every piece's contact line land on
 * the same y no matter how wide its base is, which is the whole point of
 * having one.
 */
export const FLOOR = 196

/** Ellipse ry ÷ rx, everywhere. Set by the board's own 6:1 squash. */
export const SQUASH = 0.18

/** Where a base of half-width `w` puts its axis, given `FLOOR`. */
export function footY(w: number): number {
  return FLOOR - w * SQUASH
}

/* ── the two woods ─────────────────────────────────────────────
   Mixed out of `clawd/palette` rather than picked, so that when the
   room's browns move the set moves with them. The two constraints
   that fix the mixes are both about not disappearing: the board's
   light squares are `mix(woodLit, paper, 0.45)` and its dark squares
   are `ROOM.walnut`, so maple has to sit clearly *above* the light
   squares and walnut clearly *below* the dark ones. A set that is the
   same value as the board it stands on is a set nobody can play on. */

type Tones = {
  /** The finished surface, in full light. */
  body: string
  /** The lacquer catching the lamp, and any face turned straight at it. */
  lit: string
  /** The flank turned away. */
  shade: string
  /** Undercuts, hollows, the inside of a crenel. */
  deep: string
  /** Wood exposed by a chip — never sealed, so always paler and drier. */
  raw: string
  /** The darker rings in the grain pattern. */
  grain: string
  /** The pale figure that runs with them. */
  figure: string
  /** Incised lines and the piece's own contour. */
  line: string
}

const MAPLE: Tones = {
  body: mixHex(ROOM.woodLit, ROOM.paper, 0.66),
  lit: mixHex(ROOM.paper, ROOM.dust, 0.55),
  shade: mixHex(ROOM.wood, ROOM.paper, 0.4),
  deep: mixHex(ROOM.wood, ROOM.paper, 0.1),
  raw: mixHex(ROOM.paper, ROOM.dust, 0.28),
  grain: mixHex(ROOM.wood, ROOM.paper, 0.3),
  figure: mixHex(ROOM.paper, ROOM.dust, 0.42),
  line: mixHex(ROOM.woodDeep, ROOM.wood, 0.32),
}

const WALNUT: Tones = {
  body: mixHex(ROOM.walnut, ROOM.woodDeep, 0.52),
  lit: mixHex(ROOM.walnutLit, ROOM.brassLit, 0.34),
  shade: mixHex(ROOM.woodDeep, CLAWD.ink, 0.5),
  deep: mixHex(CLAWD.ink, ROOM.woodDeep, 0.18),
  raw: mixHex(ROOM.walnutLit, ROOM.paper, 0.38),
  grain: mixHex(ROOM.walnut, CLAWD.ink, 0.66),
  figure: mixHex(ROOM.walnutLit, ROOM.brass, 0.3),
  line: mixHex(CLAWD.ink, ROOM.woodDeep, 0.1),
}

/* Baize is baize. A set has one felt, not two, and it is the same green
   under both colours — which is also why it is the only thing in here
   that does not live behind a custom property. */
const FELT = {
  body: mixHex(ROOM.leafDeep, CLAWD.ink, 0.42),
  lit: mixHex(ROOM.leaf, ROOM.leafDeep, 0.4),
  deep: mixHex(ROOM.leafDeep, CLAWD.ink, 0.72),
}

/* Shadow and highlight are *warm*, and this is not decoration.
   Neutral black over pale maple gives grey, and grey is what makes CG wood
   look like CG plastic — the base of every piece in the first pass read as
   painted metal for exactly this reason. The room is lit by a tungsten desk
   lamp, so its shadows carry the wall's brown and its speculars carry the
   lamp's amber. Both come out of the room palette rather than being picked. */
const SHADOW = mixHex(ROOM.woodDeep, CLAWD.ink, 0.55)
const SPECULAR = ROOM.dust

/* ── the stylesheet ───────────────────────────────────────────
   Two rules' worth of custom properties and a dozen one-line classes.
   This is what lets `pawn.tsx` be a drawing rather than a drawing plus
   a colour scheme: nothing under `pieces/` ever names a hex, and the
   only thing that knows which wood it is, is the <svg> root. */

function toneVars(finish: Finish, t: Tones): string {
  return (
    `svg[data-chess-finish="${finish}"]{` +
    `--cw-body:${t.body};--cw-lit:${t.lit};--cw-shade:${t.shade};` +
    `--cw-deep:${t.deep};--cw-raw:${t.raw};--cw-grain:url(#cw-grain-${finish});` +
    `--cw-figure:${t.figure};--cw-line:${t.line}}`
  )
}

const SHEET = [
  `svg[data-chess-finish]{--cw-felt:${FELT.body};--cw-felt-lit:${FELT.lit}}`,
  toneVars('maple', MAPLE),
  toneVars('walnut', WALNUT),
  '.cw-body{fill:var(--cw-body)}',
  '.cw-lit{fill:var(--cw-lit)}',
  '.cw-shade{fill:var(--cw-shade)}',
  '.cw-deep{fill:var(--cw-deep)}',
  '.cw-raw{fill:var(--cw-raw)}',
  '.cw-line{fill:var(--cw-line)}',
  '.cw-grain{fill:var(--cw-grain)}',
  '.cw-felt{fill:var(--cw-felt)}',
  '.cw-felt-lit{fill:var(--cw-felt-lit)}',
  '.cw-k-lit{stroke:var(--cw-lit);fill:none}',
  '.cw-k-shade{stroke:var(--cw-shade);fill:none}',
  '.cw-k-deep{stroke:var(--cw-deep);fill:none}',
  '.cw-k-line{stroke:var(--cw-line);fill:none}',
  '.cw-k-raw{stroke:var(--cw-raw);fill:none}',
  '.cw-k-figure{stroke:var(--cw-figure);fill:none}',
].join('\n')

/* ── the lathe ─────────────────────────────────────────────────
   A profile is a list of stations read bottom to top, each giving the
   half-width `dx` of the turning at height `y`. Segments arrive at a
   station either straight, as a cubic (`c`, control points in the same
   half-width frame), or as a circular arc (`r`, positive for a convex
   bulge and negative for a cove).

   `revolve` walks that up the lit side, mirrors it, and walks it back
   down the shaded side. The mirroring is what makes it worth having:
   a lathe cannot produce an asymmetric turning, so neither can this,
   and the character has to come from the profile rather than from a
   wobble that would read as a mistake. Reversal and reflection each
   flip an arc's sweep flag, so doing both leaves it alone — which is
   why the return leg copies the flag straight across.

   The path never closes with a straight line along the bottom. It
   closes with the near half of the footprint ellipse, because that is
   what the base of a cylinder looks like from a chair. */

export type Station = {
  dx: number
  y: number
  /** Cubic controls for the segment arriving here: `[dx1, y1, dx2, y2]`. */
  c?: readonly [number, number, number, number]
  /** Circular arc for the segment arriving here. Positive bulges outward. */
  r?: number
}

const n2 = (v: number) => Number(v.toFixed(2))

export function revolve(profile: readonly Station[], squash: number = SQUASH): string {
  const base = profile[0]
  const last = profile[profile.length - 1]
  const at = (dx: number, y: number) => `${n2(CX + dx)} ${n2(y)}`
  const out: string[] = [`M${at(base.dx, base.y)}`]

  for (let i = 1; i < profile.length; i++) {
    const p = profile[i]
    if (p.c) out.push(`C${at(p.c[0], p.c[1])} ${at(p.c[2], p.c[3])} ${at(p.dx, p.y)}`)
    else if (p.r) out.push(`A${n2(Math.abs(p.r))} ${n2(Math.abs(p.r))} 0 0 ${p.r > 0 ? 0 : 1} ${at(p.dx, p.y)}`)
    else out.push(`L${at(p.dx, p.y)}`)
  }

  // A profile that stops short of the axis is a flat top — a cut-off rim
  // waiting for crenellations or a coronet to be built on it.
  if (Math.abs(last.dx) > 0.001) out.push(`L${at(-last.dx, last.y)}`)

  for (let i = profile.length - 1; i > 0; i--) {
    const p = profile[i]
    const q = profile[i - 1]
    if (p.c) out.push(`C${at(-p.c[2], p.c[3])} ${at(-p.c[0], p.c[1])} ${at(-q.dx, q.y)}`)
    else if (p.r) out.push(`A${n2(Math.abs(p.r))} ${n2(Math.abs(p.r))} 0 0 ${p.r > 0 ? 0 : 1} ${at(-q.dx, q.y)}`)
    else out.push(`L${at(-q.dx, q.y)}`)
  }

  out.push(`A${n2(base.dx)} ${n2(base.dx * squash)} 0 0 0 ${at(base.dx, base.y)}`, 'Z')
  return out.join(' ')
}

/**
 * The six stations every piece stands on, scaled to its base half-width.
 *
 * Disc face, top arris, cove, bead, and the neck the shaft rises out of.
 * Sharing this is not laziness — it is the single strongest signal that the
 * six pieces are one set. Turners cut the base of every piece in a set with
 * the same tool at the same angle; only the diameter changes.
 */
export function foot(w: number): Station[] {
  const y = footY(w)
  return [
    { dx: w, y },
    { dx: w * 0.972, y: y - 4.6 },
    { dx: w * 0.876, y: y - 6.6, c: [w * 0.968, y - 5.8, w * 0.92, y - 6.4] },
    { dx: w * 0.575, y: y - 12.6, c: [w * 0.78, y - 8.6, w * 0.6, y - 10.2] },
    { dx: w * 0.66, y: y - 15.4, c: [w * 0.6, y - 13.6, w * 0.655, y - 14.5] },
    { dx: w * 0.5, y: y - 18.4, c: [w * 0.665, y - 16.4, w * 0.575, y - 17.8] },
  ]
}

/**
 * A turned band — the side wall of a ring, collar or drum.
 *
 * Opaque cylinder seen from slightly above: you see the whole of the top
 * ellipse but only the near half of the bottom one, so the top edge bulges
 * up and the bottom edge bulges down. Drawn with a straight top the ring
 * reads as a sticker rather than as a thing with a diameter.
 */
export function drum(rx: number, top: number, bot: number, squash: number = SQUASH): string {
  const ry = n2(rx * squash)
  return (
    `M${n2(CX - rx)} ${n2(top)} A${n2(rx)} ${ry} 0 0 1 ${n2(CX + rx)} ${n2(top)} ` +
    `L${n2(CX + rx)} ${n2(bot)} A${n2(rx)} ${ry} 0 0 1 ${n2(CX - rx)} ${n2(bot)} Z`
  )
}

/**
 * The y of a rim at horizontal offset `u`, on the near or far side.
 *
 * The one piece of arithmetic the rook's crenellations, the queen's coronet
 * and the king's crown band all need: things standing on a circular rim do
 * not stand on a straight line. Four merlons whose feet are level is the
 * single fastest way to make a round tower look like a flat cut-out.
 */
export function rimY(u: number, rx: number, y: number, near: boolean): number {
  const t = Math.max(0, 1 - (u / rx) ** 2)
  return y + (near ? 1 : -1) * rx * SQUASH * Math.sqrt(t)
}

/** A sampled run along a rim, from `u0` to `u1`, as `L` commands. */
export function rimRun(
  u0: number,
  u1: number,
  rx: number,
  y: number,
  near: boolean,
  steps = 5,
): string {
  const out: string[] = []
  for (let i = 0; i <= steps; i++) {
    const u = u0 + ((u1 - u0) * i) / steps
    out.push(`L${n2(CX + u)} ${n2(rimY(u, rx, y, near))}`)
  }
  return out.join(' ')
}

/* ── the finished surface ──────────────────────────────────────
   Anything closed and made of wood gets `<Wood/>`: flat body colour,
   the grain field, the turning gradient, the sky term and the lacquer.
   Five stacked fills rather than one, because a single flat brown is
   exactly what makes vector wood look like vector wood. Gradients are
   in objectBoundingBox units, so a merlon seven units wide gets the
   same lighting *shape* as a king a hundred and eighty tall. */

export function Wood({ d, grain = 0.85 }: { d: string; grain?: number }): ReactElement {
  return (
    <g>
      <path d={d} className="cw-body" />
      <path d={d} className="cw-grain" opacity={grain} />
      <path d={d} fill="url(#cw-turn)" />
      <path d={d} fill="url(#cw-sky)" />
      <path d={d} fill="url(#cw-lacquer)" />
    </g>
  )
}

/**
 * The felt and the shadow it sits in — drawn before the piece, not after.
 *
 * The baize is glued under the base, so from a chair you would expect to see
 * none of it. What you actually see is the two millimetres by which it lifts
 * the wood off the board: a dark green crescent under the near rim. Drawing
 * it as a whole disc offset down by 1.9 and then covering all but that
 * crescent with the piece is both simpler than clipping and closer to what
 * is really happening.
 */
export function Ground({ rx }: { rx: number }): ReactElement {
  const cy = footY(rx)
  return (
    <g>
      <ellipse
        cx={CX}
        cy={cy + 1.4}
        rx={rx * 1.26}
        ry={rx * SQUASH * 1.55}
        fill="url(#cw-contact)"
      />
      <ellipse cx={CX} cy={cy + 1.9} rx={rx * 0.97} ry={rx * SQUASH} className="cw-felt" />
      <ellipse cx={CX} cy={cy + 1.9} rx={rx * 0.97} ry={rx * SQUASH} fill="url(#cw-nap)" opacity={0.55} />
      <path
        d={`M${n2(CX - rx * 0.9)} ${n2(cy + 2.4)} A${n2(rx * 0.97)} ${n2(rx * SQUASH)} 0 0 0 ${n2(CX + rx * 0.9)} ${n2(cy + 2.4)}`}
        className="cw-k-lit"
        strokeWidth={0.5}
        opacity={0.13}
      />
    </g>
  )
}

/** A turning's exposed top face, and the light that pools on it. */
export function Disc({ rx, y, lit = 0.34 }: { rx: number; y: number; lit?: number }): ReactElement {
  const ry = rx * SQUASH
  return (
    <g>
      <ellipse cx={CX} cy={y} rx={rx} ry={ry} className="cw-body" />
      <ellipse cx={CX} cy={y} rx={rx} ry={ry} className="cw-grain" opacity={0.5} />
      <ellipse cx={CX} cy={y} rx={rx} ry={ry} className="cw-lit" opacity={lit} />
      <ellipse cx={CX} cy={y} rx={rx} ry={ry} fill="url(#cw-turn)" opacity={0.55} />
    </g>
  )
}

/**
 * A collar: a proud ring where the tool was held still against the blank.
 *
 * Four parts, and the fourth is the one that matters. The band, the light on
 * its top face, the lacquer down its lit flank — and then the line of shadow
 * it throws onto the shaft below it. Without that last arc the ring is a
 * painted stripe; with it the ring stands off the shaft.
 *
 * The top face is drawn as the *near lune* only — the sliver between the
 * ellipse's major axis and its near rim — and never as the whole ellipse.
 * The far half of a collar's top face is behind whatever rises out of the
 * collar, and a full ellipse here paints the ring straight over the shaft
 * it is supposed to be holding.
 *
 * `cap` is off entirely for rings a carved part is socketed into, where even
 * the near lune would land on the thing standing in them.
 */
export function Collar({
  rx,
  top,
  bot,
  cap = true,
  lit = 0.3,
}: {
  rx: number
  top: number
  bot: number
  cap?: boolean
  lit?: number
}): ReactElement {
  const ry = rx * SQUASH
  const lune = `M${n2(CX - rx)} ${n2(top)} A${n2(rx)} ${ry} 0 0 0 ${n2(CX + rx)} ${n2(top)} Z`
  return (
    <g>
      <Wood d={drum(rx, top, bot)} grain={0.5} />
      {cap ? (
        <g>
          <path d={lune} className="cw-body" />
          <path d={lune} className="cw-lit" opacity={lit} />
          <path d={lune} fill="url(#cw-turn)" opacity={0.5} />
        </g>
      ) : null}
      {/* the arris where the top face meets the flank, catching the lamp */}
      <path
        d={`M${n2(CX - rx * 0.55)} ${n2(rimY(-rx * 0.55, rx, top, true))} ${rimRun(-rx * 0.55, rx * 0.98, rx, top, true, 4)}`}
        className="cw-k-lit"
        strokeWidth={0.8}
        opacity={0.4}
      />
      {/* and the shadow the ring drops on the shaft under it */}
      <path
        d={`M${n2(CX - rx)} ${n2(bot)} A${n2(rx)} ${ry} 0 0 0 ${n2(CX + rx)} ${n2(bot)}`}
        className="cw-k-line"
        strokeWidth={1.2}
        opacity={0.42}
      />
    </g>
  )
}

/**
 * The whole standing object: ground, wood, the piece's own detail, contour.
 *
 * `d` is the complete outline and may hold several subpaths — the knight is
 * a turned stem plus a carved head and they are one fill. Children are the
 * detail, and they land between the ambient-occlusion pass and the contour,
 * which is the only ordering that lets a collar sit on top of the shaft's
 * shading while the contour still closes over everything.
 */
export function Turned({
  d,
  w,
  children,
}: {
  d: string
  w: number
  children?: ReactNode
}): ReactElement {
  return (
    <g aria-hidden="true">
      <Ground rx={w} />
      <Wood d={d} />
      <path d={d} fill="url(#cw-floor)" />
      {children}
      {/* The contour, roughened. See `cw-wear` for why this is the only
          thing in the piece that carries a filter. */}
      <path d={d} className="cw-k-line" strokeWidth={0.9} opacity={0.32} filter="url(#cw-wear)" />
    </g>
  )
}

/* ── grain ─────────────────────────────────────────────────────
   Nine near-vertical figures over a 43-wide tile. Vertical because a
   turner cuts the blank with the grain running up the axis, which is
   also why the pattern tile is the full 200 tall — it never repeats
   inside a piece, and the lines are authored to the same x at y=0 and
   y=200 so that when it does repeat there is no seam.

   The pattern is only half the story. It gives every piece the same
   field; the *character* has to come from the two or three grain arcs
   each piece draws by hand around its own swells, because grain wraps
   a turning and a flat field cannot know that. */

/* Fourteen of them, none wider than 0.8. Density is the whole point: a
   handful of wide dark lines reads as scratches in a lacquer, and no amount
   of tuning the colour fixes that — it is the *pitch* that says wood. */
const GRAIN: readonly { d: string; w: number; o: number }[] = [
  { d: 'M2.2 0C3.8 40 1.2 78 2.8 118C4 150 1.8 176 2.2 200', w: 0.42, o: 0.44 },
  { d: 'M4.6 0C6.6 42 3.4 80 5.4 120C7 152 4 178 4.6 200', w: 0.75, o: 0.5 },
  { d: 'M7.4 0C6 36 8.6 72 7 108C5.6 142 8.2 172 7.4 200', w: 0.35, o: 0.3 },
  { d: 'M10.4 0C8.6 34 11.8 70 10 104C8.4 138 11.4 172 10.4 200', w: 0.5, o: 0.36 },
  { d: 'M13.6 0C15.8 46 12.6 88 14.8 130C16.2 160 13.4 180 13.6 200', w: 0.68, o: 0.42 },
  { d: 'M16.4 0C15 40 17.4 78 16 114C14.8 146 17 174 16.4 200', w: 0.34, o: 0.26 },
  { d: 'M19.6 0C17.8 38 21.2 76 19 112C17.2 144 20.4 174 19.6 200', w: 0.55, o: 0.34 },
  { d: 'M22.8 0C24.8 44 21.8 84 23.8 124C25.2 156 22.6 178 22.8 200', w: 0.78, o: 0.46 },
  { d: 'M25.6 0C24.4 36 26.6 72 25.2 108C24 142 26.2 172 25.6 200', w: 0.32, o: 0.24 },
  { d: 'M28.8 0C27.2 38 30 76 28 112C26.4 144 29.4 174 28.8 200', w: 0.5, o: 0.32 },
  { d: 'M32 0C34 44 31 86 33 126C34.4 158 31.8 180 32 200', w: 0.7, o: 0.44 },
  { d: 'M35.2 0C34 38 36.2 74 34.8 110C33.6 144 35.8 174 35.2 200', w: 0.36, o: 0.26 },
  { d: 'M38.6 0C36.8 40 40 78 38 116C36.4 150 39.2 176 38.6 200', w: 0.58, o: 0.36 },
  { d: 'M41.2 0C42.6 42 40.2 82 41.8 122C43 154 41 178 41.2 200', w: 0.44, o: 0.3 },
]

/** The pale streaks that run with the dark ones. Fewer, softer, wider. */
const FIGURE: readonly { d: string; w: number; o: number }[] = [
  { d: 'M6.8 0C9 44 5 86 7.6 126C9.4 158 6.2 180 6.8 200', w: 2.6, o: 0.24 },
  { d: 'M18 0C20.6 40 16.4 80 19.2 120C21 152 17.4 178 18 200', w: 1.9, o: 0.18 },
  { d: 'M29.4 0C27.6 44 31.4 84 29 124C27.2 156 30 180 29.4 200', w: 2.2, o: 0.2 },
  { d: 'M39.8 0C42.2 42 38 84 40.6 124C42.4 156 39.2 180 39.8 200', w: 2.4, o: 0.2 },
]

function GrainPattern({ finish, tones }: { finish: Finish; tones: Tones }): ReactElement {
  return (
    <pattern
      id={`cw-grain-${finish}`}
      patternUnits="userSpaceOnUse"
      width={43}
      height={200}
    >
      <rect width={43} height={200} fill={tones.body} />
      <g stroke={tones.figure} fill="none" strokeLinecap="round">
        {FIGURE.map((g, i) => (
          <path key={i} d={g.d} strokeWidth={g.w} opacity={g.o} />
        ))}
      </g>
      <g stroke={tones.grain} fill="none" strokeLinecap="round">
        {GRAIN.map((g, i) => (
          <path key={i} d={g.d} strokeWidth={g.w} opacity={g.o} />
        ))}
      </g>
    </pattern>
  )
}

/* ─────────────────────────────────────────────────────────────
   PieceDefs — mount once, at the board root.
   ───────────────────────────────────────────────────────────── */

export function PieceDefs(): ReactElement {
  return (
    <svg
      width={0}
      height={0}
      aria-hidden="true"
      focusable="false"
      style={{
        position: 'absolute',
        width: 0,
        height: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
      }}
    >
      <style>{SHEET}</style>
      <defs>
        <GrainPattern finish="maple" tones={MAPLE} />
        <GrainPattern finish="walnut" tones={WALNUT} />

        {/* ── cw-turn ─────────────────────────────────────────
            The one gradient that does most of the work. A cylinder
            lit from the upper right is dark down its far flank, opens
            out to nothing about two thirds across, and then darkens
            again at the very edge where the surface turns away from
            the lamp. That second darkening is the whole trick: without
            a terminator at the right-hand rim the piece reads as a
            flat shape with a gradient on it rather than as something
            round. */}
        <linearGradient id="cw-turn" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor={SHADOW} stopOpacity={0.52} />
          <stop offset="0.14" stopColor={SHADOW} stopOpacity={0.3} />
          <stop offset="0.4" stopColor={SHADOW} stopOpacity={0.07} />
          <stop offset="0.62" stopColor={SHADOW} stopOpacity={0} />
          <stop offset="0.86" stopColor={SHADOW} stopOpacity={0.15} />
          <stop offset="1" stopColor={SHADOW} stopOpacity={0.42} />
        </linearGradient>

        {/* ── cw-lacquer ──────────────────────────────────────
            A shellacked turning has a hard, narrow specular that runs
            the full height of the piece in a single unbroken stripe,
            because every ring on it shares an axis. Keeping it narrow
            is what separates lacquer from satin; widen it past about
            0.2 of the bounding box and the piece looks wet. */}
        <linearGradient id="cw-lacquer" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0.54" stopColor={SPECULAR} stopOpacity={0} />
          <stop offset="0.66" stopColor={SPECULAR} stopOpacity={0.2} />
          <stop offset="0.72" stopColor={SPECULAR} stopOpacity={0.34} />
          <stop offset="0.79" stopColor={SPECULAR} stopOpacity={0.1} />
          <stop offset="0.9" stopColor={SPECULAR} stopOpacity={0} />
        </linearGradient>

        {/* Sky term: the lamp is above as well as to the side. */}
        <linearGradient id="cw-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={SPECULAR} stopOpacity={0.1} />
          <stop offset="0.42" stopColor={SPECULAR} stopOpacity={0.015} />
          <stop offset="1" stopColor={SPECULAR} stopOpacity={0} />
        </linearGradient>

        {/* Ambient occlusion into the board. A piece whose base is the
            same value as its shoulders is a piece that floats. */}
        <linearGradient id="cw-floor" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.55" stopColor={SHADOW} stopOpacity={0} />
          <stop offset="0.88" stopColor={SHADOW} stopOpacity={0.1} />
          <stop offset="1" stopColor={SHADOW} stopOpacity={0.26} />
        </linearGradient>

        {/* The pool of shadow the piece stands in. */}
        <radialGradient id="cw-contact" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor={SHADOW} stopOpacity={0.5} />
          <stop offset="0.55" stopColor={SHADOW} stopOpacity={0.24} />
          <stop offset="1" stopColor={SHADOW} stopOpacity={0} />
        </radialGradient>

        {/* Baize nap — two specks on a 3-unit lattice. At the size a
            piece actually renders this is a texture you feel rather
            than see, which is the correct amount of felt. */}
        <pattern id="cw-nap" patternUnits="userSpaceOnUse" width={3} height={3}>
          <circle cx={0.8} cy={0.8} r={0.36} fill={FELT.lit} opacity={0.55} />
          <circle cx={2.2} cy={2.1} r={0.3} fill={FELT.deep} opacity={0.6} />
        </pattern>

        {/* ── cw-wear ─────────────────────────────────────────
            Edge wear, and it is applied to exactly one element per
            piece: the contour stroke.

            Displacing the whole body group would look marginally
            better and would put thirty-two live displacement maps on
            the board at once. Displacing the contour alone gets the
            thing that actually reads — a rim that wanders a fraction
            in and out of the fill, the way an edge does after a few
            hundred games — for one filtered path per piece. The scale
            is deliberately smaller than the stroke width so the line
            never fully leaves the silhouette; at 1.2 it detaches and
            reads as a rendering bug rather than as wear. */}
        <filter
          id="cw-wear"
          x="-6%"
          y="-4%"
          width="112%"
          height="108%"
          filterUnits="objectBoundingBox"
          colorInterpolationFilters="sRGB"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.16 0.045"
            numOctaves={2}
            seed={11}
            result="cw-rough"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="cw-rough"
            scale={0.42}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>
  )
}

export default PieceDefs
