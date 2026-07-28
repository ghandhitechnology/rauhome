/* ─────────────────────────────────────────────────────────────
   KING — 182 tall, base 29

   The tallest and the heaviest, and the only piece in the set whose
   top is not a turning at all. Everything up to y=51 comes off the
   lathe; the cross above it was cut with a saw and a chisel out of the
   same blank, and it has to look like it. So it is drawn the way the
   knight is drawn — flat facets with hard arrises between them — and
   not with the cylinder gradient, which would round it off and make it
   look like a moulded plastic cross.

   The cross is real geometry: an upright 6.6 wide, a bar 21.6 across,
   every outer corner chamfered by 1.1, and eleven separate facets
   catching or missing the lamp. It would be quicker to draw a plus
   sign and put a gradient on it. It would also be the moment anyone
   looking at this set decided it was clip art, because the cross is
   the piece of the board the eye goes to first and stays on longest.

   Below it: a small ball, a bead, and a crown band with six rounded
   battlements standing on a circular rim — the same `rimY` arithmetic
   the rook and the queen use, for the same reason. The king's teeth
   are shallower and rounder than the queen's points, which is most of
   what tells the two apart at the size a piece actually renders.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from 'react'
import { Collar, CX, foot, revolve, rimRun, rimY, Turned, type Station } from '../defs'

const W = 29

/** The ball under the cross: apex at 30.8, centre 5.2 below it. */
const BALL = { cx: 60, cy: 36, r: 5.2 }

const PROFILE: Station[] = [
  ...foot(W),
  { dx: 9.4, y: 150, c: [13, 166, 10, 157] },
  { dx: 8.2, y: 134, c: [8.9, 142, 8.2, 138] },
  // Collar.
  { dx: 13.6, y: 126, c: [9.3, 131, 11.9, 127.6] },
  { dx: 14.1, y: 122 },
  { dx: 10.2, y: 118.2, c: [13.7, 120.2, 11.9, 118.7] },
  // The vase. Fuller and lower-bellied than the queen's — he is heavier,
  // and the belly is where that has to be said.
  { dx: 11.4, y: 110, c: [10.2, 115.4, 10.6, 112.4] },
  { dx: 16.2, y: 92, c: [13.8, 104, 15.6, 97] },
  { dx: 15.7, y: 82, c: [16.4, 88, 16.1, 84.4] },
  { dx: 13.2, y: 74, c: [15.2, 79, 14.2, 76.2] },
  { dx: 12.4, y: 69, c: [12.8, 72, 12.5, 70.4] },
  // Crown band.
  { dx: 16.8, y: 64, c: [12.6, 67, 15, 65] },
  { dx: 18.2, y: 55, c: [17.6, 61, 18.1, 57.4] },
  { dx: 18.2, y: 51 },
]

const FINIAL: Station[] = [
  { dx: 3.6, y: 51 },
  { dx: 3.3, y: 46, c: [3.6, 49, 3.3, 47.4] },
  { dx: 5, y: 43, c: [3.4, 44.6, 4.4, 43.4] },
  { dx: 3, y: 40.4, c: [5, 41.8, 3.7, 40.8] },
  { dx: 4.56, y: 38.5, c: [3.2, 39.6, 4, 38.8] },
  { dx: 0, y: 30.8, r: BALL.r },
]

/* ── the cross ────────────────────────────────────────────────
   Written out longhand rather than built from two rectangles: the
   chamfers are the reason it reads as carved wood and they only exist
   at the outer corners, which a union of two rects cannot express.
   Wound the same way round as everything `revolve` produces, so it
   unions cleanly with the turnings in one fill. */
const CROSS = `M63.3 33
L63.3 27.8 L69.7 27.8 L70.8 26.7
L70.8 23.3 L69.7 22.2 L63.3 22.2
L63.3 15.1 L62.2 14 L57.8 14 L56.7 15.1
L56.7 22.2 L50.3 22.2 L49.2 23.3
L49.2 26.7 L50.3 27.8 L56.7 27.8
L56.7 33 Z`

const SIL = `${revolve(PROFILE)} ${revolve(FINIAL)} ${CROSS}`

/* ── the crown band ───────────────────────────────────────────
   Six rounded battlements on the rim at y=51. Square-cut would read as
   a short rook; the rounding, and the fact that they are only 4.6 deep,
   is what keeps the two silhouettes apart. */
