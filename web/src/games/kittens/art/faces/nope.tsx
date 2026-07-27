/* ─────────────────────────────────────────────────────────────
   NOPE — red plate, ink.

   The family's third move. ATTACK rips, SKIP swerves, NOPE just
   lands on you. Same skeleton — flat plate, ray burst, halftone,
   ink subject, off-register plate — but the subject *is* the word.

   The letters are drawn as outlines rather than set in DM Sans on
   purpose: the deck's only shipped sans tops out at 600, and a
   card whose entire job is to be the loudest object on the table
   cannot be built out of semibold. Cut heavy, cut slightly wonky,
   knocked out of the red in paper with the ink plate showing on
   the left and top of every stem.

   Illustration is deliberately starved: one flat-eared cat looking
   down over the top of the stamp, unimpressed. Anything more and
   the word stops being the card.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

const RAYS: readonly string[] = Array.from({ length: 24 }, (_, i) => {
  const a = (i / 24) * Math.PI * 2 + 0.06;
  const h = 0.052;
  const r = 400;
  const x1 = (Math.cos(a - h) * r).toFixed(1);
  const y1 = (Math.sin(a - h) * r).toFixed(1);
  const x2 = (Math.cos(a + h) * r).toFixed(1);
  const y2 = (Math.sin(a + h) * r).toFixed(1);
  return `M0 0L${x1} ${y1}L${x2} ${y2}Z`;
});

/* ── letterforms ─────────────────────────────────────────────
   Each glyph is cut on a 100-unit cap height with the baseline at
   y=100. Stems are ~23 units, so this is a fat grotesque with slab
   energy. Every "straight" edge gets a shallow bow (the C segments
   with near-collinear controls) so the word looks knife-cut rather
   than drawn with a rectangle tool. O and P use evenodd counters. */
const N =
  "M2 3C9 1 17 1 25 3L49 60C48 41 48 22 49 3C57 1 65 1 72 3" +
  "C71 35 71 67 72 98C64 100 57 100 49 98L24 42C25 61 25 79 24 98" +
  "C16 100 9 100 2 98C3 66 3 35 2 3Z";

const O =
  "M36 0C58 0 72 20 72 50C72 80 58 100 36 100C14 100 0 80 0 50C0 20 14 0 36 0Z" +
  "M36 25C28 25 24 36 24 50C24 64 28 75 36 75C44 75 48 64 48 50C48 36 44 25 36 25Z";

const P =
  "M2 3C16 1 32 1 44 3C63 3 74 15 74 32C74 50 63 62 44 62L26 62" +
  "C27 74 27 86 26 98C17 100 9 100 2 98C3 66 3 35 2 3Z" +
  "M26 24L42 24C48 24 51 27 51 32C51 38 48 41 42 41L26 41Z";

const E =
  "M2 3L70 3C71 10 71 18 70 26L26 26L26 40L61 40C62 47 62 54 61 61L26 61L26 75" +
  "L72 75C73 83 73 91 72 98C48 100 25 100 2 98C3 66 3 35 2 3Z";

const GLYPHS: readonly { d: string; x: number; evenOdd: boolean }[] = [
  { d: N, x: 0, evenOdd: false },
  { d: O, x: 80, evenOdd: true },
  { d: P, x: 159, evenOdd: true },
  { d: E, x: 241, evenOdd: false },
];

function Word({ fill }: { fill: string }): ReactElement {
  return (
    <g transform="scale(0.62) translate(-156.5 -50)">
      {GLYPHS.map((g, i) => (
        <path
          key={i}
          d={g.d}
          fill={fill}
          fillRule={g.evenOdd ? "evenodd" : "nonzero"}
          transform={`translate(${g.x} 0)`}
        />
      ))}
    </g>
  );
}

/* ── the cat ─────────────────────────────────────────────────
   Ears raked out and *pointed* — the first cut had them as low
   rounded bumps, which at 60px turned the head into a bear. Skull
   wide, jaw heavy. It is not angry and it is not amused; it has
   simply already decided. */
const HEAD =
  "M-54 -14C-56 -32 -52 -48 -44 -56C-38 -49 -32 -38 -28 -27" +
  "C-18 -33 -8 -35 2 -34C13 -33 23 -30 31 -25" +
  "C35 -35 41 -47 47 -55C55 -46 59 -30 58 -12" +
  "C64 -2 65 10 58 21C48 36 22 46 0 45C-22 44 -46 34 -55 18C-61 8 -60 -5 -54 -14Z";

