/* ─────────────────────────────────────────────────────────────
   exploding_kitten — the loss condition.

   Read order the eye is meant to take: blast star → the cat's face
   (wide left eye, squeezed right eye, screaming mouth) → the lit fuse
   in the top right. Everything else is texture holding the plate down.

   Three plates only: red field, ink linework, gold/foil highlight.
   The gold blast star is duplicated by hand at translate(-2, 1.5) so
   the paper star sits off register on top of it — that misalignment is
   the whole reason this reads as printed rather than rendered.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE } from "../defs";

/* ── deterministic construction helpers ─────────────────────────
   Computed once at module load. No randomness, no render-time work. */

const BURST = { x: 120, y: 150 } as const;

/** One radiating wedge from the blast centre, in card coordinates. */
function wedge(aDeg: number, halfDeg: number, r: number): string {
  const rad = (d: number) => (d * Math.PI) / 180;
  const a0 = rad(aDeg - halfDeg);
  const a1 = rad(aDeg + halfDeg);
  const x0 = (BURST.x + Math.cos(a0) * r).toFixed(2);
  const y0 = (BURST.y + Math.sin(a0) * r).toFixed(2);
  const x1 = (BURST.x + Math.cos(a1) * r).toFixed(2);
  const y1 = (BURST.y + Math.sin(a1) * r).toFixed(2);
  return `M${BURST.x} ${BURST.y}L${x0} ${y0}L${x1} ${y1}Z`;
}

/* Uneven widths on purpose — evenly spaced rays look like a pie chart. */
const RAY_SPEC: ReadonlyArray<readonly [number, number]> = [
  [-96, 4.4],
  [-72, 2.2],
  [-51, 5.6],
  [-28, 2.8],
  [-6, 4.0],
  [16, 2.4],
  [38, 5.2],
  [59, 2.6],
  [82, 3.8],
  [104, 2.4],
  [127, 5.0],
  [148, 2.8],
  [170, 4.2],
  [-168, 2.4],
  [-140, 5.4],
  [-118, 2.6],
];
const RAYS = RAY_SPEC.map(([a, w]) => wedge(a, w, 330));

/** Jagged blast star. Radii are hand-listed so no two spikes match. */
function starPath(cx: number, cy: number, radii: readonly number[], phase: number): string {
  const n = radii.length;
  const pts = radii.map((r, i) => {
    const a = phase + (i / n) * Math.PI * 2;
    return `${(cx + Math.cos(a) * r).toFixed(2)} ${(cy + Math.sin(a) * r).toFixed(2)}`;
  });
  return `M${pts[0]}L${pts.slice(1).join("L")}Z`;
}

/* Fourteen points, not twenty: fewer and chunkier reads as a blast,
   more and thinner reads as a sun. */
const STAR_R = [134, 68, 110, 60, 140, 74, 102, 62, 130, 57, 116, 76, 106, 64];
const BLAST = starPath(BURST.x, BURST.y - 4, STAR_R, -1.42);
const BLAST_INNER = starPath(
  BURST.x,
  BURST.y - 4,
  STAR_R.map((r) => r * 0.84),
  -1.28,
);

/* ── the cat ────────────────────────────────────────────────────
   Drawn in a local frame centred on the muzzle, then placed. Ears are
   swept back by the blast; the skull is asymmetric because a
   symmetrical cat has no opinion about anything. */

/* One closed silhouette. The previous version's ears were drawn as a
   pair of thin swept curves whose two edges ran nearly parallel — at
   card size they came out as antennae, and at 60px they came out as
   nothing at all. These are proper triangles: each ear has a ~23-unit
   base on the skull and tapers to a blunt tip, so the head keeps a
   recognisable cat outline all the way down to a thumbnail. The fur
   notches are cut into the outline rather than scribbled on afterwards,
   and they are deep enough (11–12 units) to survive the ink filter. */
const HEAD = `M-27 -22
  C-34 -32 -46 -52 -52 -70
  C-53.5 -75 -49 -77.5 -45 -73
  C-36 -63 -24 -50 -15 -42
  C-9.5 -46 -3 -48.5 4 -48.5
  C11 -48.5 17.5 -46 23 -42
  C32 -50 44 -63 53 -73
  C57 -77.5 61.5 -75 60 -70
  C54 -52 42 -32 35 -22
  C43 -13 47 -1 45.5 10
  L57 15L45 21L55 30.5L41 33.5L46.5 44L33.5 37.5
  C26 44.5 13.5 47.5 0 47.5
  C-13.5 47.5 -26 44.5 -33.5 37.5
  L-46.5 44L-41 33.5L-55 30.5L-45 21L-57 15
  C-54.5 -1 -43 -13 -27 -22Z`;