const CROWN_R = 18.2
const CROWN_PLANE = 51
const CROWN_TOP = 46.4
const TOOTH_W = 4.2
const TOOTH_GAP = 2.24

const TEETH = Array.from({ length: 6 }, (_, i) => {
  const u0 = -CROWN_R + i * (TOOTH_W + TOOTH_GAP)
  return [u0, u0 + TOOTH_W] as const
})

function tooth(u0: number, u1: number): string {
  const b0 = rimY(u0, CROWN_R, CROWN_PLANE, true)
  const b1 = rimY(u1, CROWN_R, CROWN_PLANE, true)
  const t0 = rimY(u0, CROWN_R, CROWN_TOP, true)
  const t1 = rimY(u1, CROWN_R, CROWN_TOP, true)
  const x0 = CX + u0
  const x1 = CX + u1
  return (
    `M${x0.toFixed(2)} ${b0.toFixed(2)} ` +
    `L${x0.toFixed(2)} ${(t0 + 1.5).toFixed(2)} ` +
    `Q${x0.toFixed(2)} ${t0.toFixed(2)} ${(x0 + 1.5).toFixed(2)} ${t0.toFixed(2)} ` +
    `L${(x1 - 1.5).toFixed(2)} ${t1.toFixed(2)} ` +
    `Q${x1.toFixed(2)} ${t1.toFixed(2)} ${x1.toFixed(2)} ${(t1 + 1.5).toFixed(2)} ` +
    `L${x1.toFixed(2)} ${b1.toFixed(2)} ` +
    `${rimRun(u1, u0, CROWN_R, CROWN_PLANE, true, 3)} Z`
  )
}

const TOOTH_PATHS = TEETH.map(([a, b]) => tooth(a, b))

