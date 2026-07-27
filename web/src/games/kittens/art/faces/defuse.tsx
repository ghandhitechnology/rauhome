/* ─────────────────────────────────────────────────────────────
   defuse — relief.

   Deliberately the inverse of exploding_kitten in every register:
   concentric calm rings instead of radiating rays, a curled sleeping
   cat instead of a screaming one, cool foil instead of warm, and the
   loudest object on the card (the bomb) rendered harmless — its fuse
   snipped, the severed end drifting off with one thread of smoke.

   Plates: blue field, ink linework, green accent. The green plates under the
   shears, the cat and the leaves are each duplicated by hand a pixel or
   two off, so the registration is visibly wrong.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE } from "../defs";

/* ── calm rings: the opposite gesture to a blast ─────────────── */
const RING_C = { x: 122, y: 190 } as const;
const RINGS = [46, 66, 88, 112, 138, 166, 196].map((r, i) => ({
  r,
  /* each ring is a broken arc, rotated a little further round, so the
     gaps spiral instead of stacking into a seam */
  d: describeArc(RING_C.x, RING_C.y, r, -122 + i * 37, 232 + i * 37),
}));

function describeArc(
  cx: number,
  cy: number,
  r: number,
  startDeg: number,
  endDeg: number,
): string {
  const rad = (d: number) => (d * Math.PI) / 180;
  const x0 = (cx + Math.cos(rad(startDeg)) * r).toFixed(2);
  const y0 = (cy + Math.sin(rad(startDeg)) * r).toFixed(2);
  const x1 = (cx + Math.cos(rad(endDeg)) * r).toFixed(2);
  const y1 = (cy + Math.sin(rad(endDeg)) * r).toFixed(2);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M${x0} ${y0}A${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

/* ── the bomb, now inert ─────────────────────────────────────
   Not a circle: the left shoulder is fuller than the right, and the
   base flattens slightly where it rests. */
const BOMB = `M120 128
  C157 127 185 156 185 192
  C185 228 157 256 121 256
  C85 256 57 228 57 192
  C57 157 84 129 120 128Z`;

/* Specular sliver. The previous highlight was a broad soft-looking
   white crescent, and combined with the foil gradient it turned the
   bomb into a rendered glass ball — exactly the "gradient-mesh realism"
   the spec bans. A screenprint gets one hard-edged flick of paper and
   nothing else, so this is narrow, and the sphere's roundness is now
   carried by the halftone screen instead of by a glow. */
const BOMB_SHINE = `M84 170C90 156 100 147 112 143C103 152 95 162 91 173
  C87 184 86 194 88 202C82 194 81 180 84 170Z`;
/* Second, tiny, further round the shoulder — reads as a printed dot of
   paper, not as light. */
const BOMB_GLINT = `M100 218C104 216 109 218 110 221C111 224 107 226 103 225
  C99 224 97 220 100 218Z`;

/* Terminator line: screened shadow on the lower right so the sphere is
   a sphere and not a coloured disc. */
const BOMB_SHADE = `M185 190C185 228 157 256 121 256C104 256 88 250 76 239
  C93 248 116 248 136 238C160 226 176 202 176 176C176 162 172 149 165 139
  C177 152 185 170 185 190Z`;

/* ── the ferrule ─────────────────────────────────────────────
   Was a single flat quadrilateral laid at an angle across the bomb's
   shoulder. Filled green and seen against blue it read as a traffic
   cone — or as a leaf, since this card has three actual leaves on it —
   and it gave the sphere nothing to *be a bomb with*: a featureless
   ball plus a gradient is a marble.

   So it is now a real object: a short tapered cylinder standing on the
   shoulder, with a lip at the top and a raised band round its middle.
   Drawn in a local frame with its base at the origin and planted by a
   transform, so the geometry stays checkable — the base sits ~15 units
   inside the rim, and the cat's back crosses it, which is what makes
   the fuse read as coming out from behind the cat. */
const FERRULE_BODY = `M-13 4C-13 -6 -11.5 -20 -10.5 -30
  C-10.5 -32.5 10.5 -32.5 10.5 -30
  C11.5 -20 13 -6 13 4C13 7.5 -13 7.5 -13 4Z`;
const FERRULE_BAND = `M-11.8 -13C-11.8 -15 11.8 -15 11.8 -13
  C11.9 -9 11.95 -6 12 -3C12 -1 -12 -1 -12 -3C-11.95 -6 -11.9 -9 -11.8 -13Z`;
const FERRULE_LIP = `M-10.6 -28.5C-10.6 -31.5 10.6 -31.5 10.6 -28.5
  C10.6 -25.5 -10.6 -25.5 -10.6 -28.5Z`;

/* The fuse: one continuous line out of the ferrule that simply stops.
   The old cut put its three threads as parallel dashes *beside* the
   fuse rather than radiating from its end, so it read as hatching. All
   three now start at the cut point itself. */
const FUSE_STUB = `M164 112C172 100 182 99 186 89`;
const FUSE_FRAY = `M186 89L194 85M186 89L194.5 92M186 89L190.5 80.5`;
/* The severed length, lying where it fell, still smoking. */
const FUSE_LOOSE = `M201 70C209 64 206 55 213 50`;
const SMOKE = `M213 45C218 38 210 32 215 25`;

/* ── shears ──────────────────────────────────────────────────
   Not the frame's pip glyph blown up. The pip is an X of even-width
   strokes plus two rings, which is legible at 20px because it is a
   symbol; at illustration size it reads as a scribbled asterisk, and
   it duplicates a mark the card already carries twice in its corners.

   These are drawn as objects: two filled blades that taper from a wide
   pivot to a point, and two open handle rings on stroked shanks. The
   blades therefore hold a silhouette at 60px where stroked lines do
   not, and the pair reads as scissors rather than as a star. */
const BLADE_L = `M-35 -33C-30 -28.5 -13 -11 -3 -2
  C1 1.5 1 6 -3 8.5C-7 11 -11 9.5 -14 5.5
  C-21 -3.5 -33 -22.5 -36 -28.5C-37.5 -31.5 -36.5 -34.5 -35 -33Z`;
const BLADE_R = `M27 -33C22 -28.5 8 -12 -1 -3.5
  C-5 0 -5 4.5 -1 7C3 9.5 7 8 10 4C16 -4 25 -22 27.5 -28
  C29 -31.5 28.5 -34.5 27 -33Z`;
/* Handles: shank + open ring, drawn as strokes because a handle is a
   loop of steel, not a slab. */
const SHANK_L = `M-6 7C-11 14 -17 20 -21 24`;
const SHANK_R = `M2 7C6 14 11 20 15 24`;
const RING_L = `M-25 22C-19.5 22 -15 26.5 -15 32C-15 37.5 -19.5 42 -25 42
  C-30.5 42 -35 37.5 -35 32C-35 26.5 -30.5 22 -25 22Z`;
const RING_R = `M19 22C24.5 22 29 26.5 29 32C29 37.5 24.5 42 19 42
  C13.5 42 9 37.5 9 32C9 26.5 13.5 22 19 22Z`;
const SHEAR_PIVOT = `M-2 -1C1.6 -1 4.2 1.6 4.2 5.2C4.2 8.8 1.6 11.4 -2 11.4
  C-5.6 11.4 -8.2 8.8 -8.2 5.2C-8.2 1.6 -5.6 -1 -2 -1Z`;

/* ── the cat, curled and unbothered ──────────────────────────
   Local frame centred at the middle of the curl. The back is one long
   unbroken curve — that single line is what makes it read as "asleep"
   rather than "sitting". */
const BODY = `M-54 24
  C-63 6 -52 -16 -28 -27
  C-4 -38 26 -34 44 -16
  C60 0 58 24 42 33
  C26 42 2 40 -18 37
  C-34 34 -48 36 -54 24Z`;

/* The rear leg folded under. Drawn as a full closed curve, not a stray
   arc, so it reads as a limb sitting on top of the flank. */
const HAUNCH = `M12 4C29 -1 47 8 49 24C43 14 30 9 15 11C4 12 -2 8 12 4Z`;
/* Chest line and the fold where the shoulder meets the foreleg. Without
   these the body is one uninterrupted white field and the curl has no
   anatomy in it at all. */
const CHEST = `M-38 12C-32 22 -22 29 -10 31M-2 -20C4 -12 8 -2 8 8`;
/* Screened underside — the shadow the body casts on itself. Only the
   belly and the far flank get it; a screen over the whole body just
   makes the cat grey. */
const BELLY_SHADE = `M-52 22C-42 34 -16 40 12 38C32 36.5 50 30 55 19
  C53 34 30 42 4 41C-22 40 -48 36 -52 22Z`;

/* Tail wrapping forward over the paws — the classic full-stop. It
   tapers to a real tip; a tail of even width reads as an arm. */
const TAIL = `M48 20C68 25 75 46 60 57C46 67 16 63 -8 53
  C14 58 42 58 52 49C61 41 58 30 44 26Z`;

/* Front paws tucked under the chin. Without these the curl reads as a
   loaf of bread. */
const PAW_A = `M-33 24C-25 21.5 -16 24 -14 29.5C-12.5 34 -19 37.5 -27 36.5
  C-35 35.5 -39 26.5 -33 24Z`;
const PAW_B = `M-13 27C-6 25 2 27.5 3.5 32C5 36 -0.5 39 -7.5 38C-14.5 37 -18 29 -13 27Z`;
const PAW_TOES = `M-30 25.5C-30.5 29.5 -30 33 -28.5 36M-23 24.5C-23.5 28.5 -23 32.5 -21.5 35.5
  M-10 28C-10.5 31.5 -10 34.5 -8.5 37.5M-3.5 28.5C-4 32 -3.5 35 -2 37.5`;

const HEAD = `M-24 -4
  C-24 -15 -18.5 -23.5 -10 -27.5
  L-20.5 -41.5C-22 -43.5 -20 -46 -17.5 -44.5
  L-4.5 -36C-0.5 -37 4.5 -37 8.5 -36
  L21 -44.5C23.5 -46 25.5 -43.5 24 -41.5
  L14 -27.5C22.5 -23.5 28 -15 28 -4
  C28 12 16.5 24.5 2 24.5
  C-12.5 24.5 -24 12 -24 -4Z`;

const EAR_L = `M-18.5 -41C-14 -34.5 -11 -30 -9 -27.5C-11 -28.5 -13 -30 -15 -31.5
  C-16.5 -34.5 -18 -38 -18.5 -41Z`;
const EAR_R = `M22 -43.5C18.5 -36.5 15.5 -31.5 13.5 -28.5C15 -29.5 17.5 -31 19 -32
  C20 -35 21.5 -40 22 -43.5Z`;

/* Not asleep — *pretending*. The left eye is shut in the usual
   contented arc; the right is cracked open a slit and looking straight
   out of the card at you. Two shut eyes make a decorative cat; one shut
   and one open makes a cat that knows exactly what it just got away
   with, which is what this card is about. */
const EYE_L = `M-16 1C-12.5 -6 -6 -6 -2.5 1`;
const EYE_R_OPEN = `M4 -2C7.5 -9.5 16 -10 19.5 -2.5C16 2.8 7.5 3 4 -2Z`;
const PUPIL_R = `M12 -5.4C14 -5.4 15.4 -3.7 15.4 -1.5C15.4 0.7 14 2.2 12 2.2
  C10 2.2 8.6 0.7 8.6 -1.5C8.6 -3.7 10 -5.4 12 -5.4Z`;
/* Lid pulled down over the top of that eye, so it reads half-mast
   rather than merely small. */
const LID_R = `M3.5 -2.6C7 -9.8 16 -10.4 20 -3.2`;
/* One corner up, one corner level — a smirk, not a symmetric cat mouth. */
const MOUTH = `M-2 12.5C0.5 15.6 4.5 15 6 11.5M6 11.5C8.6 14.4 13 13.2 15 9.4`;
const NOSE = `M3 5.5L11 5.5C12 5.5 12.4 6.7 11.6 7.4L8.2 10.2
  C7.6 10.7 6.7 10.7 6.1 10.2L2.6 7.4C1.8 6.7 2.2 5.5 3 5.5Z`;
const WHISKERS = `M-23 3C-33 1 -41 2.5 -47 6M-22 8C-32 9 -40 13 -45 19
  M-21 13C-30 16 -37 21 -41 28M26 6C33 4.5 39 6.5 43 10`;

/* Sleep marks — three, decreasing, drifting up and away from the head. */
const ZEE = `M-6 -8H6L-6 8H6`;

/* ── catnip ─────────────────────────────────────────────────── */
/* Serrated on the top edge, smooth underneath — catnip, not a petal. */
const LEAF = `M0 0C4 -7 8 -10 11 -12L12.5 -8L16 -14L18 -9.5L21.5 -15L23.5 -10.5L27 -14.5
  L28.5 -10.5L31 -9C25 4 7 10 0 0Z`;
const LEAF_VEIN = `M2 -1C9 -4 18 -7 27 -9M9 1.5C11 -1.5 12 -4.5 12.5 -8M16.5 0.5C18 -3 18.5 -6 18 -9.5
  M23.5 -2C25 -5 25.5 -7.5 25 -10`;

function Leaf({
  x,
  y,
  r,
  s,
}: {
  x: number;
  y: number;
  r: number;
  s: number;
}): ReactElement {
  return (
    <g transform={`translate(${x} ${y}) rotate(${r}) scale(${s})`}>
      <path d={LEAF} fill={PALETTE.paper} transform="translate(-1.5 1)" opacity={0.8} />
      <path
        d={LEAF}
        fill={PALETTE.green}
        stroke={PALETTE.ink}
        strokeWidth={2.4}
        strokeLinejoin="round"
        filter="url(#ek-ink)"
      />
      <path
        d={LEAF_VEIN}
        fill="none"
        stroke={PALETTE.ink}
        strokeWidth={1.4}
        strokeLinecap="round"
        opacity={0.7}
      />
    </g>
  );
}

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate 1: the cool field ──────────────────────────── */}
      <rect x={0} y={0} width={240} height={300} fill={PALETTE.blue} filter="url(#ek-grain)" />

      {/* tone: light at the centre, screened down at the edges — the
          exact inverse of the kitten card's hot middle */}
      <rect x={0} y={0} width={240} height={78} fill="url(#ek-halftone)" opacity={0.15} />
      <rect x={0} y={236} width={240} height={64} fill="url(#ek-halftone)" opacity={0.15} />
      <rect x={0} y={0} width={54} height={300} fill="url(#ek-halftone-fine)" opacity={0.12} />
      <rect x={188} y={0} width={52} height={300} fill="url(#ek-halftone-fine)" opacity={0.12} />

      {/* ── calm rings ───────────────────────────────────────── */}
      <g fill="none" stroke={PALETTE.ink} strokeLinecap="round" opacity={0.3}>
        {RINGS.map((ring, i) => (
          <path key={ring.r} d={ring.d} strokeWidth={i % 2 === 0 ? 2.4 : 1.3} />
        ))}
      </g>
      <g fill="none" stroke={PALETTE.green} strokeLinecap="round" opacity={0.55}>
        {RINGS.filter((_, i) => i % 3 === 1).map((ring) => (
          <path key={ring.r} d={ring.d} strokeWidth={2} transform="translate(-1.5 1)" />
        ))}
      </g>

      {/* Ground shadow. Gives the bomb weight — it is resting, not
          floating — and stops the bottom band of the card going to bare
          screened blue now the laser pointer is gone. */}
      <path
        d="M34 254C34 242 73 234 122 234C171 234 208 242 208 254C208 266 171 274 122 274
           C73 274 34 266 34 254Z"
        fill="url(#ek-halftone)"
        opacity={0.45}
      />

      {/* ── the bomb ─────────────────────────────────────────── */}
      <path d={BOMB} fill={PALETTE.green} transform="translate(-2.4 1.8)" opacity={0.85} />
      <g filter="url(#ek-ink)">
        <path
          d={BOMB}
          fill="url(#ek-foil-dark)"
          stroke={PALETTE.ink}
          strokeWidth={3.6}
          strokeLinejoin="round"
        />
        {/* Screen the whole sphere before anything else lands on it.
            This is what stops the foil gradient reading as a render:
            the dot lattice sits over the smooth ramp and the eye reads
            "printed" rather than "lit". */}
        <path d={BOMB} fill="url(#ek-halftone-fine)" opacity={0.28} />
        <path d={BOMB_SHINE} fill={PALETTE.paper} opacity={0.7} />
        <path d={BOMB_GLINT} fill={PALETTE.paper} opacity={0.7} />
        <path d={BOMB_SHADE} fill={PALETTE.ink} opacity={0.44} />
        <path d={BOMB_SHADE} fill="url(#ek-halftone)" opacity={0.55} />
        {/* inner keyline, a hair inside the rim */}
        <path
          d="M121 137C155 137 176 162 176 192C176 222 155 247 121 247
             C87 247 66 222 66 192C66 162 87 137 121 137Z"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={1.2}
          opacity={0.3}
        />
      </g>

      {/* ── the ferrule, planted on the shoulder ─────────────── */}
      <g transform="translate(152 142) rotate(24)">
        <path d={FERRULE_BODY} fill={PALETTE.green} transform="translate(-2 1.4)" />
        <g filter="url(#ek-ink)">
          <path
            d={FERRULE_BODY}
            fill={PALETTE.green}
            stroke={PALETTE.ink}
            strokeWidth={3}
            strokeLinejoin="round"
          />
          <path
            d={FERRULE_BAND}
            fill={PALETTE.ink}
            stroke={PALETTE.ink}
            strokeWidth={2}
            strokeLinejoin="round"
          />
          <path
            d={FERRULE_LIP}
            fill={PALETTE.green}
            stroke={PALETTE.ink}
            strokeWidth={2.4}
            strokeLinejoin="round"
          />
        </g>
      </g>

      {/* ── the cut fuse ─────────────────────────────────────── */}
      <g fill="none" strokeLinecap="round" filter="url(#ek-ink)">
        <path d={FUSE_STUB} stroke={PALETTE.ink} strokeWidth={6} />
        {/* the frayed flat end of the cut */}
        <path d={FUSE_FRAY} stroke={PALETTE.ink} strokeWidth={2.6} />
        <path d={FUSE_LOOSE} stroke={PALETTE.ink} strokeWidth={5.4} opacity={0.9} />
        {/* one thread of smoke, going nowhere */}
        <path d={SMOKE} stroke={PALETTE.paper} strokeWidth={2.2} opacity={0.7} />
      </g>

      {/* ── shears, open around the cut ────────────────────────
          Moved in from translate(191 100) scale(0.88): at that size and
          station the finger ring pushed out to x≈231, i.e. past the
          224 safe edge and hard against the frame's face clip, and the
          blades were laid straight across the frayed fuse end — the one
          detail the whole card is about. Now they hang above and left
          of the cut, fully inside the safe area, grazing the stub. */}
      <g transform="translate(168 74) rotate(122) scale(0.72)">
        {/* green plate, off register */}
        <g fill={PALETTE.green} transform="translate(-2 1.4)" opacity={0.95}>
          <path d={BLADE_L} />
          <path d={BLADE_R} />
          <path
            d={RING_L}
            fill="none"
            stroke={PALETTE.green}
            strokeWidth={5.5}
            strokeLinecap="round"
          />
          <path
            d={RING_R}
            fill="none"
            stroke={PALETTE.green}
            strokeWidth={5.5}
            strokeLinecap="round"
          />
        </g>
        <g filter="url(#ek-ink)">
          {/* blades in paper so the steel separates from the blue field */}
          <path
            d={BLADE_L}
            fill={PALETTE.paper}
            stroke={PALETTE.ink}
            strokeWidth={3}
            strokeLinejoin="round"
          />
          <path
            d={BLADE_R}
            fill={PALETTE.paper}
            stroke={PALETTE.ink}
            strokeWidth={3}
            strokeLinejoin="round"
          />
          <g
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={5.5}
            strokeLinecap="round"
          >
            <path d={SHANK_L} />
            <path d={SHANK_R} />
            <path d={RING_L} />
            <path d={RING_R} />
          </g>
          <path d={SHEAR_PIVOT} fill={PALETTE.ink} />
        </g>
      </g>

      {/* Contact shadow. The cat is paper-white and the foil under it
          runs through a near-white specular band, so without a screened
          shadow the two masses fuse and the cat stops reading as an
          object sitting on top of a sphere. Offset down-right to match
          the light the specular crescent already implies. */}
      <g transform="translate(124 168) scale(0.9)" opacity={0.3}>
        <path d={BODY} fill="url(#ek-halftone)" transform="translate(8 10)" />
        <path d={TAIL} fill="url(#ek-halftone)" transform="translate(8 10)" />
      </g>

      {/* ── the cat, asleep on the thing that was about to kill it ── */}
      <g transform="translate(124 168) scale(0.9)">
        {/* green under-plate, off register */}
        <g transform="translate(-2.2 1.6)" opacity={0.9}>
          <path d={BODY} fill={PALETTE.green} />
          <path d={TAIL} fill={PALETTE.green} />
          <path d={HEAD} fill={PALETTE.green} transform="translate(-46 6)" />
        </g>

        <g filter="url(#ek-ink)">
          <path
            d={BODY}
            fill={PALETTE.paper}
            stroke={PALETTE.ink}
            strokeWidth={3.6}
            strokeLinejoin="round"
          />
          {/* paws first, then the tail laid across them */}
          <path
            d={PAW_A}
            fill={PALETTE.paper}
            stroke={PALETTE.ink}
            strokeWidth={2.8}
            strokeLinejoin="round"
          />
          <path
            d={PAW_B}
            fill={PALETTE.paper}
            stroke={PALETTE.ink}
            strokeWidth={2.8}
            strokeLinejoin="round"
          />
          <path
            d={PAW_TOES}
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={1.8}
            strokeLinecap="round"
            opacity={0.75}
          />
          {/* tail drawn over the body, so its keyline reads as a wrap
              rather than dissolving into the same white mass */}
          <path
            d={TAIL}
            fill={PALETTE.paper}
            stroke={PALETTE.ink}
            strokeWidth={3.2}
            strokeLinejoin="round"
          />
          {/* haunch, chest fold, then the screened underside */}
          <path
            d={HAUNCH}
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d={CHEST}
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={2.2}
            strokeLinecap="round"
            opacity={0.8}
          />
          <path d={BELLY_SHADE} fill="url(#ek-halftone-fine)" opacity={0.4} />
          <path d={BODY} fill="url(#ek-halftone-fine)" opacity={0.1} />

          <g transform="translate(-46 6)">
            <path
              d={HEAD}
              fill={PALETTE.paper}
              stroke={PALETTE.ink}
              strokeWidth={3.6}
              strokeLinejoin="round"
            />
            <path d={EAR_L} fill={PALETTE.green} stroke={PALETTE.ink} strokeWidth={1.6} />
            <path d={EAR_R} fill={PALETTE.green} stroke={PALETTE.ink} strokeWidth={1.6} />
            <path
              d={EYE_L}
              fill="none"
              stroke={PALETTE.ink}
              strokeWidth={3.2}
              strokeLinecap="round"
            />
            <path
              d={EYE_R_OPEN}
              fill={PALETTE.paper}
              stroke={PALETTE.ink}
              strokeWidth={2.6}
              strokeLinejoin="round"
            />
            <path d={PUPIL_R} fill={PALETTE.ink} />
            <path
              d={LID_R}
              fill="none"
              stroke={PALETTE.ink}
              strokeWidth={3.2}
              strokeLinecap="round"
            />
            <path
              d={NOSE}
              fill={PALETTE.green}
              stroke={PALETTE.ink}
              strokeWidth={1.6}
              strokeLinejoin="round"
            />
            <g
              fill="none"
              stroke={PALETTE.ink}
              strokeWidth={2.2}
              strokeLinecap="round"
            >
              <path d={MOUTH} />
              <path d={WHISKERS} strokeWidth={2} />
            </g>
          </g>
        </g>
      </g>

      {/* ── sleep marks ──────────────────────────────────────── */}
      <g
        fill="none"
        stroke={PALETTE.ink}
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#ek-ink)"
      >
        <path d={ZEE} transform="translate(52 104) rotate(-12) scale(0.6)" />
        <path d={ZEE} transform="translate(42 80) rotate(-20) scale(0.88)" />
        <path d={ZEE} transform="translate(58 52) rotate(-8) scale(1.2)" />
      </g>

      {/* ── catnip drifting past ─────────────────────────────── */}
      <Leaf x={22} y={184} r={-26} s={0.95} />
      <Leaf x={36} y={228} r={16} s={0.72} />
      <Leaf x={202} y={214} r={148} s={0.85} />
      <Leaf x={62} y={262} r={-8} s={0.62} />
    </g>
  );
}

/* Removed: a laser pointer and its beam in the bottom-left, firing a dot
   onto the bomb. It was a fourth narrative object on a card that already
   carries bomb + cut fuse + shears + cat, the beam cut straight across
   the bomb's silhouette, and it is motivated by nothing — the cat it was
   supposed to be teasing has its eyes shut. The bottom of the card is
   now held by the bomb's screened ground shadow and a fourth leaf. */
