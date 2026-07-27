/* ─────────────────────────────────────────────────────────────
   tacocat — a cat in a taco, and it knows the joke

   Second pass. The first one drew the shell as two stacked crescents
   with a deeply sagging rim, which at 60px is indistinguishable from a
   soup bowl — and a cat in a bowl is a different, worse card. What
   actually makes a taco read is not the curve of the shell, it is the
   TOP: a near-straight rim spanning the full width, two corners flared
   up into horns above that rim, and a ruffle of filling crammed into
   the slot so you never see an open interior. A bowl has an open mouth;
   a taco has a stuffed slot. That is the whole difference and it is
   what this file is built around.

   The cat is white, so it gets a halftone coat — a paper cat on paper
   stock disappears, which is the other thing the first pass got wrong.

   Symmetry is held for the shell (the gag is a palindrome) and broken
   in the face, because a symmetric face is a logo, not a cat: the brows
   disagree, and the smirk only goes up on one side.

   Plates: paper + gold + red.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* ── background sunburst ──────────────────────────────────────
   Same device the rest of the deck uses behind its subject. Computed
   once at module load from a fixed count, so it is deterministic. */
const BURST: readonly string[] = Array.from({ length: 18 }, (_, i) => {
  const step = (Math.PI * 2) / 18;
  const a0 = i * step;
  const a1 = a0 + step * 0.5;
  const R = 340;
  const p = (a: number) =>
    `${(120 + Math.cos(a) * R).toFixed(1)} ${(126 + Math.sin(a) * R).toFixed(1)}`;
  return `M120 126 L${p(a0)} L${p(a1)} Z`;
});

/* ── the shell ────────────────────────────────────────────────
   Two walls. FAR is the back one: nearly all of it is covered, and it
   exists so a second pair of horn points shows inside the near pair —
   that doubling is what says "folded shell" rather than "vessel".
   NEAR is the front: horn tips at y120, rim sagging only to y168, and
   the outer profile narrowing on the way down so the widest part of
   the object is its mouth. Let the belly get wider than the rim and it
   turns into a pumpkin; deepen the rim sag and the bowl comes back. */
const FAR_SHELL =
  "M30 96 L48 150 C54 198 80 230 120 230 C160 230 186 198 192 150 L210 96 " +
  "C196 128 168 148 120 148 C72 148 44 128 30 96 Z";

const NEAR_SHELL =
  "M10 120 L34 166 C42 214 80 252 120 256 C160 252 198 214 206 166 L230 120 " +
  "C212 150 176 168 120 168 C64 168 28 150 10 120 Z";

/* Filling: one continuous ruffle jammed the full width of the slot,
   stopping short of the horns at each end so both sets of shell points
   stay clear. Six lobes — few enough to read at thumbnail, enough that
   it is not a scallop pattern. */
const FILLING =
  "M44 152 C46 130 62 128 70 144 C76 128 92 127 100 142 C106 127 122 126 130 141 " +
  "C136 127 152 127 160 142 C166 128 182 129 190 145 C194 134 198 138 198 152 " +
  "L198 196 L44 196 Z";

/* Toasted char. One irregular bezier blob placed by a table — the first
   pass used <ellipse>, which is exactly the tell that a shape was not
   drawn. */
const CHAR_BLOB =
  "M-5 -1.6 C-4.2 -3.9 -1 -4.6 1.5 -3.5 C4 -2.4 5.4 -0.5 4.6 1.3 " +
  "C3.8 3.3 0.8 4.3 -1.7 3.4 C-4 2.6 -5.9 0.7 -5 -1.6 Z";

