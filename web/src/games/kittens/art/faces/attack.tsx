/* ─────────────────────────────────────────────────────────────
   ATTACK — violet plate, red plate.

   The composition every "whose problem is this now" card shares:
   flat accent plate → ray burst → halftone tone field → ink subject
   with an off-register accent plate under it → one paper-coloured
   graphic device on top.

   The device here is claw rips that tear the violet plate back to
   bare stock, with the red plate showing on the wrong side of each
   gash. Two four-gash clusters: one behind the head out of the
   top-left, one in front down the right gutter. Neither crosses the
   face — the eyes are the reason the cat is drawn at all: ears
   pinned, brows crushed onto them, pupils shrunk to pinpricks,
   mid-snarl.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* Ray burst, generated once at module load so the card never re-rolls. */
const RAYS: readonly string[] = Array.from({ length: 18 }, (_, i) => {
  const a = (i / 18) * Math.PI * 2 + 0.14;
  const h = 0.082;
  const r = 400;
  const x1 = (Math.cos(a - h) * r).toFixed(1);
  const y1 = (Math.sin(a - h) * r).toFixed(1);
  const x2 = (Math.cos(a + h) * r).toFixed(1);
  const y2 = (Math.sin(a + h) * r).toFixed(1);
  return `M0 0L${x1} ${y1}L${x2} ${y2}Z`;
});

/* ── the head ────────────────────────────────────────────────
   One closed contour, clockwise from the middle of the forehead:
   right ear base → tip → back edge → cheek → jaw → chin → and the
   mirror of all of it. Ears rake backwards rather than standing up,
   which is the difference between a cross cat and a curious one. */
const HEAD =
  "M0 -30C10 -32 19 -34 26 -34C33 -46 44 -55 58 -60" +
  "C56 -46 51 -33 45 -24C53 -18 58 -10 57 -2C59 10 55 21 50 27" +
  "C42 40 33 47 24 49C16 53 8 54 0 53C-8 54 -16 53 -24 49" +
  "C-33 47 -42 40 -50 27C-55 21 -59 10 -57 -2C-58 -10 -53 -18 -45 -24" +
  "C-51 -33 -56 -46 -58 -60C-44 -55 -33 -46 -26 -34C-19 -34 -10 -32 0 -30Z";

/* Cheek tufts welded onto the outline so the silhouette is torn
   rather than moulded. */
const TUFTS = [
  "M-50 22C-60 24 -69 22 -77 18C-68 18 -58 18 -51 17Z",
  "M-44 38C-52 44 -61 47 -69 47C-62 42 -53 38 -46 34Z",
  "M50 22C60 24 69 22 77 18C68 18 58 18 51 17Z",
  "M44 38C52 44 61 47 69 47C62 42 53 38 46 34Z",
];

/* A single claw. Short, fat at the base, hooked — the first cut was a
   55-unit needle, and four needles fanned off the back of a paw read as
   a comb, not a cat. This one is 34 long and its base is buried under
   the paw silhouette so it grows out of the toe instead of floating. */
const CLAW = "M0 0C2 -10 8 -20 21 -29C11 -25 3 -18 -4 -9C-8 -3 -6 3 0 0Z";

/* Paw, seen from the back mid-swipe. The first cut was a smooth bean
   with four toe *bumps* so shallow they vanished, plus a full set of
   pads on the same face — a paw cannot show you its pads and the back
   of its claws at once, and what it actually rendered as was a black
   egg wearing a comb. Redrawn with four toes cut deep enough to read
   as separate toes at 60px, and the pads gone, because this is the
   back of the paw. */
const PAW =
  "M-34 22C-40 6 -32 -8 -16 -13" +
  "C-14 -22 -4 -25 3 -19" +
  "C7 -28 19 -29 24 -21" +
  "C31 -28 43 -25 45 -15" +
  "C54 -16 61 -8 59 2" +
  "C66 14 60 32 46 40" +
  "C30 49 6 49 -10 41C-24 34 -32 31 -34 22Z";

/* Toe splits, in the red plate — the only thing keeping the four toes
   apart once the ink filter fattens the outline. */
const TOE_SPLITS =
  "M4 -18C4 -11 4 -5 3 1" + "M27 -20C27 -13 26 -7 25 -2" + "M49 -12C49 -6 47 0 45 5";

/* Claw anchored just *inside* each toe tip, fanned with the toe it
   belongs to across an 84° spread, all raking the same way as the
   swipe. */
const CLAWS: readonly { x: number; y: number; r: number }[] = [
  { x: -4, y: -19, r: -56 },
  { x: 16, y: -24, r: -28 },
  { x: 38, y: -21, r: -2 },
  { x: 57, y: -5, r: 28 },
];

