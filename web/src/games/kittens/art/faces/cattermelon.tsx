/* ─────────────────────────────────────────────────────────────
   cattermelon — a wedge of melon that resents being a wedge of melon

   The whole design rests on one substitution: the two top corners of
   a watermelon slice are already ear-shaped, so they become the ears
   and nothing else has to be explained. Rind, white pith, flesh,
   seeds — all four layers are real, because a slice missing its pith
   stripe stops reading as watermelon at small sizes.

   Seeds do double duty: a ring following the rind, and six more as
   whisker spots on the muzzle. Plates: paper + green + pink.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* The wedge: left ear tip, down the outside, round the rind, up to the
   right ear tip, and back across a top edge that sags between the ears. */
const SLICE =
  "M40 78 L27 130 C17 204 62 272 120 272 C178 272 223 204 213 130 " +
  "L200 78 L172 122 C150 131 90 131 68 122 Z";

/* Rind: outer arc out, inner arc back. Reversed second curve so the
   band has no twist in it. */
const RIND =
  "M27 130 C17 204 62 272 120 272 C178 272 223 204 213 130 " +
  "L195 132 C204 197 170 254 120 254 C70 254 36 197 45 132 Z";

/* The pith stripe — the pale band a real slice has between rind and flesh. */
const PITH =
  "M45 132 C36 197 70 254 120 254 C170 254 204 197 195 132 " +
  "L186 133 C194 193 164 245 120 245 C76 245 46 193 54 133 Z";

/* Seed ring following the pith, each rotated to point at the centre. */
const SEEDS: readonly [number, number, number][] = [
  [66, 186, -40],
  [74, 212, -30],
  [90, 231, -20],
  [112, 240, -7],
  [134, 239, 8],
  [154, 227, 21],
  [168, 206, 34],
  [175, 180, 46],
  [69, 156, -52],
  [172, 150, 50],
  [92, 250, -12],
  [148, 249, 12],
];

/* Whisker spots — the same seed glyph, smaller, on the muzzle. */
const SPOTS: readonly [number, number, number][] = [
  [98, 206, -22],
  [90, 216, -14],
  [100, 224, -6],
  [142, 206, 22],
  [150, 216, 14],
  [140, 224, 6],
];

const SEED =
  "M0 -6.4 C3.6 -6.4 5.2 -2.8 5.2 0.6 C5.2 4.2 2.9 6.4 0 6.4 " +
  "C-2.9 6.4 -5.2 4.2 -5.2 0.6 C-5.2 -2.8 -3.6 -6.4 0 -6.4 Z";

/* Density behind the subject — the same sunburst the rest of the deck
   uses. Without it the top fifth of this card is bare stock, which is
   the one thing the spec calls out as reading unfinished. Computed once
   at module load, so it stays deterministic. */
const BURST: readonly string[] = Array.from({ length: 18 }, (_, i) => {
  const step = (Math.PI * 2) / 18;
  const a0 = i * step;
  const a1 = a0 + step * 0.48;
  const R = 340;
  const p = (a: number) =>
    `${(120 + Math.cos(a) * R).toFixed(1)} ${(160 + Math.sin(a) * R).toFixed(1)}`;
  return `M120 160 L${p(a0)} L${p(a1)} Z`;
});

/* Spat seeds, arcing away from the muzzle. Fills the dead corner over
   the left ear and is the only thing on the card doing anything. */
