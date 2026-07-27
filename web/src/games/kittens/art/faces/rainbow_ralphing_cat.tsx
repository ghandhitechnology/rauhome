/* ─────────────────────────────────────────────────────────────
   rainbow_ralphing_cat — delighted, mid-heave

   Second pass. The first one hung the maw off the side of the skull at
   eye level, which at card size reads as a cat holding a red ball in
   its cheek — the mouth has to be on the MUZZLE, below the nose, or it
   is not a mouth. So: eyes and brows are shoved up into the top third
   of the head, the muzzle is pushed right, and the whole lower right
   quadrant of the face is jaw. The jaw still overshoots the skull
   outline on purpose, because an opening contained inside a silhouette
   reads as a hole punched in it.

   The other fix is contrast. A paper-white cat on paper stock has no
   silhouette at 60px, so the coat carries a halftone screen and the
   head sits on an ink sunburst.

   Draw order matters: jaw → tongue → rainbow → upper lip and fangs
   redrawn on top. That last step is what makes the arc read as coming
   *out of* the cat instead of being pasted next to it.

   The joke is that it is having a wonderful time. Eyes screwed shut in
   pleasure, brows up, ears pinned back, paws braced.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* Seven boundary curves; the six bands are the gaps between them.
   [start-y @x98, ctrl1-y @x146, ctrl2-y @x200, end-y @x252] — the
   x stations are fixed so every band stays parallel through the arc. */
const EDGE: readonly [number, number, number, number][] = [
  [172, 148, 38, 4],
  [178, 157, 59, 28],
  [184, 166, 81, 53],
  [190, 175, 102, 77],
  [196, 184, 124, 102],
  [202, 193, 146, 127],
  [208, 202, 168, 152],
];

const BAND_INK = [
  PALETTE.red,
  PALETTE.gold,
  PALETTE.green,
  PALETTE.blue,
  PALETTE.violet,
  PALETTE.pink,
] as const;

function edgePath(i: number): string {
  const [s, a, b, e] = EDGE[i]!;
  return `M98 ${s} C146 ${a}, 200 ${b}, 252 ${e}`;
}

/** Closed ribbon between two boundaries — the second curve reversed
    (endpoints swapped, control points swapped) so the fill has no twist. */
function spanPath(i: number, j: number): string {
  const [s0, a0, b0, e0] = EDGE[i]!;
  const [s1, a1, b1, e1] = EDGE[j]!;
  return (
    `M98 ${s0} C146 ${a0}, 200 ${b0}, 252 ${e0} ` +
    `L252 ${e1} C200 ${b1}, 146 ${a1}, 98 ${s1} Z`
  );
}

function bandPath(i: number): string {
  return spanPath(i, i + 1);
}

/* Density behind the subject, same device the rest of the deck uses.
   Ink rather than an accent, so the stream stays the only loud thing.
   Computed once at module load — deterministic. */
const BURST: readonly string[] = Array.from({ length: 20 }, (_, i) => {
  const step = (Math.PI * 2) / 20;
  const a0 = i * step;
  const a1 = a0 + step * 0.46;
  const R = 360;
  const p = (a: number) =>
    `${(72 + Math.cos(a) * R).toFixed(1)} ${(190 + Math.sin(a) * R).toFixed(1)}`;
  return `M72 190 L${p(a0)} L${p(a1)} Z`;
});

/* Sparkles: [x, y, size, rotation]. Hand-placed clear of both pips. */
const SPARK: readonly [number, number, number, number][] = [
  [148, 46, 9, 12],
  [186, 92, 6.5, -20],
  [206, 34, 5, 30],
  [126, 112, 5.5, 8],
  [166, 150, 7, -14],
  [88, 84, 6.5, 22],
  [46, 58, 5, -8],
  [62, 120, 4, 16],
  [30, 108, 3.4, -24],
  [110, 62, 4.2, 34],
];

/* The head. Ears swept back and outward, the way a cat's go when
   something is about to happen. */
const SKULL =
  "M-44 2 C-44 -14 -36 -27 -23 -33 L-41 -60 C-43.5 -64 -38.5 -68 -34 -65 " +
  "L-8 -48 C-2.6 -49.4 2.6 -49.4 8 -48 L31 -66 C35 -69 40.5 -65.5 38 -61 " +
  "L23 -33 C36 -27 44 -14 44 2 C44 24 32 41 16 46 C6 49 -6 49 -16 46 " +
  "C-32 41 -44 24 -44 2 Z";

