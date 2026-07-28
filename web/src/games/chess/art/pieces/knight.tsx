/* ─────────────────────────────────────────────────────────────
   KNIGHT — 148 tall, base 24

   The only carved piece in the set, and the one that decides whether
   the whole set looks hand-made. Everything else here is a turning:
   hold a gouge against a spinning blank and you cannot get it very
   wrong. A knight is cut by hand with a chisel, and a knight that has
   been drawn as a silhouette — one smooth horse-shaped outline with a
   dot for an eye — is instantly and obviously not that. It is a glyph.
   So this file is built the way the carving is built.

   **It is two objects, not one.** A turned stem up to the collar at
   y=132, and a carved head socketed into it — the joint a two-part
   knight really has. The head is authored at full size in its own
   coordinates and then set into the stem by a single scale about its
   ear tips, which is the only way to tune head-to-body proportion
   without re-authoring forty interior paths. The first pass had it at
   1.0 and the knight read as a horse-head sculpture with a chess base
   glued underneath: the head has to be about six tenths of the piece,
   not seven.

   **It is faceted, not shaded.** A chisel leaves flats. The cheek, the
   jowl, the muzzle's top plane, the brow, the planes down the neck —
   each is a polygon with a hard arris where it meets its neighbour,
   and the arrises are drawn twice, once as the lit edge and once as
   the shadow immediately under it. Smooth gradients over all of this
   would give a cast bronze knight, which is a different object.

   **The face is on the dark side, and has to be readable anyway.** The
   lamp is up and to the right, the horse looks left, so his entire
   face is the shaded flank — which is dramatic and correct and would
   normally lose the eye altogether. The fix is the one a painter would
   use: bounce. The board is a pale lacquered surface right underneath
   him, and it throws a warm, soft, upward light back onto the muzzle
   and the underside of the jaw. That wash is what keeps the muzzle
   from going to a black wedge, and the eye stays legible because the
   socket around it is darker than the bounce and the catchlight is
   brighter than anything else on the face.

   **Both colours face left.** A mirrored knight would need its whole
   lighting pass rebuilt — the lit flank becomes the shaded one — and
   two knight files is exactly how a set stops looking like a set.

   Wear is on the near ear, which on every wooden knight ever made is
   the first thing to go.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from 'react'
import { Collar, foot, revolve, Turned, Wood, type Station } from '../defs'

const W = 24

/* The turned half. It stops at the collar the carving is socketed into,
   and it has one more bead than the other pieces' stems because there is
   less shaft here to look at — the head starts eighty units up. */
const STEM: Station[] = [
  ...foot(W),
  // One bead and one waist, and no more than that. The stem is short and
  // every extra ring on it reads as a ripple rather than as a turning.
  { dx: 10.4, y: 166, c: [11.6, 171, 10.6, 168] },
  { dx: 11.8, y: 161, c: [10.3, 164, 11.2, 162] },
  { dx: 8.8, y: 156, c: [11.8, 159, 10, 157] },
  { dx: 8.2, y: 145, c: [8.5, 151, 8.2, 148] },
  { dx: 12.4, y: 137, c: [8.4, 141, 10.8, 138] },
  { dx: 12.9, y: 132 },
]

/**
 * How the carved head is set into the turned stem.
 *
 * Scales about the ear tips at (60, 48), so the piece keeps its 148 height
 * whatever this is tuned to, and the head's foot moves up or down the stem
 * instead. At 0.86 the head runs 48→137 and the stem gets 59 units of its own.
 */
const SET_IN = 'translate(60 48) scale(0.86) translate(-60 -48)'