/* The two eyes are deliberately not the same organ. The left is blown
   wide open — a near-circle with the white showing all the way round a
   pupil that has shrunk and floated up. The right is crushed into a
   flat almond by the brow above it. Mirror-image eyes read as a mask;
   these read as one animal having two separate bad thoughts. */
const EYE_L = `M-19 -19C-9.5 -19 -3 -12.2 -3 -3.6C-3 5 -9.5 11.6 -19 11.6
  C-28.5 11.6 -35.5 5 -35.5 -3.6C-35.5 -12.2 -28.5 -19 -19 -19Z`;
const EYE_R = `M5 -4.6C11 -13.4 24 -13.8 29 -6.2C24.6 -0.4 11.4 0.2 5 -4.6Z`;
/* Small, high, off-centre — terror, not curiosity. */
const PUPIL_L = `M-21 -12.8C-18.3 -12.8 -16.2 -10.6 -16.2 -7.9C-16.2 -5.2 -18.3 -3 -21 -3
  C-23.7 -3 -25.8 -5.2 -25.8 -7.9C-25.8 -10.6 -23.7 -12.8 -21 -12.8Z`;
/* Squeezed to a vertical slit by the wince around it. */
const PUPIL_R = `M17.6 -10.4C19.7 -10.4 20.9 -8.6 20.9 -6.4C20.9 -4.2 19.7 -2.6 17.6 -2.6
  C15.5 -2.6 14.3 -4.2 14.3 -6.4C14.3 -8.6 15.5 -10.4 17.6 -10.4Z`;

/* Brows: left flung vertically up the forehead, right driven down into
   the eye it is crushing. That mismatch is the entire joke of the face,
   so the two paths share neither angle nor length. */
const BROW_L = `M-31 -16.5C-27.5 -28 -19.5 -34.5 -10.5 -33.5`;
const BROW_R = `M31 -27.5C23.5 -23.5 15.5 -20 9 -16.5`;

const MOUTH = `M-17.5 13.5C-9 8.5 11 8.5 19.5 14C21.5 27 11 38.5 1 38.5
  C-10 38.5 -19.5 26.5 -17.5 13.5Z`;
const TONGUE = `M-5 27.5C-1 24.5 6 25 8.5 29C10.5 32.5 7 37.5 1.5 37.5C-3.5 37.5 -8 31 -5 27.5Z`;
const FANG_L = `M-14 12.5L-8 12L-11.5 21.5Z`;
const FANG_R = `M15.5 12.5L9.5 11.5L13.5 21.5Z`;

/* Held inside |x| ≤ 84 local — at scale 1.1 that lands at x 20→220, so
   the tips stop inside the safe area instead of being sliced flat by
   the frame's face clip at x 8 / 232. */
const WHISKERS = `M-46 12C-62 5 -78 6 -91 15M-45 22C-60 23 -74 30 -85 39
  M46 11C62 4 78 5 91 14M45 21C60 22 74 29 85 38`;

/* Fuse leaving the skull between the ears and climbing clear of them.
   The old route left at (4,-50) and ran right at (42,-76.5), which with
   real ears now means straight through the right one. */
const FUSE = `M2 -47C-4 -64 10 -80 28 -84C41 -87 42 -95 32 -97`;
const SPARK = `M0 -15L4.6 -5L15 -0.5L4.6 4L0 14.5L-4.6 4L-15 -0.5L-4.6 -5Z`;
const SPARK_INNER = `M0 -7.5L2.4 -2.6L7.6 -0.3L2.4 2.1L0 7.4L-2.4 2.1L-7.6 -0.3L-2.4 -2.6Z`;

/* Debris — chipped paw prints and shrapnel flung clear of the head. */
const SHRAPNEL = [
  "M54 68L66 61L63 76L52 79Z",
  "M180 196L193 190L190 206L177 203Z",
  "M46 214L58 208L57 224L44 221Z",
  "M196 116L207 111L204 125L193 122Z",
  "M84 252L96 246L95 261L82 258Z",
  /* was at 158,62 — dead centre of the spark. Moved clear. */
  "M56 46L67 40L65 55L53 52Z",
];

