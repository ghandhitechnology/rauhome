/* ─────────────────────────────────────────────────────────────
   QUEEN — 168 tall, base 27

   Second tallest, widest base, and the only piece whose profile keeps
   changing direction all the way up: cove, waist, collar, a vase that
   swells and then pulls in at the shoulder, and then the coronet
   throws itself back out again. That last reversal is what separates
   her from the king — his crown sits *on* a stem, hers grows out of
   one — and it is why the shoulder at y=73 pinches to 11.9 before the
   ring flares to 19.6. Take the pinch out and she is a bishop with
   spikes.

   The coronet is nine points on a circle, not a row of triangles.
   Five of them are on the near side of the ring and four on the far
   side, they stand at different heights on the screen because they
   stand at different depths on the ring, and the far four are drawn
   *behind* the finial while the near five are drawn in front of it —
   including the one at dead centre, which crosses the neck. Drawing
   all nine in one pass at one height is the difference between a
   crown and a comb, and it is the reason `rimY` exists.

   Wear is on the leftmost coronet point, which is the thinnest piece
   of end grain in the set and the first thing to lose its tip.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from 'react'
import { Collar, CX, Disc, foot, revolve, rimY, Turned, Wood, type Station } from '../defs'

const W = 27

/** Finial: apex at 28, so the centre sits 6.6 below it. */
const BALL = { cx: 60, cy: 34.6, r: 6.6 }

const PROFILE: Station[] = [
  ...foot(W),
  { dx: 8.6, y: 150, c: [12, 166, 9.2, 157] },
  { dx: 7.6, y: 136, c: [8.2, 143, 7.6, 139] },
  // Collar.
  { dx: 12.6, y: 128.4, c: [8.6, 133, 11, 130] },
  { dx: 13.1, y: 124.6 },
  { dx: 9.4, y: 121, c: [12.7, 122.9, 11, 121.4] },
  // The vase: out to the belly at y≈96, then in hard to the shoulder.
  { dx: 10.6, y: 114, c: [9.4, 118.5, 9.8, 116] },
  { dx: 15.6, y: 96, c: [13, 108, 15, 101] },
  { dx: 15.1, y: 86, c: [15.8, 92, 15.5, 88.4] },
  { dx: 12.6, y: 78, c: [14.6, 83, 13.6, 80.2] },
  { dx: 11.9, y: 73, c: [12.3, 76, 12, 74.4] },
  // and the coronet ring flung back out of it
  { dx: 16.4, y: 68, c: [12.6, 71, 14.6, 69] },
  { dx: 19.6, y: 60, c: [17.8, 65.4, 19, 62.4] },
  { dx: 19.6, y: 58 },
]

const FINIAL: Station[] = [
  { dx: 3.4, y: 58 },
  { dx: 3.1, y: 49, c: [3.4, 54, 3.1, 51] },
  { dx: 4.6, y: 46, c: [3.3, 47.6, 4, 46.6] },
  { dx: 2.8, y: 43.2, c: [4.6, 44.6, 3.4, 43.6] },
  { dx: 4.92, y: 39, c: [3.1, 41.4, 4.1, 39.9] },
  { dx: 0, y: 28, r: BALL.r },
]

const SIL = `${revolve(PROFILE)} ${revolve(FINIAL)}`

/* ── the coronet ──────────────────────────────────────────────
   Nine points every forty degrees, starting with one at dead centre
   front. `u` is the horizontal offset of each; the ones with a
   positive sine are on the near side of the ring and occlude the
   finial, the rest are behind it. The points stand on a slightly
   smaller circle than the ring's widest flare, which is where the
   top of a turned ring actually is. */
const RING = 19.6
const POINT_R = 18
const POINT_PLANE = 58
const POINT_H = 11
const HALF = 2.4

const POINTS = Array.from({ length: 9 }, (_, k) => {
  const a = (Math.PI / 2) + (k * 40 * Math.PI) / 180
  return { u: POINT_R * Math.cos(a), near: Math.sin(a) > 0 }
})

function point(u: number, near: boolean): string {
  const base = rimY(u, POINT_R, POINT_PLANE, near)
  const tip = base - POINT_H
  const x = CX + u
  return (
    `M${(x - HALF).toFixed(2)} ${base.toFixed(2)} ` +
    `L${(x - 0.85).toFixed(2)} ${(tip + 1.2).toFixed(2)} ` +
    `Q${x.toFixed(2)} ${tip.toFixed(2)} ${(x + 0.85).toFixed(2)} ${(tip + 1.2).toFixed(2)} ` +
    `L${(x + HALF).toFixed(2)} ${base.toFixed(2)} Z`
  )
}