/* ── the head ─────────────────────────────────────────────────
   Read anticlockwise from the throat: up the front of the neck, over
   the jaw, round the chin and the muzzle, up the dish of the face to
   the brow, up and down the near ear, the notch, up and down the far
   ear, then the whole length of the mane down to the collar.

   Two things in here are doing more work than they look like they are.
   The five cusps down the mane — points where the tangent reverses
   rather than turning smoothly — are what make it hair; smooth it out
   and it becomes a fin. And the far ear's tip is *higher* on the screen
   than the near ear's, by one and a half units, because it is further
   away in a projection that steps back and up. Level ears kill the
   depth of the whole head. */
const HEAD = `M46 151
C45.5 140 41 128 36.4 121
C34.4 117.4 32 113.8 30.6 110
C29.6 106 28.8 102.4 28.4 99
C28 95.6 27.4 92.2 27.3 89.4
C27.5 86.4 28.9 84.4 31.2 83.2
C34.2 78.8 37.8 73.4 41.2 68
C42.6 65.2 44 63 45.8 61.2
C46.8 57 48.4 53.2 50 49.4
C51.9 54.2 53 57.6 53.8 60.8
C54.6 58.6 55.2 56 56.2 53.6
C57.2 51.2 58.4 49 59.6 48
C61.6 51.6 62.9 55.6 63.6 60
C66.4 63 69 66.6 70.8 71
C73.2 74 74 77 72.8 80
C75.6 82.6 76.8 85.8 75.6 89.2
C78.4 92.2 79.6 95.6 78.4 99.2
C81 102.8 82 106.6 80.8 110.2
C83 114.2 83.8 118.4 83 122.4
C82.4 132 80.2 142 76 151
C68 148 54 148 46 151 Z`

const SIL = revolve(STEM)

/** The five chisel cuts down the mane, and the ridge each one leaves. */
const MANE_CUTS: readonly string[] = [
  'M67.2 66.8C69.6 70.2 71.6 75.2 72.6 79.8',
  'M69.6 76.2C71.8 80.2 74.2 85.2 75.4 88.8',
  'M72.2 86.2C74.6 90.2 77 95.2 78.2 98.8',
  'M74.6 96.8C77 101.2 79.4 106.2 80.5 109.8',
  'M77 108.2C79.4 113.2 82 118.2 82.8 121.8',
]