/* [x, y, scale, rotation] */
const CHAR: readonly [number, number, number, number][] = [
  [120, 240, 1.25, 6],
  [94, 236, 0.85, -18],
  [148, 234, 0.95, 24],
  [66, 218, 1.0, -36],
  [174, 216, 0.9, 34],
  [46, 188, 0.8, -14],
  [194, 186, 0.75, 12],
  [106, 250, 0.65, -6],
  [136, 248, 0.6, 14],
  [82, 250, 0.55, 20],
  [38, 166, 0.6, -8],
  [202, 164, 0.6, 8],
  [160, 246, 0.55, -10],
  [120, 208, 0.7, 16],
  [56, 240, 0.5, -22],
  [184, 238, 0.5, 22],
];

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── 1. stock plate ─────────────────────────────────── */}
      <rect
        x={8}
        y={8}
        width={224}
        height={282}
        fill={PALETTE.gold}
        opacity={0.18}
        filter="url(#ek-grain)"
      />

      {/* ── 2. density: sunburst + halftone field ──────────── */}
      <g clipPath="url(#ek-face-clip)">
        <g fill={PALETTE.gold} opacity={0.3}>
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
        <circle cx={120} cy={110} r={86} fill="url(#ek-halftone)" opacity={0.09} />
      </g>

      {/* ── 3. tail, behind the shell so it reads as attached ── */}
      <g fill="none" strokeLinecap="round">
        <path
          d="M168 156 C204 150 222 118 210 92 C204 80 191 82 189 92"
          stroke={PALETTE.red}
          strokeWidth={14}
          opacity={0.85}
          transform="translate(-3 2)"
        />
        <path
          d="M168 156 C204 150 222 118 210 92 C204 80 191 82 189 92"
          stroke={INK}
          strokeWidth={14}
        />
        <path
          d="M168 156 C204 150 222 118 210 92 C204 80 191 82 189 92"
          stroke={PALETTE.paper}
          strokeWidth={8.5}
        />
        <g stroke={INK} strokeWidth={2.3} filter="url(#ek-ink)">
          <path d="M196 158 C198 153 199 148 198 144" />
          <path d="M214 142 C217 138 218 133 218 128" />
          <path d="M213 104 C210 102 206 101 203 101" />
        </g>
      </g>

      {/* ── 4. far wall of the shell ───────────────────────── */}
      <path d={FAR_SHELL} fill={PALETTE.red} opacity={0.9} transform="translate(-2 1.4)" />
      <path d={FAR_SHELL} fill={PALETTE.gold} />
      <path d={FAR_SHELL} fill={INK} opacity={0.16} />
      <path d={FAR_SHELL} fill="url(#ek-halftone)" opacity={0.16} />

      {/* ── 5. filling, crammed into the slot ──────────────── */}
      <path d={FILLING} fill={PALETTE.red} opacity={0.85} transform="translate(-3 2)" />
      <path d={FILLING} fill={PALETTE.red} />
      <path d={FILLING} fill="url(#ek-halftone)" opacity={0.16} />

      {/* ── 6. the cat: chest first, head over the join ────── */}
      <path
        d="M74 206 C68 166 92 122 120 122 C148 122 172 166 166 206 Z"
        fill={PALETTE.red}
        opacity={0.85}
        transform="translate(-3 2)"
      />
      <path
        d="M74 206 C68 166 92 122 120 122 C148 122 172 166 166 206 Z"
        fill={PALETTE.paper}
      />
      <path
        d="M74 206 C68 166 92 122 120 122 C148 122 172 166 166 206 Z"
        fill="url(#ek-halftone-fine)"
        opacity={0.2}
      />

      <g transform="translate(120 88)">
        <path
          d="M-40 2 C-40 -13 -33 -25 -21 -31 L-36 -58 C-38.5 -62 -33.5 -65.5 -29.5 -62.5
             L-6.5 -45.5 C-2.2 -46.6 2.2 -46.6 6.5 -45.5 L29.5 -62.5 C33.5 -65.5 38.5 -62 36 -58
             L21 -31 C33 -25 40 -13 40 2 C40 22 30 36 16 41 C6 44.5 -6 44.5 -16 41
             C-30 36 -40 22 -40 2 Z"
          fill={PALETTE.red}
          opacity={0.88}
          transform="translate(-3 2)"
        />
        <path
          d="M-40 2 C-40 -13 -33 -25 -21 -31 L-36 -58 C-38.5 -62 -33.5 -65.5 -29.5 -62.5
             L-6.5 -45.5 C-2.2 -46.6 2.2 -46.6 6.5 -45.5 L29.5 -62.5 C33.5 -65.5 38.5 -62 36 -58
             L21 -31 C33 -25 40 -13 40 2 C40 22 30 36 16 41 C6 44.5 -6 44.5 -16 41
             C-30 36 -40 22 -40 2 Z"
          fill={PALETTE.paper}
        />
        <path
          d="M-40 2 C-40 -13 -33 -25 -21 -31 L-36 -58 C-38.5 -62 -33.5 -65.5 -29.5 -62.5
             L-6.5 -45.5 C-2.2 -46.6 2.2 -46.6 6.5 -45.5 L29.5 -62.5 C33.5 -65.5 38.5 -62 36 -58
             L21 -31 C33 -25 40 -13 40 2 C40 22 30 36 16 41 C6 44.5 -6 44.5 -16 41
             C-30 36 -40 22 -40 2 Z"
          fill="url(#ek-halftone-fine)"
          opacity={0.2}
        />

        <g filter="url(#ek-ink)">
          {/* silhouette stroke */}
          <path
            d="M-40 2 C-40 -13 -33 -25 -21 -31 L-36 -58 C-38.5 -62 -33.5 -65.5 -29.5 -62.5
               L-6.5 -45.5 C-2.2 -46.6 2.2 -46.6 6.5 -45.5 L29.5 -62.5 C33.5 -65.5 38.5 -62 36 -58
               L21 -31 C33 -25 40 -13 40 2 C40 22 30 36 16 41 C6 44.5 -6 44.5 -16 41
               C-30 36 -40 22 -40 2 Z"
            fill="none"
            stroke={INK}
            strokeWidth={3.6}
            strokeLinejoin="round"
          />

          {/* inner ears, filled so the horns of the head survive shrinking */}
          <path
            d="M-30.5 -55.5 L-11.5 -41.5 C-17 -39.5 -21.5 -37 -25 -33.5 Z"
            fill={INK}
            opacity={0.85}
          />
          <path
            d="M30.5 -55.5 L11.5 -41.5 C17 -39.5 21.5 -37 25 -33.5 Z"
            fill={INK}
            opacity={0.85}
          />

          {/* brows: they disagree. The right one is up in the ear, the
              left is flat. This is the entire attitude of the card. */}
          <path
            d="M-29 -19 C-23 -22 -14 -22.5 -9 -20"
            fill="none"
            stroke={INK}
            strokeWidth={2.8}
            strokeLinecap="round"
          />
          <path
            d="M9 -22 C15 -30 25 -31 30 -26"
            fill="none"
            stroke={INK}
            strokeWidth={2.8}
            strokeLinecap="round"
          />

          {/* eyes: almonds, both pupils shoved to one side — a cat
              looking at you sideways is smug; looking straight is cute */}
          <path
            d="M-27 -7 C-22.5 -16 -10.5 -16.5 -6 -8 C-11 -1.5 -22 -1 -27 -7 Z"
            fill={PALETTE.paper}
            stroke={INK}
            strokeWidth={2.2}
            strokeLinejoin="round"
          />
          <path
            d="M27 -7 C22.5 -16 10.5 -16.5 6 -8 C11 -1.5 22 -1 27 -7 Z"
            fill={PALETTE.paper}
            stroke={INK}
            strokeWidth={2.2}
            strokeLinejoin="round"
          />
          <path d="M-11.5 -12.8 C-7 -12.6 -5.4 -8.2 -7.6 -4.8 C-12.2 -3.8 -15 -6.4 -14.4 -9.8 Z" fill={INK} />
          <path d="M20.5 -12.4 C25 -12.2 26.4 -7.8 24.2 -4.6 C19.6 -3.6 17 -6.2 17.6 -9.6 Z" fill={INK} />
          {/* heavy top lids, drooped */}
          <path
            d="M-27.5 -8 C-22.5 -15 -10.5 -15.5 -5.6 -8.8"
            fill="none"
            stroke={INK}
            strokeWidth={3.6}
            strokeLinecap="round"
          />
          <path
            d="M27.5 -8 C22.5 -15 10.5 -15.5 5.6 -8.8"
            fill="none"
            stroke={INK}
            strokeWidth={3.6}
            strokeLinecap="round"
          />

          {/* nose + a smirk that only goes up on one side */}
          <path
            d="M-5.4 3 C-2 1.4 2 1.4 5.4 3 C4 7.4 1.8 9.6 0 9.6 C-1.8 9.6 -4 7.4 -5.4 3 Z"
            fill={PALETTE.red}
            stroke={INK}
            strokeWidth={2}
            strokeLinejoin="round"
          />
          <path d="M0 9.6 L0 14" fill="none" stroke={INK} strokeWidth={2.2} strokeLinecap="round" />
          <path
            d="M0 14 C-4 18.5 -11 18.5 -14 15"
            fill="none"
            stroke={INK}
            strokeWidth={2.6}
            strokeLinecap="round"
          />
          <path
            d="M0 14 C4.5 22 14 23.5 19.5 17"
            fill="none"
            stroke={INK}
            strokeWidth={2.6}
            strokeLinecap="round"
          />
          {/* the crease the smirk pushes into that cheek */}
          <path
            d="M22 12 C24.5 15 25.5 18.5 25 22"
            fill="none"
            stroke={INK}
            strokeWidth={1.9}
            strokeLinecap="round"
            opacity={0.75}
          />

          {/* whiskers — three a side, kept above the filling line so
              none of them get swallowed by the ruffle */}
          <g fill="none" stroke={INK} strokeWidth={2} strokeLinecap="round">
            <path d="M-19 12 C-33 10 -47 6 -57 -1" />
            <path d="M-19 17 C-34 19 -48 20 -59 18" />
            <path d="M-18 22 C-31 26 -42 30 -50 35" />
            <path d="M19 12 C33 10 47 6 57 -1" />
            <path d="M19 17 C34 19 48 20 59 18" />
            <path d="M18 22 C31 26 42 30 50 35" />
          </g>

          {/* cheek fluff notches, so the jaw is not a smooth arc */}
          <g fill="none" stroke={INK} strokeWidth={2} strokeLinecap="round">
            <path d="M-33 26 C-30 29 -28.5 33 -28.5 37" />
            <path d="M33 26 C30 29 28.5 33 28.5 37" />
          </g>
        </g>
      </g>

      {/* ── 7. filling linework, over the cat's flanks ─────── */}
      <g filter="url(#ek-ink)">
        <path
          d={FILLING}
          fill="none"
          stroke={INK}
          strokeWidth={2.8}
          strokeLinejoin="round"
        />
        <g fill="none" stroke={INK} strokeWidth={1.8} strokeLinecap="round" opacity={0.5}>
          <path d="M56 146 C58 158 58 170 56 180" />
          <path d="M86 144 C88 156 88 168 86 178" />
          <path d="M154 144 C156 156 156 168 154 178" />
          <path d="M184 146 C186 158 186 170 184 180" />
        </g>
      </g>

      {/* ── 8. near wall ───────────────────────────────────── */}
      <path d={NEAR_SHELL} fill={PALETTE.red} opacity={0.85} transform="translate(-3 2)" />
      <path d={NEAR_SHELL} fill={PALETTE.gold} />
      <path d={NEAR_SHELL} fill="url(#ek-halftone)" opacity={0.14} />

      {/* char, clipped in spirit to the near wall by placement */}
      <g fill={INK} opacity={0.3}>
        {CHAR.map(([x, y, s, r], i) => (
          <path key={i} d={CHAR_BLOB} transform={`translate(${x} ${y}) rotate(${r}) scale(${s})`} />
        ))}
      </g>

      <g filter="url(#ek-ink)" fill="none" stroke={INK} strokeLinecap="round" strokeLinejoin="round">
        <path d={NEAR_SHELL} strokeWidth={3.8} />
        {/* the fold and the seam creases that run out of it */}
        <g opacity={0.42}>
          <path d="M120 176 C117 200 118 222 120 244" strokeWidth={1.8} />
          <path d="M78 172 C70 194 70 214 78 232" strokeWidth={1.5} />
          <path d="M162 172 C170 194 170 214 162 232" strokeWidth={1.5} />
          <path d="M54 178 C50 194 52 206 58 216" strokeWidth={1.4} />
          <path d="M186 178 C190 194 188 206 182 216" strokeWidth={1.4} />
        </g>
      </g>

      {/* ── 9. paws hooked over the near rim ───────────────── */}
      {[-1, 1].map((s) => (
        <g key={s} transform={`translate(${120 + s * 50} 158) scale(${s} 1)`}>
          <path
            d="M-16 12 C-19 0 -13 -9 -3 -9 C7 -9 13 -1 12 10 C7 15 -10 16 -16 12 Z"
            fill={PALETTE.red}
            opacity={0.85}
            transform="translate(-3 2)"
          />
          <path
            d="M-16 12 C-19 0 -13 -9 -3 -9 C7 -9 13 -1 12 10 C7 15 -10 16 -16 12 Z"
            fill={PALETTE.paper}
          />
          <path
            d="M-16 12 C-19 0 -13 -9 -3 -9 C7 -9 13 -1 12 10 C7 15 -10 16 -16 12 Z"
            fill="url(#ek-halftone-fine)"
            opacity={0.2}
          />
          <g filter="url(#ek-ink)" fill="none" stroke={INK} strokeLinecap="round">
            <path
              d="M-16 12 C-19 0 -13 -9 -3 -9 C7 -9 13 -1 12 10 C7 15 -10 16 -16 12 Z"
              strokeWidth={3}
              strokeLinejoin="round"
            />
            <path d="M-7.5 -8 C-8 -3 -8 2 -7 7" strokeWidth={2} />
            <path d="M1 -9 C1 -4 1.5 1 2.5 7" strokeWidth={2} />
            <path d="M9 -6 C10 -2 11 3 11.5 8" strokeWidth={2} />
          </g>
        </g>
      ))}
    </g>
  );
}