/* ── the rips ────────────────────────────────────────────────
   The first cut ran three 228-unit slits the full height of the card,
   evenly spaced and all parallel. Three long parallel white bars is
   not a claw strike; it is venetian blinds, and one of them went
   straight through the ×2 badge.

   A claw strike reads as a *cluster*: four short gashes, tight
   spacing, unequal lengths, all raked the same way. Two clusters here
   — one behind the head off the top-left, one in front down the right
   gutter — so the card is struck twice, which is the card's whole
   rule. GASH is 122 long, sharp at both ends, fattest past halfway;
   squashed on x at placement so it stays a slit rather than a banana. */
const GASH =
  "M0 0C-6 26 -9 56 -8 84C-7 102 -5 114 -2 122" +
  "C-1 102 1 76 2 52C3 32 2 15 0 0Z";

type Rip = { x: number; y: number; r: number; s: number };
/* Rakes down-right out of the top-left corner, dying behind the ears. */
const RIPS_BEHIND: readonly Rip[] = [
  { x: 24, y: -4, r: -24, s: 0.72 },
  { x: 46, y: -10, r: -21, s: 1.0 },
  { x: 68, y: -2, r: -18, s: 0.84 },
  { x: 88, y: -12, r: -15, s: 0.52 },
];
/* The cluster that cuts in front — down the right gutter, through the
   dead violet under the badge. It has to miss the eyes or the
   expression dies, so it starts below the muzzle line. */
const RIPS_FRONT: readonly Rip[] = [
  { x: 230, y: 168, r: 19, s: 0.86 },
  { x: 212, y: 180, r: 17, s: 1.06 },
  { x: 194, y: 192, r: 15, s: 0.78 },
  { x: 178, y: 204, r: 13, s: 0.46 },
];

function Rips({ rips, fill }: { rips: readonly Rip[]; fill: string }): ReactElement {
  return (
    <g>
      {rips.map((p, i) => (
        <path
          key={i}
          d={GASH}
          fill={fill}
          transform={`translate(${p.x} ${p.y}) rotate(${p.r}) scale(${p.s} 1)`}
        />
      ))}
    </g>
  );
}

/* Twelve-point burst behind the ×2. */
const BURST: string = (() => {
  const pts: string[] = [];
  for (let i = 0; i < 24; i += 1) {
    const a = (i / 24) * Math.PI * 2 - Math.PI / 2;
    const r = i % 2 === 0 ? 30 : 21;
    pts.push(`${(Math.cos(a) * r).toFixed(1)} ${(Math.sin(a) * r).toFixed(1)}`);
  }
  return `M${pts.join("L")}Z`;
})();

