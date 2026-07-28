/* ─────────────────────────────────────────────────────────────
   ROOK — 128 tall, base 24

   The shortest piece and the widest, which is the point: the rook is
   the only thing on the board with real mass, and if it reads as a
   tall thin tube the set has no bottom register at all.

   Everything above y=82 is the reason this file is longer than the
   pawn's. The crenellations are the one place in the set where a
   silhouette is decided by arithmetic rather than by a curve, and the
   arithmetic is `rimY`: the tower's top is a circle, so the feet of
   the merlons are *not level*. The centre one stands three units lower
   on the screen than the two at the edges, because it is nearer. Four
   merlons on a straight baseline is the single fastest way to turn a
   round tower into a cardboard cut-out, and it is what almost every
   flat chess icon does.

   The crenels are cut all the way through, so through each gap you see
   three things stacked: the near wall's cut top, the dark inside of the
   tower, and a far merlon standing higher up the screen because it is
   further away. Drawing the gaps as flat dark notches loses the depth
   that makes a rook a hollow thing rather than a comb.

   Wear is on the front-right merlon's outer corner. A rook is picked up
   by the battlements — thumb on one merlon, finger on the opposite one —
   and that is the corner a right hand lands on.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from 'react'
import { Collar, CX, Disc, foot, revolve, rimRun, rimY, SQUASH, Turned, Wood, type Station } from '../defs'

const W = 24

const PROFILE: Station[] = [
  ...foot(W),
  // Plinth: a square-edged block the tower stands on, so the shaft does not
  // grow straight out of the cove like a stem.
  { dx: 14.6, y: 168, c: [12.5, 171.6, 14, 169.8] },
  { dx: 15.1, y: 163 },
  { dx: 13.8, y: 160, c: [15, 161.6, 14.4, 160.5] },
  // The tower. Barely tapered — 0.7 of a unit over fifty — but never
  // parallel, because a parallel-sided tube is the one thing a lathe does
  // not naturally produce.
  { dx: 13.1, y: 128, c: [13.2, 150, 13.05, 138] },
  { dx: 13.6, y: 106, c: [13.15, 120, 13.4, 112] },
  // Cornice, then the wall head.
  { dx: 17.4, y: 100.6, c: [14.6, 104, 16.2, 101.6] },
  { dx: 17.9, y: 96.6 },
  { dx: 16.4, y: 93.4, c: [17.8, 95.2, 17, 93.8] },
  { dx: 17.2, y: 89.6, c: [16.4, 91.6, 16.9, 90.2] },
  { dx: 18.6, y: 82, c: [17.6, 86.4, 18.4, 83.6] },
]

const SIL = revolve(PROFILE)

/* ── the wall head ────────────────────────────────────────────
   RIM is the outside of the wall, BORE the inside; the difference is
   the thickness you can see across the cut top of each merlon. TOP is
   the plane the wall is cut off at, CREST the plane the merlons rise
   to. Both are planes, not lines — see `rimY`. */
const RIM = 18.6
const BORE = 14.2
const TOP = 82
const CREST = 68

/** Four merlons and three crenels, cut symmetrically about the axis. */
const MERLON_W = 7
const CRENEL_W = 3.05
const NEAR: readonly [number, number][] = [0, 1, 2, 3].map((i) => {
  const u0 = -RIM + 0.025 + i * (MERLON_W + CRENEL_W)
  return [u0, u0 + MERLON_W] as [number, number]
})
/** The far side shows only through the near gaps, so it is drawn to them. */
const FAR: readonly [number, number][] = [-10.05, 0, 10.05].map(
  (c) => [c - MERLON_W / 2, c + MERLON_W / 2] as [number, number],
)

function nearMerlon(u0: number, u1: number): string {
  return (
    `M${(CX + u0).toFixed(2)} ${rimY(u0, RIM, TOP, true).toFixed(2)} ` +
    `${rimRun(u0, u1, RIM, TOP, true, 4)} ` +
    `L${(CX + u1).toFixed(2)} ${rimY(u1, RIM, CREST, true).toFixed(2)} ` +
    `${rimRun(u1, u0, RIM, CREST, true, 4)} Z`
  )
}

/** Planted a unit inside the bore so its foot is never visible in a gap. */
function farMerlon(u0: number, u1: number): string {
  return (
    `M${(CX + u0).toFixed(2)} ${(TOP + 1).toFixed(2)} ` +
    `L${(CX + u0).toFixed(2)} ${rimY(u0, RIM, CREST, false).toFixed(2)} ` +
    `${rimRun(u0, u1, RIM, CREST, false, 4)} ` +
    `L${(CX + u1).toFixed(2)} ${(TOP + 1).toFixed(2)} Z`
  )
}