const SPIT: readonly [number, number, number, number][] = [
  [58, 96, 1.0, -38],
  [40, 70, 0.85, -52],
  [30, 46, 0.7, -66],
  [188, 92, 0.9, 40],
  [204, 66, 0.7, 54],
];

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── stock ──────────────────────────────────────────── */}
      <rect
        x={8}
        y={8}
        width={224}
        height={282}
        fill={PALETTE.green}
        opacity={0.18}
        filter="url(#ek-grain)"
      />
      <g clipPath="url(#ek-face-clip)">
        <g fill={PALETTE.green} opacity={0.3}>
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
        <circle cx={120} cy={160} r={104} fill="url(#ek-halftone)" opacity={0.07} />
      </g>

      {/* spat seeds — deck-house off-register in red, then the ink glyph */}
      <g>
        {SPIT.map(([x, y, sc, r], i) => (
          <g key={i} transform={`translate(${x} ${y}) rotate(${r}) scale(${sc})`}>
            <path d={SEED} fill={PALETTE.red} opacity={0.8} transform="translate(-3 2)" />
            <path d={SEED} fill={INK} />
          </g>
        ))}
      </g>

      {/* ── tail: striped like the rind, because of course it is ── */}
      <g fill="none" strokeLinecap="round">
        <path
          d="M144 254 C196 262 230 238 224 210"
          stroke={PALETTE.red}
          strokeWidth={14}
          opacity={0.85}
          transform="translate(-3 2)"
        />
        <g filter="url(#ek-ink)">
          <path
            d="M144 254 C196 262 230 238 224 210"
            stroke={INK}
            strokeWidth={14}
          />
          <path
            d="M144 254 C196 262 230 238 224 210"
            stroke={PALETTE.green}
            strokeWidth={9}
          />
          <g stroke={INK} strokeWidth={2.4} opacity={0.9}>
            <path d="M204 250 C205 246 206 242 205 239" />
            <path d="M218 246 C221 243 223 239 223 235" />
            <path d="M226 228 C223 226 220 225 217 225" />
          </g>
        </g>
      </g>

      {/* ── the slice ──────────────────────────────────────── */}
      {/* off-register pink plate under the whole wedge */}
      <path d={SLICE} fill={PALETTE.red} opacity={0.9} transform="translate(-3 2)" />

      <g filter="url(#ek-ink)">
        <path d={SLICE} fill={PALETTE.pink} stroke={INK} strokeWidth={3.6} strokeLinejoin="round" />
        {/* flesh tone: a screen over the flat pink, the way a two-colour
            press would get a darker value without a third plate */}
        <path d={SLICE} fill="url(#ek-halftone)" opacity={0.15} />

        {/* pith, then rind, laid over the flesh */}
        <path d={PITH} fill={PALETTE.paper} stroke={INK} strokeWidth={2} strokeLinejoin="round" />
        <path d={RIND} fill={PALETTE.green} stroke={INK} strokeWidth={3} strokeLinejoin="round" />

        {/* dark rind striping — the classic melon chevrons, drawn as
            curves that follow the rind rather than straight bars */}
        <g fill="none" stroke={INK} strokeWidth={4.2} strokeLinecap="round" opacity={0.55}>
          <path d="M30 150 C36 162 38 176 37 190" />
          <path d="M42 216 C50 228 60 238 72 245" />
          <path d="M98 258 C110 261 122 262 134 260" />
          <path d="M162 248 C174 241 184 231 191 219" />
          <path d="M203 194 C207 181 209 166 208 152" />
          <path d="M25 176 C30 186 33 197 34 208" opacity={0.7} />
          <path d="M180 236 C189 227 196 216 201 205" opacity={0.7} />
        </g>

        {/* inner ears */}
        <path d="M41.5 88 L33.5 122 L61 116 Z" fill={INK} opacity={0.82} />
        <path d="M198.5 88 L206.5 122 L179 116 Z" fill={INK} opacity={0.82} />
      </g>

      {/* seed ring */}
      <g fill={INK}>
        {SEEDS.map(([x, y, r], i) => (
          <g key={i} transform={`translate(${x} ${y}) rotate(${r})`}>
            <path d={SEED} fill={PALETTE.red} opacity={0.7} transform="translate(-2.4 1.6)" />
            <path d={SEED} />
          </g>
        ))}
      </g>

      {/* ── the face ───────────────────────────────────────── */}
      <g filter="url(#ek-ink)">
        {/* brows: one flat, one hitched. The entire mood is in the gap. */}
        <path
          d="M74 146 C83 139 97 138 106 143"
          fill="none"
          stroke={INK}
          strokeWidth={3.6}
          strokeLinecap="round"
        />
        <path
          d="M134 137 C143 127 158 126 168 133"
          fill="none"
          stroke={INK}
          strokeWidth={3.6}
          strokeLinecap="round"
        />

        {/* eyes: wide almonds, lids dropped halfway, pupils dead ahead */}
        <path
          d="M78 164 C84 152 100 151 107 163 C100 174 85 175 78 164 Z"
          fill={PALETTE.paper}
          stroke={INK}
          strokeWidth={2.4}
          strokeLinejoin="round"
        />
        <path
          d="M135 163 C142 151 158 152 164 164 C157 175 142 174 135 163 Z"
          fill={PALETTE.paper}
          stroke={INK}
          strokeWidth={2.4}
          strokeLinejoin="round"
        />
        <path d="M86 160 C93 157 99 160 99 165.5 C99 170 93 172 88 169.5 C84 167.5 83 162 86 160 Z" fill={INK} />
        <path d="M143 160 C150 157 156 160 156 165.5 C156 170 150 172 145 169.5 C141 167.5 140 162 143 160 Z" fill={INK} />
        <path
          d="M77 162 C84 152 100 151 107.5 161.5"
          fill="none"
          stroke={INK}
          strokeWidth={3.6}
          strokeLinecap="round"
        />
        <path
          d="M134.5 161.5 C142 151 158 152 164.5 162"
          fill="none"
          stroke={INK}
          strokeWidth={3.6}
          strokeLinecap="round"
        />

        {/* nose + a mouth that has already given up */}
        <path
          d="M112 190 C115.5 188.2 124.5 188.2 128 190 C126.4 195.4 123.4 198.2 120 198.2
             C116.6 198.2 113.6 195.4 112 190 Z"
          fill={PALETTE.green}
          stroke={INK}
          strokeWidth={2.2}
          strokeLinejoin="round"
        />
        <path d="M120 198.2 L120 204" fill="none" stroke={INK} strokeWidth={2.4} strokeLinecap="round" />
        <path
          d="M120 204 C114 210 104 209 101 203"
          fill="none"
          stroke={INK}
          strokeWidth={2.8}
          strokeLinecap="round"
        />
        <path
          d="M120 204 C126 210 136 209 139 203"
          fill="none"
          stroke={INK}
          strokeWidth={2.8}
          strokeLinecap="round"
        />

        {/* whiskers, sagging */}
        <g fill="none" stroke={INK} strokeWidth={2.1} strokeLinecap="round">
          <path d="M84 200 C73 199 63 200 55 204" />
          <path d="M84 208 C73 211 64 216 57 222" />
          <path d="M156 200 C167 199 177 200 185 204" />
          <path d="M156 208 C167 211 176 216 183 222" />
        </g>
      </g>

      {/* whisker spots — same seed glyph, half scale */}
      <g fill={INK}>
        {SPOTS.map(([x, y, r], i) => (
          <g key={i} transform={`translate(${x} ${y}) rotate(${r}) scale(0.5)`}>
            <path d={SEED} />
          </g>
        ))}
      </g>

      {/* a couple of juice drops, so the bottom edge is not inert */}
      <g filter="url(#ek-ink)">
        <path
          d="M94 276 C97 280 98.5 283.5 97 286 C95 289 91 288.5 90 285.5 C89 283 91 279.5 94 276 Z"
          fill={PALETTE.pink}
          stroke={INK}
          strokeWidth={1.8}
          strokeLinejoin="round"
        />
        <path
          d="M152 274 C155.6 278.4 157.4 282.6 155.6 285.6 C153.2 289.2 148.4 288.6 147.2 285
             C146 282 148.4 277.8 152 274 Z"
          fill={PALETTE.pink}
          stroke={INK}
          strokeWidth={1.8}
          strokeLinejoin="round"
        />
      </g>
    </g>
  );
}
