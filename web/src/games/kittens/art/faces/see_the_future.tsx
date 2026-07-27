/* ─────────────────────────────────────────────────────────────
   SEE THE FUTURE — the fortune-teller card.

   Action-card skeleton, same as SKIP and ATTACK: flat saturated
   plate → ray fan → halftone bands → a solid-ink subject with an
   off-register plate → paper-coloured graphic devices on top.

   Played completely straight: turban, gem, crystal ball, cosmic
   rays, a third eye wide open in the middle of the forehead. The
   joke is the face underneath it — two half-lidded, profoundly
   bored eyes, because it has already seen the top three cards and
   one of them is a bomb.

   Plates: paper + violet + gold. No red anywhere, so every
   off-register fringe here is a hand-placed gold duplicate at
   (-2.8, +1.7) rather than the shared misprint filter.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

const BALL = { cx: 120, cy: 252, r: 38 } as const;

/* Cosmic rays fanning up out of the ball. Angles are degrees from
   straight up; the cat's head masks the middle of the fan. */
const RAYS: readonly (readonly [number, number])[] = [
  [-82, 10],
  [-67, 5],
  [-53, 12],
  [-39, 6],
  [-25, 10],
  [-11, 5],
  [4, 11],
  [18, 6],
  [32, 10],
  [46, 5],
  [60, 12],
  [75, 6],
];

/* A four-point sparkle, drawn once and scattered. */
const SPARK =
  "M0 -9.5C1.3 -3.6 3.6 -1.3 9.5 0C3.6 1.3 1.3 3.6 0 9.5" +
  "C-1.3 3.6 -3.6 1.3 -9.5 0C-3.6 -1.3 -1.3 -3.6 0 -9.5Z";

const SPARKS: readonly (readonly [number, number, number])[] = [
  [40, 126, 1.05],
  [200, 142, 0.85],
  [30, 190, 0.7],
  [210, 200, 1.0],
  [52, 100, 0.6],
  [190, 104, 0.7],
  [26, 156, 0.5],
  [216, 168, 0.55],
  [46, 238, 0.62],
  [198, 246, 0.7],
];

/* ── the three revealed cards ────────────────────────────────
   Slightly trapezoidal, so the fan has depth in it. */
const REVEAL =
  "M-21 -30C-21 -31.6 -19.9 -32.4 -18.4 -32.2L19.6 -28.4" +
  "C21.1 -28.2 21.9 -27.2 21.7 -25.7L18.4 28.8" +
  "C18.2 30.4 17.1 31.2 15.6 31L-17.6 27.6" +
  "C-19.1 27.4 -19.9 26.4 -19.7 24.9Z";

const BOMB =
  "M-2 -4C6.4 -4 13 1.8 13 9.2C13 16.6 6.4 22.4 -2 22.4" +
  "C-10.4 22.4 -17 16.6 -17 9.2C-17 1.8 -10.4 -4 -2 -4Z" +
  "M4.4 -8.6C7.4 -14.4 12.8 -16.4 17 -13.6L13.6 -8.4" +
  "C11.4 -9.6 9.2 -8.6 7.8 -5.8Z" +
  "M17 -25L19.2 -19.8L24.4 -17.6L19.2 -15.4L17 -10.2L14.8 -15.4L9.6 -17.6L14.8 -19.8Z";

const PAW_GLYPH =
  "M-10 3C-6 -5 6 -5 10 3C12.4 8.4 8 14.4 -0.4 14.6" +
  "C-4.4 14.7 -7.6 14.6 -10.6 14C-16.6 12.8 -13.6 7 -10 3Z" +
  "M-15.4 -7C-12.8 -10 -8.8 -8.6 -8.6 -4.6C-8.5 -1.2 -10.6 0.6 -13.2 -0.3" +
  "C-16 -1.2 -17.6 -4.6 -15.4 -7Z" +
  "M-3.6 -12.6C-1 -15.6 3 -14.2 3.2 -10.2C3.3 -6.6 1.2 -4.8 -1.4 -5.8" +
  "C-4.2 -6.8 -5.8 -10.2 -3.6 -12.6Z" +
  "M9.4 -10.6C12 -13.2 15.6 -11.6 15.4 -7.8C15.3 -4.6 13.2 -3 10.8 -4" +
  "C8.2 -5.1 7.2 -8.4 9.4 -10.6Z";