/* ── one eye, half-mast ──────────────────────────────────────
   The first cut stacked a wide oval pupil under a thin lid crescent
   inside a shallow almond. The pupil overshot the almond top *and*
   bottom, so it cut the white into two disconnected slivers and each
   eye rendered as a pair of white beans — four white blobs in a row
   across the face, which is a bug, not a cat.

   Rebuilt as the only half-lidded eye that survives 60px: full paper
   almond, a heavy ink lid eating the top third, and a vertical slit
   pupil that is *supposed* to touch top and bottom. The white then
   reads as two triangles either side of a slit, which is what a cat's
   eye actually looks like. Drawn for the left eye; mirrored on x. */
const EYE_WHITE = "M-36 -2C-27 -14 -9 -14 -1 -2C-9 7 -29 8 -36 -2Z";
const EYE_LID = "M-37 -2.6C-28 -15 -8 -15 0 -2.6C-8 -6.8 -29 -7.4 -37 -2.6Z";
const EYE_SLIT =
  "M-18.5 -6C-15 -6 -13.5 -2.5 -13.5 1C-13.5 4.5 -15 7.2 -18.5 7.2" +
  "C-22 7.2 -23.5 4.5 -23.5 1C-23.5 -2.5 -22 -6 -18.5 -6Z";
