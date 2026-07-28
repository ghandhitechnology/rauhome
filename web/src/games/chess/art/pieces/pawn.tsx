/* ─────────────────────────────────────────────────────────────
   PAWN — 108 tall, base 21

   Eight of these stand on the board at once, which makes the pawn the
   piece that decides whether the set looks like a set. It is also the
   only one with nothing carved on it: base, cove, bead, a long waisted
   stem, a collar, and a ball. So all of the interest has to come from
   the turning itself, and there are three places it comes from.

   The waist. The stem does not taper — it *hollows*, narrowing to 5.3
   at chest height and then flaring back out into the collar. A straight
   cone is what a pawn looks like when nobody held a gouge against it.

   The collar. It is proud of the shaft by three units and it throws a
   line of shadow down onto the shaft below. That shadow is the single
   detail that turns a painted stripe into a ring with a diameter.

   The ball. It gets its own turn gradient and its own sky term on top
   of the whole-piece ones, because a sphere sitting on a cylinder is
   lit differently from the cylinder, and shading them as one object is
   why cheap vector chess sets look like lollipops.

   The wear is on the upper-left of the ball, which is where eight
   pawns get knocked into each other and into the lid of the box, and
   on the front-left rim of the base, which is where they get dragged
   across a square rather than lifted.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from 'react'
import { Collar, foot, revolve, Turned, type Station } from '../defs'

const W = 21

/** Sphere: apex at 88, so the centre is 11.9 below it. */
const BALL = { cx: 60, cy: 99.9, r: 11.9 }

const PROFILE: Station[] = [
  ...foot(W),
  // The waist. Concave both ways off the narrowest point at y≈134.
  { dx: 6.2, y: 152, c: [9.6, 168, 6.8, 160] },
  { dx: 5.3, y: 132, c: [5.7, 144, 5.3, 138] },
  // Out into the collar, square-shouldered so it catches an edge of light.
  { dx: 10.2, y: 124.4, c: [6.9, 129.4, 8.8, 126] },
  { dx: 10.55, y: 121.2 },
  { dx: 7.2, y: 118.2, c: [10.2, 119.9, 8.7, 118.6] },
  // The neck, then the shoulder of the ball.
  { dx: 5.7, y: 113.4, c: [6.3, 116.4, 5.7, 115] },
  { dx: 9.3, y: 107.4, c: [5.8, 110.6, 7.4, 108.4] },
  { dx: 0, y: 88, r: BALL.r },
]

const SIL = revolve(PROFILE)

export default function Piece(): ReactElement {
  return (
    <Turned d={SIL} w={W}>
      {/* The arris where the base disc's face meets its top cove. A turner
          leaves this crisp and the board wears it round again. */}
      <path
        d="M41.6 185.6A18.4 3.31 0 0 0 78.4 185.6"
        className="cw-k-line"
        strokeWidth={0.8}
        opacity={0.34}
      />
      <path
        d="M45.4 184.5A18.4 3.31 0 0 0 74.8 184.9"
        className="cw-k-lit"
        strokeWidth={0.7}
        opacity={0.26}
      />

      {/* The bead above the cove, and the shadow it drops into it. */}
      <path
        d="M46.4 176.8A13.86 2.49 0 0 0 73.6 176.8"
        className="cw-k-lit"
        strokeWidth={0.9}
        opacity={0.3}
      />
      <path
        d="M47.4 179.3A13.4 2.4 0 0 0 72.6 179.3"
        className="cw-k-line"
        strokeWidth={1}
        opacity={0.34}
      />

      {/* Grain wrapping the waist. The pattern behind it runs dead straight;
          these two are what tell you the shaft is round. */}
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M56.4 174C55.2 162 55.6 150 57 138" strokeWidth={0.65} opacity={0.32} />
        <path d="M63.6 176C64.6 164 64.2 152 63 140" strokeWidth={0.5} opacity={0.24} />
        <path d="M60.4 172C59.4 160 59.8 148 60.8 136" strokeWidth={0.4} opacity={0.18} />
      </g>

      <Collar rx={10.55} top={121.2} bot={124.4} />

      {/* The ball's own lighting, over the top of the whole-piece pass. */}
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-turn)" opacity={0.46} />
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-sky)" opacity={0.7} />

      {/* Grain over the ball, bowing with the surface. */}
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M54.6 92.2C53.1 96.4 52.9 102.4 54.4 106.9" strokeWidth={0.5} opacity={0.26} />
        <path d="M66.4 91.6C68 96 68.2 102.6 66.6 107.4" strokeWidth={0.42} opacity={0.2} />
        <path d="M60.2 88.4C59.4 94 59.4 104 60.4 110.4" strokeWidth={0.36} opacity={0.15} />
      </g>

      {/* Specular. Small, offset up-right, with a hot core — lacquer, not satin. */}
      <ellipse
        cx={65.4}
        cy={94.4}
        rx={2.9}
        ry={4.2}
        transform="rotate(-24 65.4 94.4)"
        className="cw-lit"
        opacity={0.5}
      />
      <ellipse cx={65.9} cy={93.4} rx={1.2} ry={1.9} transform="rotate(-24 65.9 93.4)" className="cw-lit" opacity={0.62} />

      {/* Knocked. A lens of unsealed wood along the upper-left arc, with the
          hairline of shadow that a broken edge always keeps on its underside. */}
      <path
        d="M53.9 92.2C51.5 94.5 49.9 97.4 49.3 100.6C50.6 98.2 52.4 95.5 54.9 93.5Z"
        className="cw-raw"
        opacity={0.52}
      />
      <path
        d="M53.9 92.2C51.5 94.5 49.9 97.4 49.3 100.6"
        className="cw-k-line"
        strokeWidth={0.5}
        opacity={0.35}
      />

      {/* The ball throws its shadow onto the neck it stands on. */}
      <ellipse cx={60} cy={115.6} rx={6.1} ry={1.9} className="cw-deep" opacity={0.34} />

      {/* Dragged. The front-left of the base, where a pawn gets pushed rather
          than lifted, has lost its arris. */}
      <path
        d="M45.1 193.3C46.5 192.1 48.4 191.8 49.9 192.5C48.9 194 47.2 194.8 45.5 194.6Z"
        className="cw-raw"
        opacity={0.55}
      />
      <path
        d="M45.1 193.3C46.5 192.1 48.4 191.8 49.9 192.5"
        className="cw-k-line"
        strokeWidth={0.55}
        opacity={0.4}
      />
    </Turned>
  )
}