export default function Piece(): ReactElement {
  return (
    <Turned d={SIL} w={W}>
      {/* ── the turned half ────────────────────────────────── */}
      <path
        d="M39 185.1A21 3.78 0 0 0 81 185.1"
        className="cw-k-line"
        strokeWidth={0.8}
        opacity={0.32}
      />
      <path
        d="M44.2 176.3A15.8 2.84 0 0 0 75.8 176.3"
        className="cw-k-lit"
        strokeWidth={0.9}
        opacity={0.3}
      />
      <path
        d="M48.2 161A11.8 2.12 0 0 0 71.8 161"
        className="cw-k-lit"
        strokeWidth={0.8}
        opacity={0.28}
      />
      <path
        d="M49 163.6A11 1.98 0 0 0 71 163.6"
        className="cw-k-line"
        strokeWidth={1}
        opacity={0.34}
      />
      <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
        <path d="M54.6 172C53.4 164 53.4 154 54.8 144" strokeWidth={0.6} opacity={0.28} />
        <path d="M65.8 173C67 164 67 154 65.6 144" strokeWidth={0.45} opacity={0.2} />
      </g>

      {/* ── the carving ──────────────────────────────────────
          Authored at full size in head coordinates and set into the
          stem by one scale. Every facet is clipped to the silhouette
          rather than fitted to it by hand: a chisel plane that runs off
          the edge of the wood is a plane, and one that stops a unit
          short is a sticker. */}
      <g transform={SET_IN}>
        <Wood d={HEAD} />
        <path d={HEAD} fill="url(#cw-floor)" opacity={0.55} />

          {/* ── bounce ───────────────────────────────────────
              Warm light off the board, thrown back up onto everything
              facing down and left. It is the only reason the muzzle is
              not a black wedge, and it goes in first so the facets cut
              into it rather than sitting on it. */}
          <path
            d="M28.6 99C29.4 104 31.2 108.6 33.8 112.4C35.4 115 36.2 118 36.6 121
               C35.2 116.2 33.2 111.6 31.6 108C30.4 105.4 29 102.2 28.6 99Z"
            className="cw-lit"
            opacity={0.17}
          />
          <path
            d="M27.8 92.6C29.2 92.4 31 93 32.8 94.2C34.8 95.6 36.4 97.6 37.4 99.8
               C35.6 97.6 33.4 95.8 31 94.8C29.8 94.3 28.5 93.6 27.8 92.6Z"
            className="cw-lit"
            opacity={0.14}
          />

          {/* ── the neck ─────────────────────────────────────
              Three planes and one arris. The lit sliver runs under the
              mane, the front of the neck falls away, and the throat is
              the darkest wood on the piece. The arris between the first
              two is a pair of lines, light over dark, because that is
              what a chisel edge looks like from a chair. */}
          <path
            d="M69.6 79C70.2 86 71.6 92 73 104C75.8 117 77 132 76.2 147
               C79.2 139 80.6 130 80.6 118C79.2 102 75.4 88 72.4 78Z"
            className="cw-lit"
            opacity={0.2}
          />
          <path
            d="M39.8 125C42.6 132.6 45.6 140 48 147C50 146.6 51.8 146.6 53.2 146.8
               C50.2 139.4 46.8 131.6 43 125.4Z"
            className="cw-shade"
            opacity={0.4}
          />
          <path
            d="M43.4 129C45.2 135 47.6 140.6 50.8 144C52.8 146 55 147.2 57.2 147.8
               C52.6 148 48.6 147 46.4 145.4C45.2 144.4 44.4 137.6 43.4 129Z"
            className="cw-shade"
            opacity={0.22}
          />
          <g strokeLinecap="round">
            <path
              className="cw-k-lit"
              d="M65 64.6C67.8 76.4 70.6 92 72.6 110C73.6 120 74 133 72.6 148"
              strokeWidth={0.7}
              opacity={0.22}
            />
            <path
              className="cw-k-line"
              d="M63.8 65.4C66.6 77 69.4 92.6 71.4 110.4C72.4 120.4 72.8 133 71.4 148.4"
              strokeWidth={0.5}
              opacity={0.22}
            />
          </g>
          <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
            <path d="M56 148C55 134 56.2 120 59.6 108" strokeWidth={0.55} opacity={0.22} />
            <path d="M49.6 146C48.2 134 48.4 122 50.6 112" strokeWidth={0.42} opacity={0.18} />
          </g>

          {/* ── the mane ─────────────────────────────────────
              A band along the crest, then five cuts across it. Each cut
              is a dark groove with a lit ridge on its lamp side; the
              ridge alone reads as scratches and the groove alone reads
              as a seam. */}
          <path
            d="M63.6 60C66.4 63 69 66.6 70.8 71C73.2 74 74 77 72.8 80
               C75.6 82.6 76.8 85.8 75.6 89.2C78.4 92.2 79.6 95.6 78.4 99.2
               C81 102.8 82 106.6 80.8 110.2C83 114.2 83.8 118.4 83 122.4
               C80.2 118.4 77.6 110.4 75.6 100.4C73.4 89.4 69.4 74.4 63.6 60Z"
            className="cw-lit"
            opacity={0.15}
          />
          <g strokeLinecap="round">
            {MANE_CUTS.map((d, i) => (
              <path key={`c${i}`} className="cw-k-line" d={d} strokeWidth={1.1} opacity={0.42} />
            ))}
            <g transform="translate(-1.1 1.3)">
              {MANE_CUTS.map((d, i) => (
                <path key={`r${i}`} className="cw-k-lit" d={d} strokeWidth={0.8} opacity={0.3} />
              ))}
            </g>
          </g>

          {/* ── the ears ─────────────────────────────────────
              The far one is filled flat with shade so it drops behind;
              the near one keeps a hollow and a lit leading edge. */}
          <path
            d="M56.2 53.6C57.2 51.2 58.4 49 59.6 48C61.6 51.6 62.9 55.6 63.6 60
               C61.2 57.6 58.2 55.6 56.2 53.6Z"
            className="cw-shade"
            opacity={0.45}
          />
          <path
            d="M59.6 48C61.6 51.6 62.9 55.6 63.6 60"
            className="cw-k-lit"
            strokeWidth={0.7}
            opacity={0.3}
          />
          <path
            d="M48 55.6C48.7 52.8 49.4 50.7 50 49.4C50.7 51.6 51.4 54.4 51.8 56.8
               C50.5 57 49.1 56.6 48 55.6Z"
            className="cw-deep"
            opacity={0.55}
          />
          <path
            d="M46 61.4C47 57 48.4 53 50 49.4"
            className="cw-k-lit"
            strokeWidth={0.7}
            opacity={0.34}
          />
          <path
            d="M46.4 62.4C47.4 58.6 48.4 55 49.6 51.6"
            className="cw-k-line"
            strokeWidth={0.8}
            opacity={0.32}
          />

          {/* ── the brow and the eye ─────────────────────────
              Ridge, socket, almond, pupil, catchlight. Take any one of
              the five out and it goes back to being a dot. */}
          <path
            d="M43 70C45.2 66 49 63.6 53.2 63.8"
            className="cw-k-lit"
            strokeWidth={1.2}
            opacity={0.38}
          />
          <path
            d="M43.4 71.6C45.6 67.6 49.4 65.2 53.6 65.4"
            className="cw-k-line"
            strokeWidth={0.9}
            opacity={0.38}
          />
          <path
            d="M43.8 76.4C44.6 71.4 48 67.8 52.2 68C53 73 49.8 77.4 45.6 78Z"
            className="cw-deep"
            opacity={0.5}
          />
          <path
            d="M45.3 73.8C46.3 71 49.3 69.4 51.7 70.2C51.1 73 48.5 75 45.9 74.8Z"
            className="cw-line"
          />
          <ellipse cx={48.6} cy={72.1} rx={1.4} ry={1.7} transform="rotate(-24 48.6 72.1)" className="cw-deep" />
          <circle cx={49.5} cy={71.1} r={0.62} className="cw-lit" />
          <path
            d="M45.8 75C47.8 75.2 50.2 74 51.6 72"
            className="cw-k-lit"
            strokeWidth={0.55}
            opacity={0.3}
          />

          {/* ── the cheek and the jowl ───────────────────────
              The cheekbone is a raised flat and the jowl behind it falls
              into the throat. The arris between them, from under the eye
              to the corner of the jaw, is the strongest edge on the face
              after the brow. */}
          <path
            d="M39.6 100.6C41.8 94.4 46.2 90.6 50.8 90.8C49.6 96.8 45.6 102.2 40.8 104Z"
            className="cw-lit"
            opacity={0.16}
          />
          <path
            d="M37 121.4C36.2 115.4 34.4 110 31.4 105.4C35 107.4 38.4 111 40.8 115.8
               C43.4 120.8 44.4 126.4 43.8 131.4Z"
            className="cw-shade"
            opacity={0.3}
          />
          <g strokeLinecap="round">
            <path className="cw-k-lit" d="M44 88.8C47.2 93 48.8 99 48.4 106" strokeWidth={0.7} opacity={0.26} />
            <path className="cw-k-line" d="M43 89.6C46.2 94 47.8 100 47.4 107" strokeWidth={0.55} opacity={0.26} />
          </g>
          <g className="cw-k-grain" strokeLinecap="round" opacity={0.6}>
            <path d="M40 108C39.2 100 40.2 92 43 84" strokeWidth={0.45} opacity={0.2} />
            <path d="M35 104C34.2 98 35 92 37 87" strokeWidth={0.38} opacity={0.16} />
          </g>

          {/* ── the muzzle ───────────────────────────────────
              Top plane lit, front plane in shade, and the arris between
              them running back along the side of the nose. The mouth is
              one cut with a lit lip under it; the nostril is a comma
              with a flared upper edge, because a nostril drawn as a
              plain oval reads as a drilled hole. */}
          <path
            d="M29.6 86C32.2 84 35.4 82.8 38.4 82.6C36.6 86 33.6 88.6 30.4 90
               C29.6 88.8 29.2 87.2 29.6 86Z"
            className="cw-lit"
            opacity={0.18}
          />
          <path
            d="M27.8 91.6C28.2 95.4 29 98.6 30.4 101.6C29.2 98.6 28.6 95 28.6 91.8Z"
            className="cw-shade"
            opacity={0.4}
          />
          <g strokeLinecap="round">
            <path className="cw-k-lit" d="M30.6 100L36.6 91.4L40 82.4" strokeWidth={0.6} opacity={0.26} />
            <path className="cw-k-line" d="M31.8 101.4L37.8 92.6L41.2 83.6" strokeWidth={0.5} opacity={0.22} />
          </g>
          <path
            d="M29.8 89.4C31.4 88.4 33 89.2 33.2 90.8C33.4 92.5 32 93.5 30.6 92.9
               C29.5 92.4 29.1 90.8 29.8 89.4Z"
            className="cw-deep"
          />
          <path
            d="M31.4 88.8C32.7 88.9 33.6 89.8 33.8 91"
            className="cw-k-lit"
            strokeWidth={0.6}
            opacity={0.4}
          />
          <path
            d="M28.6 95.4C30.8 96.6 33.2 97.4 35.6 97.6"
            className="cw-k-line"
            strokeWidth={0.9}
            opacity={0.48}
          />
          <path
            d="M28.9 96.9C31 97.9 33.2 98.5 35.2 98.7"
            className="cw-k-lit"
            strokeWidth={0.6}
            opacity={0.3}
          />
          <path
            d="M29.4 99C30.4 101 32 102.4 34 103.2"
            className="cw-k-lit"
            strokeWidth={0.7}
            opacity={0.26}
          />

          {/* Chipped. Nobody has ever owned a wooden knight with both
              ears intact; this one lost the near tip and the break was
              never sealed, so it sits paler and drier than the surface
              around it. */}
          <path
            d="M49.3 52.2C49.6 50.6 49.8 49.8 50 49.4C50.6 50.7 51 51.9 51.2 52.9Z"
            className="cw-raw"
            opacity={0.6}
          />
          <path
            d="M49.3 52.2C49.6 50.6 49.8 49.8 50 49.4"
            className="cw-k-line"
            strokeWidth={0.45}
            opacity={0.4}
          />
          {/* and the nose, rubbed pale by two hundred games of being
              picked up by it */}
          <ellipse
            cx={31}
            cy={91}
            rx={2.4}
            ry={3.6}
            transform="rotate(-14 31 91)"
            className="cw-raw"
            opacity={0.18}
          />
        {/* The carving's own contour. It cannot come from `Turned`, which
            only knows the turned half — and it wants to be a hair heavier
            than a turning's, because a chisel leaves a harder edge than a
            gouge. */}
        <path d={HEAD} className="cw-k-line" strokeWidth={1.05} opacity={0.34} />
      </g>

      {/* ── the joint ────────────────────────────────────────
          The collar goes on last, over the carving's foot: it is the band
          that hides the socket. Capless, because its top face would be
          painted straight across the neck standing in it. */}
      <Collar rx={12.9} top={132} bot={137.5} cap={false} />
      <path
        d="M48.6 133.4C53 131.8 67 131.8 72.4 133.8C67 132.8 54.4 132.8 49.6 134.6Z"
        className="cw-deep"
        opacity={0.42}
      />
    </Turned>
  )
}