export default function Piece(): ReactElement {
  return (
    <Turned d={SIL} w={W}>
      {/* Base arris and bead — the widest foot in the set, so both rings
          have to be crisp or the whole piece reads as soft. */}
      <path
        d="M34.6 184.2A25.4 4.57 0 0 0 85.4 184.2"
        className="cw-k-line"
        strokeWidth={0.9}
        opacity={0.34}
      />
      <path
        d="M40.9 175.4A19.1 3.44 0 0 0 79.1 175.4"
        className="cw-k-lit"
        strokeWidth={1}
        opacity={0.3}
      />

      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M53.6 170C50.6 158 50.2 145 52.4 131" strokeWidth={0.75} opacity={0.3} />
        <path d="M67.6 172C70.6 159 70.6 146 68.4 132" strokeWidth={0.55} opacity={0.22} />
      </g>

      <Collar rx={14.1} top={122} bot={126} />

      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M52 116C48.4 106 47.6 96 49.2 84" strokeWidth={0.7} opacity={0.28} />
        <path d="M68.6 117C72 107 72.6 97 71 85" strokeWidth={0.5} opacity={0.2} />
        <path d="M60.4 114C59.6 102 59.6 92 60.2 80" strokeWidth={0.42} opacity={0.16} />
        <path className="cw-k-figure" d="M55.6 112C53.4 100 53.2 90 54.8 81" strokeWidth={1.9} opacity={0.14} />
      </g>

      {/* Shoulder, and the shadow the crown band drops onto it. */}
      <path
        d="M47.4 66.4A12.8 2.3 0 0 0 72.6 66.4"
        className="cw-k-line"
        strokeWidth={1.4}
        opacity={0.4}
      />

      {/* ── the crown band ───────────────────────────────────
          The band itself is already in the silhouette; what it needs is
          its top rim lit, its teeth standing on that rim, and the dark
          bore showing between them. */}
      <ellipse cx={CX} cy={CROWN_PLANE} rx={CROWN_R} ry={CROWN_R * 0.18} className="cw-body" />
      <ellipse cx={CX} cy={CROWN_PLANE} rx={14.4} ry={14.4 * 0.18} className="cw-deep" opacity={0.75} />
      <path
        d={`M${CX - CROWN_R} ${CROWN_PLANE} A${CROWN_R} ${CROWN_R * 0.18} 0 0 0 ${CX + CROWN_R} ${CROWN_PLANE} Z`}
        className="cw-lit"
        opacity={0.34}
      />
      {TOOTH_PATHS.map((d, i) => (
        <g key={i}>
          <path d={d} className="cw-body" />
          <path d={d} className="cw-grain" opacity={0.45} />
          <path d={d} fill="url(#cw-turn)" />
          <path d={d} fill="url(#cw-lacquer)" />
          <path d={d} className="cw-k-line" strokeWidth={0.55} opacity={0.32} />
        </g>
      ))}

      {/* ── the finial ───────────────────────────────────────
          Ball and bead, with the ball's own roundness. */}
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-turn)" opacity={0.44} />
      <circle cx={BALL.cx} cy={BALL.cy} r={BALL.r} fill="url(#cw-sky)" opacity={0.7} />
      <ellipse
        cx={62.5}
        cy={33.4}
        rx={1.3}
        ry={1.9}
        transform="rotate(-26 62.5 33.4)"
        className="cw-lit"
        opacity={0.55}
      />
      <path
        d="M55 38.6A5.2 5.2 0 0 0 65 38.6"
        className="cw-k-line"
        strokeWidth={0.6}
        opacity={0.3}
      />

      {/* ── the cross ────────────────────────────────────────
          Eleven facets. Top chamfers take the lamp square on, the lit
          side is the right, the underside of the bar is the darkest
          thing above the shoulder, and the cross drops a shadow onto
          the ball it is standing in. */}
      <g>
        {/* top chamfers — the two brightest surfaces on the whole piece */}
        <path d="M56.7 15.1L57.8 14L62.2 14L63.3 15.1Z" className="cw-lit" opacity={0.62} />
        <path d="M49.2 23.3L50.3 22.2L69.7 22.2L70.8 23.3Z" className="cw-lit" opacity={0.5} />
        {/* lit flanks, right of the axis */}
        <path d="M61.6 15.3L63.3 15.1L63.3 22.2L61.6 22.2Z" className="cw-lit" opacity={0.3} />
        <path d="M61.6 27.8L63.3 27.8L63.3 33L61.6 33Z" className="cw-lit" opacity={0.3} />
        <path d="M69.2 22.5L70.8 23.3L70.8 26.7L69.2 27.5Z" className="cw-lit" opacity={0.42} />
        {/* shaded flanks, left of it */}
        <path d="M56.7 15.3L58.5 15.3L58.5 22.2L56.7 22.2Z" className="cw-shade" opacity={0.5} />
        <path d="M56.7 27.8L58.5 27.8L58.5 33L56.7 33Z" className="cw-shade" opacity={0.5} />
        <path d="M49.2 23.3L50.9 22.7L50.9 27.3L49.2 26.7Z" className="cw-shade" opacity={0.62} />
        {/* the bar's underside, and the shadow it throws down the upright */}
        <path d="M49.2 26.7L70.8 26.7L69.7 27.8L50.3 27.8Z" className="cw-deep" opacity={0.6} />
        <path d="M56.7 27.8L63.3 27.8L63.3 29.4L56.7 29.4Z" className="cw-deep" opacity={0.3} />
        {/* the arris down the middle of the upright, where the two faces meet */}
        <path d="M60.1 15L60.1 22.2M60.1 27.8L60.1 32.6" className="cw-k-line" strokeWidth={0.45} opacity={0.22} />
        {/* end grain on the sawn faces of the bar */}
        <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
          <path d="M52.6 23.6L52.6 26.4M55.4 23.4L55.4 26.6M65 23.4L65 26.6M67.8 23.6L67.8 26.4" strokeWidth={0.4} opacity={0.22} />
        </g>
      </g>
      {/* the cross standing in the ball throws a shadow across it */}
      <path d="M56.7 32.4C58.4 33.6 61.6 33.6 63.3 32.4L63.3 33.4C61.4 34.4 58.6 34.4 56.7 33.4Z" className="cw-deep" opacity={0.4} />

      {/* Chipped. The left arm of the cross is the most exposed end grain on
          the board and it has taken a knock; the break is unsealed and pale. */}
      <path
        d="M49.2 24.6L50.9 24.2L50.9 25.6L49.2 26Z"
        className="cw-raw"
        opacity={0.6}
      />
      <path d="M49.2 24.6L50.9 24.2" className="cw-k-line" strokeWidth={0.45} opacity={0.4} />
      {/* and the usual rub on the belly */}
      <ellipse
        cx={71.4}
        cy={95}
        rx={2.6}
        ry={5.8}
        transform="rotate(8 71.4 95)"
        className="cw-raw"
        opacity={0.2}
      />
    </Turned>
  )
}