const PAW_AT = "translate(56 248) rotate(-6) scale(0.8)";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate ─────────────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={288} fill={PALETTE.violet} filter="url(#ek-grain)" />

      {/* ── ray burst behind the skull ────────────────────── */}
      <g transform="translate(120 138)" fill={INK} opacity={0.15}>
        {RAYS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>

      {/* ── tone fields ───────────────────────────────────── */}
      <rect x={6} y={198} width={228} height={96} fill="url(#ek-halftone-red)" opacity={0.26} />
      <rect x={6} y={6} width={228} height={58} fill="url(#ek-halftone)" opacity={0.16} />

      {/* ── rips behind the subject ───────────────────────── */}
      <g transform="translate(-2.8 1.7)">
        <Rips rips={RIPS_BEHIND} fill={PALETTE.red} />
      </g>
      <g filter="url(#ek-ink)">
        <Rips rips={RIPS_BEHIND} fill={PALETTE.paper} />
      </g>

      {/* ── off-register red plate under the whole subject ── */}
      <g transform="translate(-2.8 1.7)" fill={PALETTE.red} opacity={0.92}>
        <g transform="translate(120 138)">
          <path d={HEAD} />
          {TUFTS.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        <g transform={PAW_AT}>
          <path d={PAW} />
          {CLAWS.map((c, i) => (
            <path key={i} d={CLAW} transform={`translate(${c.x} ${c.y}) rotate(${c.r})`} />
          ))}
        </g>
      </g>

      {/* ── ink linework ──────────────────────────────────── */}
      <g filter="url(#ek-ink)">
        {/* paw, lower left, already swinging */}
        <g transform={PAW_AT}>
          <path d={PAW} fill={INK} />
          {CLAWS.map((c, i) => (
            <path
              key={i}
              d={CLAW}
              transform={`translate(${c.x} ${c.y}) rotate(${c.r})`}
              fill={INK}
            />
          ))}
          {/* toe splits in the red plate, and a fur break across the
              wrist so the paw has a direction */}
          <path
            d={TOE_SPLITS}
            fill="none"
            stroke={PALETTE.red}
            strokeWidth={3.4}
            strokeLinecap="round"
          />
          <path
            d="M-26 20C-22 27 -18 31 -13 34M-16 12C-13 20 -10 26 -6 31"
            fill="none"
            stroke={PALETTE.red}
            strokeWidth={2.8}
            strokeLinecap="round"
            opacity={0.7}
          />
        </g>

        {/* head */}
        <g transform="translate(120 138)">
          <path d={HEAD} fill={INK} />
          {TUFTS.map((d, i) => (
            <path key={i} d={d} fill={INK} />
          ))}

          {/* inner ears */}
          <path d="M-50 -49C-46 -38 -42 -30 -37 -25C-43 -32 -48 -41 -51 -50Z" fill={PALETTE.red} />
          <path d="M50 -49C46 -38 42 -30 37 -25C43 -32 48 -41 51 -50Z" fill={PALETTE.red} />
          <path
            d="M-49 -48C-45 -37 -41 -30 -36 -24"
            fill="none"
            stroke={PALETTE.red}
            strokeWidth={6}
            strokeLinecap="round"
          />
          <path
            d="M49 -48C45 -37 41 -30 36 -24"
            fill="none"
            stroke={PALETTE.red}
            strokeWidth={6}
            strokeLinecap="round"
          />

          {/* eyes — narrowed almonds, pupils shrunk and pulled inward.
              This is the entire expression; everything else is framing. */}
          <path d="M-41 -8C-33 -19 -14 -18 -7 -4C-16 5 -35 4 -41 -8Z" fill={PALETTE.paper} />
          <path d="M41 -8C33 -19 14 -18 7 -4C16 5 35 4 41 -8Z" fill={PALETTE.paper} />
          <path
            d="M-20 -12C-16 -12 -14 -8 -14 -4C-14 0 -16 3 -20 3C-24 3 -26 0 -26 -4C-26 -8 -24 -12 -20 -12Z"
            fill={INK}
          />
          <path
            d="M20 -12C24 -12 26 -8 26 -4C26 0 24 3 20 3C16 3 14 0 14 -4C14 -8 16 -12 20 -12Z"
            fill={INK}
          />

          {/* brows, driven down onto the eyes */}
          <path d="M-49 -27C-38 -23 -26 -16 -15 -6L-19 1C-30 -8 -41 -15 -51 -19Z" fill={INK} />
          <path d="M49 -27C38 -23 26 -16 15 -6L19 1C30 -8 41 -15 51 -19Z" fill={INK} />

          {/* nose */}
          <path d="M0 6C5 6 9 8 9 12C9 16 4 20 0 22C-4 20 -9 16 -9 12C-9 8 -5 6 0 6Z" fill={PALETTE.red} />

          {/* snarl */}
          <path d="M-22 24C-13 19 13 19 22 24C22 42 12 52 0 52C-12 52 -22 42 -22 24Z" fill={INK} />
          <path d="M-13 37C-6 34 6 34 13 37C11 46 6 50 0 50C-6 50 -11 46 -13 37Z" fill={PALETTE.red} />
          <path d="M-16 23C-13 22 -9 22 -7 23L-11 38Z" fill={PALETTE.paper} />
          <path d="M16 23C13 22 9 22 7 23L11 38Z" fill={PALETTE.paper} />
          <path d="M-9 50C-7 51 -3 51 -1 50L-5 41Z" fill={PALETTE.paper} />
          <path d="M9 50C7 51 3 51 1 50L5 41Z" fill={PALETTE.paper} />

          {/* whiskers — tapered slivers, not strokes */}
          <path d="M-32 17C-46 12 -60 9 -74 9C-60 13 -46 18 -32 21Z" fill={INK} />
          <path d="M-31 27C-45 27 -58 29 -70 34C-57 34 -44 33 -31 31Z" fill={INK} />
          <path d="M32 17C46 12 60 9 74 9C60 13 46 18 32 21Z" fill={INK} />
          <path d="M31 27C45 27 58 29 70 34C57 34 44 33 31 31Z" fill={INK} />
        </g>
      </g>

      {/* ── motion streaks off the paw ──────────────────────
          Red at 2.6px on a violet plate is two values apart and
          vanished. Paper, and the stray third arc that ran off under
          the paw pointing at nothing is gone. */}
      <g
        stroke={PALETTE.paper}
        strokeWidth={3}
        strokeLinecap="round"
        opacity={0.5}
        fill="none"
      >
        <path d="M20 214C13 233 15 255 26 272" />
        <path d="M35 204C26 222 24 242 31 260" />
      </g>

      {/* ── ×2 badge, top right ───────────────────────────── */}
      <g transform="translate(190 64) rotate(-11)">
        <path d={BURST} fill={PALETTE.red} transform="translate(-2.8 1.7)" />
        <g filter="url(#ek-ink)">
          <path d={BURST} fill={INK} />
        </g>
        <text
          x={0}
          y={1}
          textAnchor="middle"
          dominantBaseline="central"
          fontFamily='"DM Sans", system-ui, sans-serif'
          fontWeight={600}
          fontSize={22}
          letterSpacing={-1}
          fill={PALETTE.paper}
        >
          ×2
        </text>
      </g>

      {/* ── the rip that cuts in front ────────────────────── */}
      <g transform="translate(-2.8 1.7)">
        <Rips rips={RIPS_FRONT} fill={PALETTE.red} />
      </g>
      <g filter="url(#ek-ink)">
        <Rips rips={RIPS_FRONT} fill={PALETTE.paper} />
      </g>
    </g>
  );
}