/** The cut top of a near merlon — the wall's thickness, seen from above. */
function merlonCap(u0: number, u1: number): string {
  return (
    `M${(CX + u0).toFixed(2)} ${rimY(u0, RIM, CREST, true).toFixed(2)} ` +
    `${rimRun(u0, u1, RIM, CREST, true, 4)} ` +
    `${rimRun(u1 * (BORE / RIM), u0 * (BORE / RIM), BORE, CREST, true, 4)} Z`
  )
}

const NEAR_PATHS = NEAR.map(([a, b]) => nearMerlon(a, b))
const FAR_PATHS = FAR.map(([a, b]) => farMerlon(a, b))
const CAP_PATHS = NEAR.map(([a, b]) => merlonCap(a, b))

export default function Piece(): ReactElement {
  return (
    <Turned d={SIL} w={W}>
      {/* Base arris and the shadow the plinth drops into the cove. */}
      <path
        d="M44.6 185.1A21 3.78 0 0 0 75.4 185.1"
        className="cw-k-line"
        strokeWidth={0.8}
        opacity={0.32}
      />
      <Collar rx={15.1} top={163} bot={168} lit={0.38} />

      {/* Grain up the tower. Two dark, one pale, none of them parallel. */}
      <g strokeLinecap="round" opacity={0.6}>
        <path className="cw-k-grain" d="M53.4 160C52.2 142 52.6 122 53.8 106" strokeWidth={0.7} opacity={0.3} />
        <path className="cw-k-grain" d="M66.8 161C68 143 67.6 123 66.4 107" strokeWidth={0.5} opacity={0.22} />
        <path className="cw-k-figure" d="M60.6 158C59.6 140 59.8 120 60.8 104" strokeWidth={1.6} opacity={0.14} />
      </g>

      {/* Cornice. It overhangs, so it drops a hard line onto the tower. */}
      <Collar rx={17.9} top={96.6} bot={100.6} lit={0.46} />
      <path
        d="M42.1 101.6A17.9 3.22 0 0 0 77.9 101.6"
        className="cw-k-line"
        strokeWidth={1.3}
        opacity={0.4}
      />

      {/* ── the wall head ────────────────────────────────────
          Wall top, bore, far merlons, near merlons — strictly back to
          front, because every one of those four occludes the one before
          it and any other order shows a seam. */}
      <Disc rx={RIM} y={TOP} lit={0.5} />
      <ellipse cx={CX} cy={TOP} rx={BORE} ry={BORE * SQUASH} className="cw-deep" />
      {/* the far inner wall catches a little of the lamp coming over the top */}
      <path
        d={`M${CX - BORE} ${TOP} A${BORE} ${BORE * SQUASH} 0 0 1 ${CX + BORE} ${TOP} Z`}
        className="cw-shade"
        opacity={0.55}
      />

      <g>
        {FAR_PATHS.map((d, i) => (
          <g key={i}>
            <path d={d} className="cw-shade" />
            <path d={d} fill="url(#cw-turn)" opacity={0.5} />
          </g>
        ))}
      </g>

      <g>
        {NEAR_PATHS.map((d, i) => (
          <g key={i}>
            <Wood d={d} grain={0.6} />
            <path d={d} className="cw-k-line" strokeWidth={0.6} opacity={0.3} />
          </g>
        ))}
        {CAP_PATHS.map((d, i) => (
          <g key={i}>
            <path d={d} className="cw-lit" opacity={0.44} />
            <path d={d} fill="url(#cw-turn)" opacity={0.4} />
            <path d={d} className="cw-k-line" strokeWidth={0.5} opacity={0.28} />
          </g>
        ))}
      </g>

      {/* Handled. The outer corner of the right-hand merlon has gone soft and
          pale, and kept the hairline of shadow every broken arris keeps. */}
      <path
        d="M76.9 71.4C77.9 72.4 78.4 73.8 78.4 75.2C77.4 74.2 76.6 72.9 76.3 71.6Z"
        className="cw-raw"
        opacity={0.6}
      />
      <path
        d="M76.9 71.4C77.9 72.4 78.4 73.8 78.4 75.2"
        className="cw-k-line"
        strokeWidth={0.5}
        opacity={0.34}
      />
      {/* and a matching rub on the plinth, where it is set down hardest */}
      <path
        d="M46.2 166.4C47.6 165.4 49.4 165 50.8 165.3C49.6 166.6 48 167.3 46.4 167.3Z"
        className="cw-raw"
        opacity={0.45}
      />
    </Turned>
  )
}