const QUERY =
  "M-9 -10C-9 -19 -2.6 -24.6 4.4 -24.6C11.8 -24.6 17.4 -19.4 17.4 -12.2" +
  "C17.4 -6 12.6 -2.4 8.6 0.6C5.6 2.8 4.6 4.6 4.6 7.6L-2 7.6" +
  "C-2 2.2 -0.2 -1.4 3.8 -4.4C7.2 -7 9.4 -8.8 9.4 -12" +
  "C9.4 -15.4 7 -17.8 3.8 -17.8C0 -17.8 -2.4 -14.8 -2.4 -10Z" +
  "M1 12.4C4.4 12.4 7 15 7 18.4C7 21.8 4.4 24.4 1 24.4" +
  "C-2.4 24.4 -5 21.8 -5 18.4C-5 15 -2.4 12.4 1 12.4Z";

function RevealedCard({ glyph }: { glyph: string }): ReactElement {
  return (
    <g>
      <path d={REVEAL} fill={PALETTE.gold} transform="translate(-2.8 1.7)" />
      <path d={REVEAL} fill={PALETTE.paper} stroke={INK} strokeWidth={3.4} strokeLinejoin="round" />
      {/* title bar, so it reads as one of these cards at thumbnail size */}
      <path d="M-14 15C-4 15.8 6 16.8 15.6 17.8L14.8 25.4C5.2 24.4 -5 23.4 -14.8 22.6Z" fill={INK} />
      <path d={glyph} fill={INK} transform="translate(0 -3)" />
      {/* violet corner tick — the deck's own tell */}
      <path
        d="M-16 -25.6L-16 -19M-16 -25.6L-9.4 -25.2"
        fill="none"
        stroke={PALETTE.violet}
        strokeWidth={2.4}
        strokeLinecap="round"
      />
    </g>
  );
}

/* ── the seer ────────────────────────────────────────────────
   Local space centred on the skull, which sits at (120,166). Built
   from overlapping ink masses; the union is the silhouette. */

const SKULL =
  "M-46 -4C-46 -26 -25 -42 0 -42C25 -42 46 -26 46 -4" +
  "C46 14 36 30 20 38C13 41 -13 41 -20 38C-36 30 -46 14 -46 -4Z";

/* Broad triangles off the OUTER top corners of the skull. Ears set
   narrow and high on the crown are what turn a drawn cat into a
   rabbit, and this card has been there once already. */
const EAR_L = "M-40 -32C-47 -46 -52 -62 -50 -76C-39 -68 -28 -54 -24 -44Z";
const EAR_R = "M40 -32C47 -46 52 -62 50 -76C39 -68 28 -54 24 -44Z";
const EAR_L_IN = "M-43 -47C-46 -55 -48 -62 -47 -68C-41 -62 -36 -55 -34 -51Z";
const EAR_R_IN = "M43 -47C46 -55 48 -62 47 -68C41 -62 36 -55 34 -51Z";

const TORSO =
  "M80 206C96 199 144 199 160 206C167 226 165 250 157 266L83 266C75 250 73 226 80 206Z";
const ARM_L =
  "M88 206C71 216 59 236 57 256C55 271 65 281 78 277C90 273 94 259 90 247" +
  "C86 233 93 219 105 211Z";
const ARM_R =
  "M152 206C169 216 181 236 183 256C185 271 175 281 162 277C150 273 146 259 150 247" +
  "C154 233 147 219 135 211Z";
const PAW_L =
  "M64 238C74 229 91 229 98 239C103 246 99 257 88 259C75 261 63 256 60 247" +
  "C58 243 61 240 64 238Z";
const PAW_R =
  "M176 238C166 229 149 229 142 239C137 246 141 257 152 259C165 261 177 256 180 247" +
  "C182 243 179 240 176 238Z";