/** The narrow facet down a point's lamp side — a spike with no facet is a tooth. */
function facet(u: number, near: boolean): string {
  const base = rimY(u, POINT_R, POINT_PLANE, near)
  const tip = base - POINT_H
  const x = CX + u
  return (
    `M${(x + 0.3).toFixed(2)} ${(tip + 1.4).toFixed(2)} ` +
    `L${(x + HALF).toFixed(2)} ${base.toFixed(2)} ` +
    `L${(x + HALF * 0.32).toFixed(2)} ${base.toFixed(2)} Z`
  )
}

const NEAR_POINTS = POINTS.filter((p) => p.near)
const FAR_POINTS = POINTS.filter((p) => !p.near)

export default function Piece(): ReactElement {
  return (
    <Turned d={SIL} w={W}>
      {/* Base arris and bead. */}
      <path
        d="M36.4 184.5A23.6 4.25 0 0 0 83.6 184.5"
        className="cw-k-line"
        strokeWidth={0.9}
        opacity={0.32}
      />
      <path
        d="M42.2 175.7A17.8 3.2 0 0 0 77.8 175.7"
        className="cw-k-lit"
        strokeWidth={0.9}
        opacity={0.3}
      />

      {/* Grain up the waist and out over the belly of the vase. */}
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M54.4 170C51.8 158 51.4 146 53.4 133" strokeWidth={0.7} opacity={0.3} />
        <path d="M66.6 172C69.2 159 69 147 67 134" strokeWidth={0.5} opacity={0.22} />
      </g>

      <Collar rx={13.1} top={124.6} bot={128.4} />

      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M52.6 120C49.4 110 48.2 100 49.6 88" strokeWidth={0.65} opacity={0.28} />
        <path d="M68 121C71 111 72 101 70.6 89" strokeWidth={0.5} opacity={0.2} />
        <path d="M60.4 118C59.6 106 59.6 94 60.2 84" strokeWidth={0.4} opacity={0.16} />
        <path className="cw-k-figure" d="M56.2 116C54.2 104 54 94 55.4 85" strokeWidth={1.8} opacity={0.14} />
      </g>

      {/* The shoulder, and the shadow the coronet ring drops onto it. */}
      <path
        d="M47.6 70.4A12.4 2.23 0 0 0 72.4 70.4"
        className="cw-k-line"
        strokeWidth={1.3}
        opacity={0.4}
      />
      {/* the ring's own lit arris, where the flare turns over */}
      <path
        d="M42.4 60.6A19.4 3.49 0 0 0 77.6 60.6"
        className="cw-k-lit"
        strokeWidth={1}
        opacity={0.32}
      />

      {/* ── the coronet ──────────────────────────────────────
          Ring top, far points, finial, near points. The order is the
          depth order and nothing else will do. */}
      <Disc rx={RING} y={POINT_PLANE} lit={0.48} />

      {FAR_POINTS.map((p, i) => (
        <g key={`f${i}`}>
          <path d={point(p.u, false)} className="cw-shade" />
          <path d={point(p.u, false)} fill="url(#cw-turn)" opacity={0.45} />
        </g>
      ))}

      {/* Finial: the ball's own roundness over the whole-piece pass. */}
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-turn)" opacity={0.44} />
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-sky)" opacity={0.7} />
      <ellipse
        cx={63.1}
        cy={31.3}
        rx={1.7}
        ry={2.5}
        transform="rotate(-26 63.1 31.3)"
        className="cw-lit"
        opacity={0.55}
      />
      <path
        d="M53.5 39.4A6.6 6.6 0 0 0 66.5 39.4"
        className="cw-k-line"
        strokeWidth={0.7}
        opacity={0.3}
      />
      {/* the bead under the ball, and the shadow the ball drops on it */}
      <ellipse cx={60} cy={44.6} rx={2.9} ry={1} className="cw-deep" opacity={0.35} />

      {NEAR_POINTS.map((p, i) => (
        <g key={`n${i}`}>
          <Wood d={point(p.u, true)} grain={0.45} />
          <path d={facet(p.u, true)} className="cw-lit" opacity={0.38} />
          <path d={point(p.u, true)} className="cw-k-line" strokeWidth={0.5} opacity={0.34} />
        </g>
      ))}

      {/* Snapped. The left point has lost its tip; end grain that thin does
          not survive a box, and the break is paler than the sealed surface. */}
      <path
        d="M40.7 50.4C41.3 49.4 42.3 49 43.2 49.4C42.6 50.4 41.7 51.1 40.9 51.4Z"
        className="cw-raw"
        opacity={0.62}
      />
      <path
        d="M40.7 50.4C41.3 49.4 42.3 49 43.2 49.4"
        className="cw-k-line"
        strokeWidth={0.5}
        opacity={0.38}
      />
      {/* and a rub on the belly, where she is gripped */}
      <ellipse
        cx={70.6}
        cy={99}
        rx={2.6}
        ry={5.4}
        transform="rotate(9 70.6 99)"
        className="cw-raw"
        opacity={0.2}
      />
    </Turned>
  )
}