/* The maw. Hinged at a cusp on the muzzle at (-6 -2) — that corner is
   what makes it a mouth rather than an oval — and running out past the
   skull's right edge (x 44) to x 62. */
const MAW =
  "M-6 -2 C2 -20 30 -24 46 -12 C62 0 62 24 46 34 C28 45 2 36 -6 18 " +
  "C-11 9 -10 4 -6 -2 Z";

/* Chin, hung below the maw and outside the skull for the same reason. */
const CHIN = "M-6 18 C2 34 22 42 46 34 C50 46 38 58 22 57 C6 56 -6 42 -8 28 Z";

const CHEST = "M28 292 C24 252 40 230 68 230 C96 230 112 252 110 292 Z";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── 1. stock ───────────────────────────────────────── */}
      <rect
        x={8}
        y={8}
        width={224}
        height={282}
        fill={PALETTE.paper}
        filter="url(#ek-grain)"
      />

      {/* ── 2. density ─────────────────────────────────────── */}
      <g clipPath="url(#ek-face-clip)">
        <g fill={INK} opacity={0.055}>
          {BURST.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        <rect
          x={8}
          y={8}
          width={224}
          height={282}
          fill="url(#ek-halftone-fine)"
          opacity={0.1}
        />
        <circle cx={74} cy={190} r={92} fill="url(#ek-halftone)" opacity={0.08} />
      </g>

      {/* ── 3. chest, braced against the heave. Runs off the bottom of
             the face clip rather than stopping in mid-air. ─────── */}
      <path d={CHEST} fill={PALETTE.red} opacity={0.8} transform="translate(-3 2)" />
      <path d={CHEST} fill={PALETTE.paper} />
      <path d={CHEST} fill="url(#ek-halftone-fine)" opacity={0.22} />
      <g filter="url(#ek-ink)">
        <path d={CHEST} fill="none" stroke={INK} strokeWidth={3.4} strokeLinejoin="round" />
        <g fill="none" stroke={INK} strokeWidth={2} strokeLinecap="round" opacity={0.7}>
          <path d="M54 252 C58 258 58 264 54 270" />
          <path d="M70 256 C74 262 74 268 70 274" />
          <path d="M86 252 C90 258 90 264 86 270" />
        </g>
      </g>

      {/* ── 4. cat: skull, ears, everything behind the jaw ─── */}
      <g transform="translate(72 186)">
        <path d={SKULL} fill={PALETTE.red} opacity={0.8} transform="translate(-3 2)" />
        <path d={SKULL} fill={PALETTE.paper} />
        <path d={SKULL} fill="url(#ek-halftone-fine)" opacity={0.22} />

        <g filter="url(#ek-ink)">
          <path d={SKULL} fill="none" stroke={INK} strokeWidth={3.6} strokeLinejoin="round" />
          <path d="M-35 -58 L-14.5 -43 C-20 -41 -24.5 -38.5 -28 -35 Z" fill={INK} opacity={0.85} />
          <path d="M33 -60 L14 -43 C19.5 -41 24 -38.5 27.5 -35 Z" fill={INK} opacity={0.85} />

          {/* brows, shoved up by the effort — the right one higher, so
              the face is not a symmetrical mask */}
          <path
            d="M-36 -42 C-31 -50 -22 -51 -17 -47"
            fill="none"
            stroke={INK}
            strokeWidth={2.8}
            strokeLinecap="round"
          />
          <path
            d="M-8 -47 C-3 -56 7 -57 12 -51"
            fill="none"
            stroke={INK}
            strokeWidth={2.8}
            strokeLinecap="round"
          />

          {/* eyes: clamped shut, upturned — this is pleasure, not pain */}
          <path
            d="M-36 -29 C-31 -39 -21 -39 -16 -29"
            fill="none"
            stroke={INK}
            strokeWidth={3.8}
            strokeLinecap="round"
          />
          <path
            d="M-9 -33 C-4 -43 6 -43 11 -33"
            fill="none"
            stroke={INK}
            strokeWidth={3.8}
            strokeLinecap="round"
          />
          {/* squeeze creases at the outer corners */}
          <g fill="none" stroke={INK} strokeWidth={1.9} strokeLinecap="round" opacity={0.85}>
            <path d="M-38 -34 L-44 -38" />
            <path d="M-39 -26 L-46 -25" />
            <path d="M13 -38 L18 -43" />
            <path d="M14 -30 L20 -31" />
          </g>

          {/* nose, sitting on the muzzle directly above the mouth corner */}
          <path
            d="M-19 -17 C-15.6 -18.6 -11.6 -18.6 -8.2 -17 C-9.6 -12.6 -11.8 -10.4 -13.6 -10.4
               C-15.4 -10.4 -17.6 -12.6 -19 -17 Z"
            fill={PALETTE.red}
            stroke={INK}
            strokeWidth={2}
            strokeLinejoin="round"
          />
          <path
            d="M-13.6 -10.4 C-13.2 -6.6 -10.4 -3.6 -6.4 -2.6"
            fill="none"
            stroke={INK}
            strokeWidth={2}
            strokeLinecap="round"
          />

          {/* cheek whiskers, all on the free side of the face */}
          <g fill="none" stroke={INK} strokeWidth={2} strokeLinecap="round">
            <path d="M-30 -6 C-44 -9 -57 -14 -66 -22" />
            <path d="M-30 1 C-45 1 -59 3 -69 6" />
            <path d="M-29 8 C-42 14 -53 22 -60 31" />
          </g>
          {/* fluff notches on the jaw */}
          <g fill="none" stroke={INK} strokeWidth={2} strokeLinecap="round">
            <path d="M-38 26 C-35 29 -33.5 33 -33.5 37" />
            <path d="M-22 41 C-20 44 -19 47 -19 50" />
          </g>
        </g>

        {/* chin, drawn under the maw so the jaw hangs off the skull */}
        <path d={CHIN} fill={PALETTE.paper} />
        <path d={CHIN} fill="url(#ek-halftone-fine)" opacity={0.22} />
        <g filter="url(#ek-ink)">
          <path d={CHIN} fill="none" stroke={INK} strokeWidth={3.2} strokeLinejoin="round" />
        </g>

        {/* ── the maw ──────────────────────────────────────────
             Throat in red rather than flat ink: a black hole in the
             side of a cat's head reads as damage, a red one reads as
             a mouth. The ink only survives as the rim. */}
        <path d={MAW} fill={PALETTE.red} />
        <g filter="url(#ek-ink)">
          <path d={MAW} fill="none" stroke={INK} strokeWidth={3.6} strokeLinejoin="round" />
          {/* throat, only just darker than the mouth — any more and the
              whole jaw collapses into one black mass at card size */}
          <path
            d="M4 -8 C14 -16 32 -14 40 -4 C46 4 44 18 34 22 C22 27 8 20 4 12 Z"
            fill={INK}
            opacity={0.22}
          />
        </g>
      </g>

      {/* ── 5. the rainbow ─────────────────────────────────── */}
      {/* off-register plate: the whole stream in red, shifted */}
      <g transform="translate(-3 2)" opacity={0.55}>
        <path d={spanPath(0, 6)} fill={PALETTE.red} />
      </g>

      <g>
        {BAND_INK.map((c, i) => (
          <path key={c} d={bandPath(i)} fill={c} />
        ))}
        {/* screen texture over the two coolest bands so the stream has
            tone as well as hue */}
        <g opacity={0.14}>
          <path d={bandPath(3)} fill="url(#ek-halftone-fine)" />
          <path d={bandPath(4)} fill="url(#ek-halftone-fine)" />
        </g>
      </g>

      {/* band separations + the two outer keylines */}
      <g fill="none" filter="url(#ek-ink)">
        {[1, 2, 3, 4, 5].map((i) => (
          <path key={i} d={edgePath(i)} stroke={INK} strokeWidth={1.3} opacity={0.5} />
        ))}
        <path d={edgePath(0)} stroke={INK} strokeWidth={3.2} strokeLinecap="round" />
        <path d={edgePath(6)} stroke={INK} strokeWidth={3.2} strokeLinecap="round" />
      </g>

      {/* ── 6. jaws re-drawn over the stream ───────────────── */}
      <g transform="translate(72 186)">
        {/* tongue, drawn *after* the stream so it hangs clear of it
            instead of being swallowed by the bottom band */}
        <path
          d="M-4 12 C6 26 26 32 44 25 C42 42 24 48 12 40 C3 34 -5 21 -4 12 Z"
          fill={PALETTE.pink}
          transform="translate(-3 2)"
          opacity={0.7}
        />
        <g filter="url(#ek-ink)">
          {/* upper lip arc, crossing in front of the rainbow */}
          <path
            d="M-6 -2 C2 -20 30 -24 46 -12 C53 -7 57 0 59 8"
            fill="none"
            stroke={INK}
            strokeWidth={4.4}
            strokeLinecap="round"
          />
          <path
            d="M-4 12 C6 26 26 32 44 25 C42 42 24 48 12 40 C3 34 -5 21 -4 12 Z"
            fill={PALETTE.pink}
            stroke={INK}
            strokeWidth={2.6}
            strokeLinejoin="round"
          />
          <path
            d="M8 24 C15 30 24 34 34 34.6"
            fill="none"
            stroke={INK}
            strokeWidth={1.7}
            strokeLinecap="round"
            opacity={0.6}
          />

          {/* lower jaw edge */}
          <path
            d="M-6 18 C2 30 16 38 32 38"
            fill="none"
            stroke={INK}
            strokeWidth={4}
            strokeLinecap="round"
          />
          {/* fangs, biting into the arc */}
          <path
            d="M4 -14 L10.5 -13 L6.5 -2 Z"
            fill={PALETTE.paper}
            stroke={INK}
            strokeWidth={1.9}
            strokeLinejoin="round"
          />
          <path
            d="M28 -19 L34 -15 L27 -5 Z"
            fill={PALETTE.paper}
            stroke={INK}
            strokeWidth={1.9}
            strokeLinejoin="round"
          />
          <path
            d="M2 16 L9 20 L1.5 26 Z"
            fill={PALETTE.paper}
            stroke={INK}
            strokeWidth={1.9}
            strokeLinejoin="round"
          />
        </g>
      </g>

      {/* ── 7. sparkles ────────────────────────────────────── */}
      <g>
        {SPARK.map(([x, y, s, r], i) => (
          <g key={i} transform={`translate(${x} ${y}) rotate(${r}) scale(${s / 10})`}>
            <path
              d="M0 -11 C1.6 -4.4 4.4 -1.6 11 0 C4.4 1.6 1.6 4.4 0 11
                 C-1.6 4.4 -4.4 1.6 -11 0 C-4.4 -1.6 -1.6 -4.4 0 -11 Z"
              fill={i % 2 === 0 ? PALETTE.gold : PALETTE.violet}
              transform="translate(-3 2)"
              opacity={0.75}
            />
            <path
              d="M0 -11 C1.6 -4.4 4.4 -1.6 11 0 C4.4 1.6 1.6 4.4 0 11
                 C-1.6 4.4 -4.4 1.6 -11 0 C-4.4 -1.6 -1.6 -4.4 0 -11 Z"
              fill={PALETTE.paper}
              stroke={INK}
              strokeWidth={2.4}
              strokeLinejoin="round"
            />
          </g>
        ))}
      </g>

      {/* ── 8. braced front paws ───────────────────────────── */}
      {(
        [
          [44, 266, -12],
          [84, 272, 9],
        ] as const
      ).map(([x, y, r], i) => (
        <g key={i} transform={`translate(${x} ${y}) rotate(${r})`}>
          <path
            d="M-16 10 C-19 -2 -13 -11 -2 -11 C9 -11 15 -2 13 9 C7 15 -10 16 -16 10 Z"
            fill={PALETTE.red}
            opacity={0.8}
            transform="translate(-3 2)"
          />
          <path
            d="M-16 10 C-19 -2 -13 -11 -2 -11 C9 -11 15 -2 13 9 C7 15 -10 16 -16 10 Z"
            fill={PALETTE.paper}
          />
          <path
            d="M-16 10 C-19 -2 -13 -11 -2 -11 C9 -11 15 -2 13 9 C7 15 -10 16 -16 10 Z"
            fill="url(#ek-halftone-fine)"
            opacity={0.22}
          />
          <g filter="url(#ek-ink)" fill="none" stroke={INK} strokeLinecap="round">
            <path
              d="M-16 10 C-19 -2 -13 -11 -2 -11 C9 -11 15 -2 13 9 C7 15 -10 16 -16 10 Z"
              strokeWidth={3}
              strokeLinejoin="round"
            />
            <path d="M-7.5 -10 C-8 -5 -8 0 -7 5" strokeWidth={2} />
            <path d="M1 -11 C1 -6 1.5 -1 2.5 5" strokeWidth={2} />
            <path d="M9.5 -8 C10.5 -4 11.5 1 12 6" strokeWidth={2} />
          </g>
        </g>
      ))}
    </g>
  );
}
