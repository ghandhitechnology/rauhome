/* ─────────────────────────────────────────────────────────────
   BISHOP — 150 tall, base 23

   Two masses with a hard brim between them: a bell below, a mitre
   above, and a flat disc at y=98.6–102.4 that belongs to neither. The
   brim is the whole piece. Take it away and the bishop is a pawn that
   has been stretched; put it in and the eye reads the mitre as a
   separate thing *sitting on* the body, which is what it is.

   The mitre gets its own `revolve` — the top eight stations of the same
   profile — so it can carry its own turn gradient. A mitre shaded by
   the whole-piece gradient is lit as though it were the same cylinder
   as the base, and it is not: it is a narrower solid a hundred units
   further up, and its terminator sits somewhere else.

   The slot is cut across the lit side, upper-left to lower-right, the
   way it is on a real Staunton mitre. Three parts, and skipping any
   one of them turns it back into a painted line: a dark interior, a
   lit lower lip where the cut catches the lamp, and a hard shadow on
   the upper wall where the cut is deepest.

   Wear: the brim's left edge, which is the widest thing on the piece
   and therefore the first thing to meet another piece in the box.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from 'react'
import { Collar, foot, revolve, Turned, type Station } from '../defs'

const W = 23

/** Finial: apex at 46, so the centre sits 5.8 below it. */
const BALL = { cx: 60, cy: 51.8, r: 5.8 }

const PROFILE: Station[] = [
  ...foot(W),
  // Stem, hollowed hard — the bishop is the most waisted piece in the set.
  { dx: 7.6, y: 152, c: [10.4, 168, 8, 158] },
  { dx: 6.6, y: 142, c: [7.2, 147.5, 6.6, 144.5] },
  // Collar.
  { dx: 11.4, y: 134.6, c: [7.6, 139.4, 9.9, 136.2] },
  { dx: 11.8, y: 131 },
  { dx: 8.2, y: 127.6, c: [11.4, 129.4, 9.8, 128] },
  // The bell swells out of it and keeps swelling to the brim.
  { dx: 9.2, y: 121, c: [8.2, 125, 8.5, 123] },
  { dx: 16.2, y: 106, c: [11.6, 115, 14.6, 110] },
  // The brim: a vertical face, not a bulge. It has to read as an edge.
  { dx: 17.6, y: 102.4, c: [16.8, 104.6, 17.4, 103.2] },
  { dx: 17.6, y: 98.6 },
  { dx: 14.2, y: 95, c: [17.5, 96.8, 15.8, 95.4] },
  // Mitre.
  { dx: 13.4, y: 90, c: [14.1, 93.4, 13.6, 91.6] },
  { dx: 12.8, y: 79, c: [13.6, 85, 13.2, 82] },
  { dx: 8, y: 65, c: [12, 73, 10.6, 68.6] },
  { dx: 3.2, y: 60, c: [6, 63.6, 4.2, 61.6] },
  // A bead under the finial, so the ball is set on something.
  { dx: 4.4, y: 58.4, c: [3.2, 59.4, 4, 58.8] },
  { dx: 2.9, y: 56.4, c: [4.4, 57.6, 3.4, 56.8] },
  { dx: 5.4, y: 54, c: [3.1, 55.4, 4.2, 54.5] },
  { dx: 0, y: 46, r: BALL.r },
]

const SIL = revolve(PROFILE)
/** Mitre and finial alone, for lighting that belongs to them. */
const MITRE = revolve(PROFILE.slice(-8))