const TURBAN =
  "M-48 -28C-54 -52 -36 -74 0 -76C36 -74 54 -52 48 -28" +
  "C34 -40 18 -46 0 -46C-18 -46 -34 -40 -48 -28Z";
const TURBAN_BAND =
  "M-50 -26C-34 -40 -17 -46 0 -46C17 -46 34 -40 50 -26L47 -13" +
  "C32 -27 17 -32 0 -32C-17 -32 -32 -27 -47 -13Z";
const GEM = "M0 -74L14 -58L0 -38L-14 -58Z";

/* Third eye: paper almond, gold iris, ink slit pupil blown wide. */
const IRIS =
  "M0 -32C6.6 -32 11.6 -26.6 11.6 -20C11.6 -13.4 6.6 -8 0 -8" +
  "C-6.6 -8 -11.6 -13.4 -11.6 -20C-11.6 -26.6 -6.6 -32 0 -32Z";
const SLIT =
  "M0 -32C3.8 -28.6 5.2 -24.6 5.2 -20C5.2 -15.4 3.8 -11.4 0 -8" +
  "C-3.8 -11.4 -5.2 -15.4 -5.2 -20C-5.2 -24.6 -3.8 -28.6 0 -32Z";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate ─────────────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={288} fill={PALETTE.violet} filter="url(#ek-grain)" />

      {/* ── the fan of rays out of the ball ───────────────── */}
      <g transform={`translate(${BALL.cx} ${BALL.cy})`} fill={PALETTE.gold} opacity={0.34}>
        {RAYS.map(([a, w], i) => (
          <path key={i} d={`M0 -16L${-w} -264L${w} -264Z`} transform={`rotate(${a})`} />
        ))}
      </g>

      {/* ── tone fields ───────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={50} fill="url(#ek-halftone-fine)" opacity={0.22} />
      <rect x={6} y={236} width={228} height={58} fill="url(#ek-halftone)" opacity={0.18} />

      {/* ── stars ─────────────────────────────────────────── */}
      <g filter="url(#ek-ink)">
        {SPARKS.map(([x, y, s], i) => (
          <g key={i} transform={`translate(${x} ${y}) scale(${s})`}>
            <path d={SPARK} fill={INK} transform="translate(-2.6 1.6)" />
            <path d={SPARK} fill={PALETTE.gold} stroke={INK} strokeWidth={1.6} strokeLinejoin="round" />
          </g>
        ))}
      </g>

      {/* ── the three revealed cards, levitating ──────────── */}
      <g filter="url(#ek-ink)">
        <g transform="translate(68 74) rotate(-16)">
          <RevealedCard glyph={BOMB} />
        </g>
        <g transform="translate(174 76) rotate(17)">
          <RevealedCard glyph={QUERY} />
        </g>
        <g transform="translate(120 58) rotate(2) scale(1.06)">
          <RevealedCard glyph={PAW_GLYPH} />
        </g>
      </g>
      {/* rising-lines under the fan, so the cards read as levitating */}
      <g
        fill="none"
        stroke={PALETTE.gold}
        strokeWidth={2.6}
        strokeLinecap="round"
        opacity={0.9}
        filter="url(#ek-ink)"
      >
        <path d="M50 116C46 122 44 128 44 134" />
        <path d="M120 104C120 111 121 117 123 123" />
        <path d="M192 118C196 124 198 130 199 136" />
      </g>

      {/* ── the seer: off-register gold plate, then the ink ── */}
      <g fill={PALETTE.gold}>
        <g transform="translate(-2.8 1.7)">
          <path d={TORSO} />
          <path d={ARM_L} />
          <path d={ARM_R} />
          <g transform="translate(120 166)">
            <path d={EAR_L} />
            <path d={EAR_R} />
            <path d={SKULL} />
          </g>
        </g>
      </g>

      <g filter="url(#ek-ink)">
        <g fill={INK}>
          <path d={TORSO} />
          <path d={ARM_L} />
          <path d={ARM_R} />
        </g>
        {/* sleeve bars, so the shoulders are not one blank mass */}
        <g fill={PALETTE.paper} opacity={0.55}>
          <path d="M80 220C74 226 70 233 68 240C68 231 72 223 78 216Z" />
          <path d="M72 246C68 252 66 259 66 266C64 258 66 249 70 242Z" />
          <path d="M160 220C166 226 170 233 172 240C172 231 168 223 162 216Z" />
          <path d="M168 246C172 252 174 259 174 266C176 258 174 249 170 242Z" />
        </g>

        <g transform="translate(120 166)">
          <path d={SKULL} fill={INK} />

          {/* cheek shading, cut in paper */}
          <g fill={PALETTE.paper} opacity={0.28}>
            <path d="M-42 6C-38 20 -28 31 -14 36C-28 36 -40 26 -44 12Z" />
            <path d="M42 6C38 20 28 31 14 36C28 36 40 26 44 12Z" />
          </g>

          {/* ── the face ──────────────────────────────────────
              Two half-lidded eyes with the lower lid showing, which is
              what makes it read bored rather than asleep, plus brows
              that have not bothered to move. */}
          <g fill="none" stroke={PALETTE.paper} strokeLinecap="round">
            <path d="M-33 10C-27 1 -15 1 -9 11" strokeWidth={4} />
            <path d="M9 11C15 1 27 1 33 10" strokeWidth={4} />
            <path d="M-31 16C-26 21 -16 21 -10 16" strokeWidth={2.2} opacity={0.75} />
            <path d="M10 16C16 21 26 21 31 16" strokeWidth={2.2} opacity={0.75} />
            <path d="M-36 -4C-29 -9 -18 -9 -10 -5" strokeWidth={2.6} opacity={0.8} />
            <path d="M10 -5C18 -9 29 -9 36 -4" strokeWidth={2.6} opacity={0.8} />
          </g>

          {/* muzzle: nose, a flat unimpressed mouth, whiskers */}
          <path d="M-7 22L7 22L0 30Z" fill={PALETTE.paper} />
          <path
            d="M0 30L0 34M-14 36C-8 40 8 40 14 36"
            fill="none"
            stroke={PALETTE.paper}
            strokeWidth={2.8}
            strokeLinecap="round"
          />
          <g fill={PALETTE.paper} opacity={0.9}>
            <path d="M-20 25C-30 24 -39 22 -47 19C-38 20 -29 21 -20 22Z" />
            <path d="M-20 31C-30 32 -38 34 -46 38C-37 33 -29 30 -20 28Z" />
            <path d="M20 25C30 24 39 22 47 19C38 20 29 21 20 22Z" />
            <path d="M20 31C30 32 38 34 46 38C37 33 29 30 20 28Z" />
          </g>

          {/* ── the turban ────────────────────────────────── */}
          <path d={TURBAN} fill={PALETTE.gold} transform="translate(-2.8 1.7)" opacity={0.55} />
          <path d={TURBAN} fill={PALETTE.gold} stroke={INK} strokeWidth={3.6} strokeLinejoin="round" />
          <g fill="none" stroke={INK} strokeWidth={2.4} strokeLinecap="round" opacity={0.7}>
            <path d="M-44 -36C-34 -54 -18 -64 0 -66C20 -66 36 -56 44 -38" />
            <path d="M-38 -48C-28 -60 -14 -68 0 -69" />
            <path d="M0 -69C16 -68 30 -60 38 -48" />
          </g>
          <path d={TURBAN_BAND} fill={PALETTE.violet} transform="translate(-2.8 1.7)" />
          <path
            d={TURBAN_BAND}
            fill={PALETTE.violet}
            stroke={INK}
            strokeWidth={2.6}
            strokeLinejoin="round"
          />
          {/* ears, drawn over the wrap so they break its outline — an ear
              that hides under the turban leaves a cat-shaped nothing */}
          <g fill={INK}>
            <path d={EAR_L} />
            <path d={EAR_R} />
          </g>
          <path d={EAR_L_IN} fill={PALETTE.violet} />
          <path d={EAR_R_IN} fill={PALETTE.violet} />
          <path d={GEM} fill={INK} transform="translate(-2.8 1.7)" />
          <path d={GEM} fill={PALETTE.paper} stroke={INK} strokeWidth={2.8} strokeLinejoin="round" />
          <path
            d="M0 -74L-6 -58L0 -38M-14 -58L14 -58"
            fill="none"
            stroke={INK}
            strokeWidth={1.8}
            opacity={0.65}
          />

          {/* ── the third eye ─────────────────────────────── */}
          <path
            d="M-26 -20C-15 -35 15 -35 26 -20C15 -5 -15 -5 -26 -20Z"
            fill={PALETTE.paper}
            stroke={INK}
            strokeWidth={3.2}
            strokeLinejoin="round"
          />
          <path d={IRIS} fill={PALETTE.gold} stroke={INK} strokeWidth={2} />
          <path d={SLIT} fill={INK} />
          {/* lashes radiating off it */}
          <g fill="none" stroke={INK} strokeWidth={2.2} strokeLinecap="round">
            <path d="M-24 -26C-28 -31 -31 -35 -33 -39" />
            <path d="M-12 -31C-13 -37 -14 -42 -14 -47" />
            <path d="M12 -31C13 -37 14 -42 14 -47" />
            <path d="M24 -26C28 -31 31 -35 33 -39" />
            <path d="M-22 -13C-26 -9 -29 -6 -32 -3" />
            <path d="M22 -13C26 -9 29 -6 32 -3" />
          </g>
        </g>
      </g>

      {/* ── the crystal ball ──────────────────────────────── */}
      <g filter="url(#ek-ink)">
        {/* clawed stand, bleeding into the title band */}
        <path
          d="M88 272C96 284 106 292 120 294C134 292 144 284 152 272C158 284 154 300 140 306L100 306C86 300 82 284 88 272Z"
          fill={INK}
        />
        <circle cx={BALL.cx - 2.8} cy={BALL.cy + 1.7} r={BALL.r} fill={PALETTE.gold} />
        <circle
          cx={BALL.cx}
          cy={BALL.cy}
          r={BALL.r}
          fill={PALETTE.paper}
          stroke={INK}
          strokeWidth={3.6}
        />
        {/* what is inside it: a halftone swirl and a small bomb */}
        <path
          d="M90 266C92 254 100 246 111 244C104 252 101 262 103 272C105 281 111 287 119 290C104 290 91 280 90 266Z"
          fill="url(#ek-halftone)"
          opacity={0.45}
        />
        <g transform="translate(123 258) scale(0.74)">
          <path d={BOMB} fill={INK} />
        </g>
        {/* specular crescent, top left */}
        <path
          d="M96 238C101 229 111 223 120 223C111 227 103 234 99 244Z"
          fill={PALETTE.paper}
          stroke={INK}
          strokeWidth={1.8}
        />
        <g fill={PALETTE.gold} stroke={INK} strokeWidth={1.4} strokeLinejoin="round">
          <g transform="translate(104 250) scale(0.55)">
            <path d={SPARK} />
          </g>
          <g transform="translate(138 274) scale(0.4)">
            <path d={SPARK} />
          </g>
        </g>
      </g>

      {/* ── the paws resting on the glass ─────────────────── */}
      <g filter="url(#ek-ink)">
        <g fill={PALETTE.gold} transform="translate(-2.8 1.7)">
          <path d={PAW_L} />
          <path d={PAW_R} />
        </g>
        <g fill={INK}>
          <path d={PAW_L} />
          <path d={PAW_R} />
        </g>
        <g fill="none" stroke={PALETTE.paper} strokeWidth={2.4} strokeLinecap="round" opacity={0.85}>
          <path d="M73 234C75 240 75 247 73 253" />
          <path d="M85 234C87 240 87 247 85 253" />
          <path d="M167 234C165 240 165 247 167 253" />
          <path d="M155 234C153 240 153 247 155 253" />
        </g>
      </g>
    </g>
  );
}