const EYE_LASH = "M-36 -2C-27 -14 -9 -14 -1 -2";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate ─────────────────────────────────────────── */}
      <rect
        x={6}
        y={6}
        width={228}
        height={288}
        fill={PALETTE.red}
        filter="url(#ek-grain)"
      />

      {/* ── ray burst, dead centre behind the word ────────── */}
      <g transform="translate(120 168)" fill={INK} opacity={0.13}>
        {RAYS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>

      {/* ── tone ──────────────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={70} fill="url(#ek-halftone)" opacity={0.18} />
      <rect x={6} y={232} width={228} height={62} fill="url(#ek-halftone)" opacity={0.22} />

      {/* ── edge ticks: cheap print-shop density down the sides ── */}
      <g fill={INK} opacity={0.35}>
        {Array.from({ length: 9 }, (_, i) => (
          <rect key={`l${i}`} x={12} y={70 + i * 22} width={9} height={3} />
        ))}
        {Array.from({ length: 9 }, (_, i) => (
          <rect key={`r${i}`} x={219} y={70 + i * 22} width={9} height={3} />
        ))}
      </g>

      {/* ── the cat, looking down over the stamp ────────────
          The under-plate used to be INK at half opacity, which on a red
          field is a drop shadow, not a misprint. It is paper now: the
          fringe reads bright on the left and bottom of the skull, and it
          matches the paper-over-ink registration used on the word. */}
      <g transform="translate(117.2 69.7) scale(0.85)">
        <path d={HEAD} fill={PALETTE.paper} opacity={0.85} />
      </g>
      <g transform="translate(120 68) scale(0.85)" filter="url(#ek-ink)">
        <path d={HEAD} fill={INK} />

        {/* inner ears */}
        <path d="M-45 -47C-40 -38 -36 -32 -32 -27C-39 -29 -44 -32 -47 -35Z" fill={PALETTE.red} />
        <path d="M48 -46C43 -37 39 -31 35 -26C42 -28 47 -31 50 -34Z" fill={PALETTE.red} />

        {/* eyes: paper almond, ink lid down over the top third, slit
            pupil. Half-lidded plus a flat mouth is the whole
            performance — see the note on EYE_WHITE. */}
        <g>
          <path d={EYE_WHITE} fill={PALETTE.paper} />
          <path d={EYE_SLIT} fill={INK} />
          <path d={EYE_LID} fill={INK} />
          <path
            d={EYE_LASH}
            fill="none"
            stroke={INK}
            strokeWidth={3.4}
            strokeLinecap="round"
          />
        </g>
        <g transform="scale(-1 1)">
          <path d={EYE_WHITE} fill={PALETTE.paper} />
          <path d={EYE_SLIT} fill={INK} />
          <path d={EYE_LID} fill={INK} />
          <path
            d={EYE_LASH}
            fill="none"
            stroke={INK}
            strokeWidth={3.4}
            strokeLinecap="round"
          />
        </g>

        {/* nose, pulled up off the chin, and the flattest mouth that can
            be drawn. They used to sit edge-to-edge at y 25/32 and fused
            with the whiskers into a moustache. */}
        <path d="M0 8C4 8 7 10 7 13C7 16 3 19 0 21C-3 19 -7 16 -7 13C-7 10 -4 8 0 8Z" fill={PALETTE.red} />
        <path
          d="M-16 26C-8 24.4 8 24.4 16 26"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={3.4}
          strokeLinecap="round"
          opacity={0.92}
        />
        {/* whiskers */}
        <path d="M-26 18C-38 16 -50 16 -62 18C-50 21 -38 23 -26 22Z" fill={PALETTE.paper} opacity={0.9} />
        <path d="M-25 26C-36 28 -46 31 -55 36C-45 35 -35 32 -25 30Z" fill={PALETTE.paper} opacity={0.9} />
        <path d="M26 18C38 16 50 16 62 18C50 21 38 23 26 22Z" fill={PALETTE.paper} opacity={0.9} />
        <path d="M25 26C36 28 46 31 55 36C45 35 35 32 25 30Z" fill={PALETTE.paper} opacity={0.9} />
      </g>

      {/* ── the stamp ─────────────────────────────────────── */}
      <g transform="translate(120 174) rotate(-7)">
        {/* rule box: ink plate, then paper hairline inside it */}
        <rect
          x={-105}
          y={-62}
          width={210}
          height={124}
          rx={8}
          fill="none"
          stroke={INK}
          strokeWidth={4}
          filter="url(#ek-ink)"
        />
        <rect
          x={-97}
          y={-54}
          width={194}
          height={108}
          rx={5}
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={1.6}
          strokeDasharray="7 5"
          opacity={0.75}
        />

        {/* the word: ink plate laid down first, paper struck on top
            2.6px to the right — the misprint reads as an ink fringe
            on every left and top edge. */}
        <g transform="translate(-2.6 1.7)">
          <Word fill={INK} />
        </g>
        <g filter="url(#ek-ink)">
          <Word fill={PALETTE.paper} />
        </g>

        {/* small print under the word — dropped 3px and set a size
            smaller, because at y=50/18 the ascenders were grazing the
            bowl of the P and the crossbar of the E */}
        <text
          x={0}
          y={53}
          textAnchor="middle"
          fontFamily='"Instrument Serif", Georgia, serif'
          fontStyle="italic"
          fontSize={17}
          fill={PALETTE.paper}
          opacity={0.92}
        >
          absolutely not
        </text>
      </g>

      {/* ── struck-out paw, bottom-left ─────────────────────
          Was ink-on-red at 0.85 and 0.82 scale: at card size it read as
          a smudge and at 60px it disappeared entirely, leaving the whole
          bottom band empty. Knocked out of the paper plate instead, half
          again as big, with the bar struck through in solid ink. */}
      <g transform="translate(40 264) rotate(-14) scale(1)">
        <g fill={PALETTE.paper} opacity={0.94}>
          <path d="M-13 5C-9 -4 9 -4 13 5C16 12 10 19 0 19C-10 19 -16 12 -13 5Z" />
          <path d="M-15 -8C-11 -8 -8 -4 -9 0C-11 4 -15 5 -18 2C-20 -1 -19 -8 -15 -8Z" />
          <path d="M-4 -14C0 -14 3 -10 2 -5C0 -1 -4 0 -7 -3C-9 -7 -8 -14 -4 -14Z" />
          <path d="M8 -13C12 -12 13 -7 11 -3C8 0 4 0 3 -4C2 -9 4 -14 8 -13Z" />
          <path d="M17 -5C20 -4 21 0 19 3C16 6 12 4 12 1C11 -3 14 -6 17 -5Z" />
        </g>
        <path
          d="M-14 16L20 -10"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={9}
          strokeLinecap="round"
          opacity={0.55}
          transform="translate(-2.6 1.7)"
        />
        <path
          d="M-14 16L20 -10"
          fill="none"
          stroke={INK}
          strokeWidth={7}
          strokeLinecap="round"
          filter="url(#ek-ink)"
        />
      </g>
    </g>
  );
}