export default function Piece(): ReactElement {
  return (
    <Turned d={SIL} w={W}>
      {/* Base arris, bead, and the shadow the bead drops into the cove. */}
      <path
        d="M43.9 185.3A20.1 3.62 0 0 0 76.1 185.3"
        className="cw-k-line"
        strokeWidth={0.8}
        opacity={0.32}
      />
      <path
        d="M45.5 176.5A15.2 2.73 0 0 0 74.5 176.5"
        className="cw-k-lit"
        strokeWidth={0.9}
        opacity={0.3}
      />

      {/* Grain wrapping the waist, bowing where the stem is thinnest. */}
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M55.8 172C54 160 54.2 148 55.6 137" strokeWidth={0.65} opacity={0.3} />
        <path d="M64.4 174C66 161 65.6 149 64.2 138" strokeWidth={0.5} opacity={0.22} />
      </g>

      <Collar rx={11.8} top={131} bot={134.6} />

      {/* Grain over the bell, opening out as the surface does. */}
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M53.6 126C50.4 118 48.4 110 47.8 103" strokeWidth={0.6} opacity={0.26} />
        <path d="M66.6 127C69.6 119 71.4 111 72 104" strokeWidth={0.45} opacity={0.2} />
        <path d="M60.4 124C59.8 116 59.6 108 60 102" strokeWidth={0.4} opacity={0.16} />
      </g>

      {/* The brim, and the hard line it throws onto the bell under it. */}
      <Collar rx={17.6} top={98.6} bot={102.4} lit={0.5} />
      <path
        d="M42.4 103.4A17.6 3.17 0 0 0 77.6 103.4"
        className="cw-k-line"
        strokeWidth={1.3}
        opacity={0.42}
      />

      {/* ── the mitre ────────────────────────────────────────
          Its own turn and sky terms. It is a smaller solid a long way
          up the piece and it does not share the base's terminator. */}
      <path d={MITRE} fill="url(#cw-turn)" opacity={0.42} />
      <path d={MITRE} fill="url(#cw-sky)" opacity={0.6} />
      {/* and the shadow it sits in, on the brim's top face */}
      <path
        d="M46.6 95.6A13.6 2.45 0 0 0 73.4 95.6"
        className="cw-k-line"
        strokeWidth={1.5}
        opacity={0.34}
      />
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M52.4 92C51 84 51.4 74 54.2 66" strokeWidth={0.55} opacity={0.24} />
        <path d="M67.8 93C69 85 68.6 75 65.8 67" strokeWidth={0.42} opacity={0.18} />
      </g>

      {/* ── the slot ─────────────────────────────────────────
          Interior, lit lower lip, shadowed upper wall. */}
      <path
        d="M55.4 67.2C60.4 72.4 65.4 77.4 70 82L68.2 84.6C63.6 79.8 58.4 74.4 53.4 69.4Z"
        className="cw-deep"
        opacity={0.82}
      />
      <path
        d="M53.4 69.4C58.4 74.4 63.6 79.8 68.2 84.6"
        className="cw-k-lit"
        strokeWidth={1.1}
        opacity={0.45}
      />
      <path
        d="M55.4 67.2C60.4 72.4 65.4 77.4 70 82"
        className="cw-k-line"
        strokeWidth={0.8}
        opacity={0.5}
      />
      {/* where the cut runs out at the rim it takes a bite out of the edge —
          shallow, and following the mitre's curve, or it reads as a tab */}
      <path
        d="M69.4 81.6C70.6 82.8 71.4 83.8 71.8 84.8C71 84.4 70 83.6 68.8 82.6Z"
        className="cw-deep"
        opacity={0.7}
      />

      {/* ── the finial ───────────────────────────────────────
          Ball, its own roundness, and one hard specular. */}
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-turn)" opacity={0.44} />
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-sky)" opacity={0.7} />
      <ellipse
        cx={62.7}
        cy={49.2}
        rx={1.5}
        ry={2.1}
        transform="rotate(-26 62.7 49.2)"
        className="cw-lit"
        opacity={0.55}
      />
      <path
        d="M54.9 56.6A5.4 5.4 0 0 0 65.1 56.6"
        className="cw-k-line"
        strokeWidth={0.7}
        opacity={0.3}
      />

      {/* Boxed. The brim is the widest thing on the piece, so it is where
          another piece lands; the arris is gone and the wood under it is bare. */}
      <path
        d="M42.6 99.4C43.2 98.6 44.6 98.4 45.8 98.8C45.2 100.6 44 101.8 42.6 102.2Z"
        className="cw-raw"
        opacity={0.6}
      />
      <path
        d="M42.6 99.4C43.2 98.6 44.6 98.4 45.8 98.8"
        className="cw-k-line"
        strokeWidth={0.5}
        opacity={0.36}
      />
      {/* and a rub on the mitre's lit shoulder, where a thumb sits to lift it */}
      <ellipse
        cx={70}
        cy={87.6}
        rx={2.2}
        ry={3.4}
        transform="rotate(20 70 87.6)"
        className="cw-raw"
        opacity={0.22}
      />
    </Turned>
  )
}