function PawMark({ x, y, r }: { x: number; y: number; r: number }): ReactElement {
  return (
    <g transform={`translate(${x} ${y}) rotate(${r}) scale(0.85)`}>
      <path d="M-6.5 2.5C-5 -1.5 5 -1.5 6.5 2.5C7.7 5.7 5.2 8.6 0 8.6C-5.2 8.6 -7.7 5.7 -6.5 2.5Z" />
      <path d="M-7.4 -3.2C-6.2 -5.4 -3.6 -5.4 -2.9 -3C-2.3 -0.9 -3.8 0.7 -5.6 0.3C-7.4 -0.1 -8.1 -1.9 -7.4 -3.2Z" />
      <path d="M-1.6 -6.4C-0.7 -8.8 2 -8.8 2.7 -6.3C3.3 -4.1 1.8 -2.5 -0.1 -3C-1.9 -3.5 -2.3 -5 -1.6 -6.4Z" />
      <path d="M5 -3.6C6.3 -5.7 8.8 -5.4 9.2 -3C9.5 -0.9 7.8 0.5 6.1 -0.1C4.4 -0.7 4.2 -2.3 5 -3.6Z" />
    </g>
  );
}

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate 1: the red field ───────────────────────────── */}
      <rect x={0} y={0} width={240} height={300} fill={PALETTE.red} filter="url(#ek-grain)" />

      {/* tone: dense screen bottom-right, thinning up-left */}
      <rect x={0} y={150} width={240} height={150} fill="url(#ek-halftone)" opacity={0.16} />
      <rect x={0} y={228} width={240} height={72} fill="url(#ek-halftone)" opacity={0.14} />
      <rect x={0} y={0} width={240} height={92} fill="url(#ek-halftone-fine)" opacity={0.1} />

      {/* ── plate 2: radiating ink rays behind everything ────── */}
      <g fill={PALETTE.ink} opacity={0.26}>
        {RAYS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>

      {/* ── the blast star, misregistered on purpose ─────────── */}
      <g>
        {/* gold plate, laid down first and 2px off */}
        <path d={BLAST} fill={PALETTE.gold} transform="translate(-2 1.5)" opacity={0.95} />
        {/* paper plate on top — the fringe is the gold peeking left/top */}
        <path d={BLAST} fill={PALETTE.paper} />
        <path
          d={BLAST_INNER}
          fill="none"
          stroke={PALETTE.red}
          strokeWidth={2.2}
          opacity={0.5}
          filter="url(#ek-ink)"
        />
        <path
          d={BLAST}
          fill="none"
          stroke={PALETTE.ink}
          strokeWidth={3.4}
          strokeLinejoin="round"
          filter="url(#ek-ink)"
        />
      </g>

      {/* Red screen laid across the lower half. It is invisible where it
          crosses the red field and only develops inside the white star —
          one rect, and the star stops being bare paper. */}
      <path
        d="M20 172C40 206 74 226 120 228C166 230 202 212 221 178C216 228 172 268 120 268
           C68 268 24 224 20 172Z"
        fill="url(#ek-halftone-red)"
        opacity={0.5}
      />
      <path
        d="M92 44C116 30 150 36 166 58C144 50 118 52 100 64C90 70 84 50 92 44Z"
        fill="url(#ek-halftone-red)"
        opacity={0.4}
      />

      {/* concussion ring — thin, broken, sits just outside the star */}
      <g
        fill="none"
        stroke={PALETTE.ink}
        strokeWidth={2.6}
        strokeLinecap="round"
        opacity={0.55}
        filter="url(#ek-ink)"
      >
        <path d="M28 108C36 62 78 30 124 32C160 33.5 190 54 202 84" />
        <path d="M214 122C222 168 200 218 160 244" />
        <path d="M96 268C62 258 34 228 24 194" />
      </g>

      {/* Scorch pooled under and behind the skull. Without it the foil
          head — which carries a near-white band through its middle —
          sits on the paper-white star with nothing but a keyline
          between them, and the silhouette collapses at thumbnail size.
          Offset down-right so it reads as cast, not as an outline. */}
      <path
        d="M120 84C170 84 202 118 202 166C202 214 166 246 120 246
           C74 246 38 214 38 166C38 118 70 84 120 84Z"
        fill="url(#ek-halftone)"
        opacity={0.38}
        transform="translate(8 10)"
      />

      {/* ── the cat ──────────────────────────────────────────── */}
      <g transform="translate(120 162) scale(1.1)">
        {/* off-register red under-plate for the skull — the fringe is the point */}
        <path d={HEAD} fill={PALETTE.red} transform="translate(-2.6 1.8)" />

        <g filter="url(#ek-ink)">
          {/* skull in foil */}
          <path
            d={HEAD}
            fill="url(#ek-foil)"
            stroke={PALETTE.ink}
            strokeWidth={3.6}
            strokeLinejoin="round"
          />

          {/* inner ears — the only red inside the head. Redrawn as
              triangles inset inside the new ear triangles; the old pair
              were slivers fitted to the old sliver ears. */}
          <path
            d="M-28 -31C-33 -41 -38 -53 -41.5 -62C-36 -55 -27 -47.5 -21 -43
               C-24 -39 -26.5 -34.5 -28 -31Z"
            fill={PALETTE.red}
            stroke={PALETTE.ink}
            strokeWidth={2}
            strokeLinejoin="round"
          />
          <path
            d="M36 -30.5C40.5 -40 46 -52.5 49.5 -62C44.5 -55 35.5 -47.5 29 -43
               C31.5 -39 34.5 -34.5 36 -30.5Z"
            fill={PALETTE.red}
            stroke={PALETTE.ink}
            strokeWidth={2}
            strokeLinejoin="round"
          />

          {/* eyes */}
          <path d={EYE_L} fill={PALETTE.paper} stroke={PALETTE.ink} strokeWidth={2.8} />
          <path d={EYE_R} fill={PALETTE.paper} stroke={PALETTE.ink} strokeWidth={2.8} />
          <path d={PUPIL_L} fill={PALETTE.ink} />
          <path d={PUPIL_R} fill={PALETTE.ink} />

          {/* brows: alarm on the left, fury on the right */}
          <g
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={4}
            strokeLinecap="round"
          >
            <path d={BROW_L} />
            <path d={BROW_R} />
          </g>

          {/* nose */}
          <path
            d="M-5.5 6.5L5.5 6.5C6.8 6.5 7.2 8 6.2 9L1.4 13C0.6 13.7 -0.6 13.7 -1.4 13L-6.2 9
               C-7.2 8 -6.8 6.5 -5.5 6.5Z"
            fill={PALETTE.red}
            stroke={PALETTE.ink}
            strokeWidth={1.8}
            strokeLinejoin="round"
          />

          {/* screaming mouth */}
          <path d={MOUTH} fill={PALETTE.ink} stroke={PALETTE.ink} strokeWidth={2.4} strokeLinejoin="round" />
          <path d={TONGUE} fill={PALETTE.red} />
          <path d={FANG_L} fill={PALETTE.paper} />
          <path d={FANG_R} fill={PALETTE.paper} />

          {/* whiskers, blown back */}
          <path
            d={WHISKERS}
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={2.4}
            strokeLinecap="round"
          />
        </g>

        {/* fuse + spark, drawn last so they sit over the ear */}
        <g fill="none" strokeLinecap="round" filter="url(#ek-ink)">
          <path d={FUSE} stroke={PALETTE.ink} strokeWidth={8.5} />
          <path d={FUSE} stroke={PALETTE.gold} strokeWidth={2.6} opacity={0.6} />
        </g>
        <g transform="translate(32 -97) scale(1.25)">
          <path d={SPARK} fill={PALETTE.ink} transform="translate(-2 1.5) scale(1.15)" />
          <path d={SPARK} fill={PALETTE.gold} filter="url(#ek-ink)" />
          <path d={SPARK_INNER} fill={PALETTE.paper} />
        </g>
      </g>

      {/* ── debris ───────────────────────────────────────────── */}
      <g fill={PALETTE.ink} opacity={0.9}>
        {SHRAPNEL.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      <g fill={PALETTE.ink} filter="url(#ek-ink)">
        <PawMark x={62} y={104} r={-34} />
        {/* was at 186,158 — that stamped an ink paw print on the cat's
            own cheek, since debris is drawn after the head. */}
        <PawMark x={202} y={206} r={28} />
        <PawMark x={70} y={244} r={14} />
      </g>

      {/* ── warning chevrons, bottom-left, clear of the corner pip ── */}
      <g transform="translate(30 258)">
        <path
          d="M0 0H128L118 20H-10Z"
          fill={PALETTE.gold}
          transform="translate(-2 1.5)"
          opacity={0.9}
        />
        <g filter="url(#ek-ink)">
          <path d="M0 0H128L118 20H-10Z" fill={PALETTE.ink} />
          <g fill={PALETTE.gold}>
            <path d="M8 3L22 3L12 17L-2 17Z" />
            <path d="M32 3L46 3L36 17L22 17Z" />
            <path d="M56 3L70 3L60 17L46 17Z" />
            <path d="M80 3L94 3L84 17L70 17Z" />
            <path d="M104 3L118 3L108 17L94 17Z" />
          </g>
        </g>
      </g>
    </g>
  );
}
