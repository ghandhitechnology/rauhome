/* ─────────────────────────────────────────────────────────────
   SHUFFLE — a deck going around a cat that did not consent.

   Same skeleton as SKIP and ATTACK, because SHUFFLE is an action
   card and has to shelve next to them: flat saturated plate → ray
   burst → halftone bands → a solid-ink subject with an off-register
   red plate → paper-coloured graphic devices on top.

   At 60px the read is a blue card with a white ring of cards and a
   black scribble at the dead centre. Up close the ring resolves into
   ten cards at ten attitudes — face, back, and edge-on — and the
   scribble resolves into a cat mid-tumble, four legs out, mouth open.

   Plates: paper + blue + the red off-register fringe. Nothing else.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* Ray burst, generated the same way the rest of the deck generates it
   so the wedges are the same width and count as ATTACK's and SKIP's. */
const RAYS: readonly string[] = Array.from({ length: 20 }, (_, i) => {
  const a = (i / 20) * Math.PI * 2 + 0.14;
  const h = 0.06;
  const r = 400;
  const x1 = (Math.cos(a - h) * r).toFixed(1);
  const y1 = (Math.sin(a - h) * r).toFixed(1);
  const x2 = (Math.cos(a + h) * r).toFixed(1);
  const y2 = (Math.sin(a + h) * r).toFixed(1);
  return `M0 0L${x1} ${y1}L${x2} ${y2}Z`;
});

/* ── the cards ───────────────────────────────────────────────
   A card seen roughly face-on: very slightly trapezoidal, so each
   one has a little turn in it and the ring does not look like ten
   copies of one rectangle. */
const CARD_FACE =
  "M-15 -22C-15 -23.6 -13.9 -24.4 -12.4 -24.2L13.6 -21.4" +
  "C15.1 -21.2 15.9 -20.2 15.7 -18.7L12.6 20.9" +
  "C12.4 22.5 11.3 23.3 9.8 23.1L-13.4 20.5" +
  "C-14.9 20.3 -15.7 19.3 -15.5 17.8Z";

/* The same card most of the way over onto its edge — a thin lens, plus
   the sliver of its dark face still catching along one long side. A
   bare lens reads as a pill; the dark spine is what makes it a card. */
const CARD_EDGE =
  "M-4 -23C1 -24 4.6 -22 5.2 -18.6L5.8 18.4" +
  "C6 21.8 3 24 -1.8 23.2C-4.6 22.8 -6 21 -6 18.8" +
  "L-6.4 -18C-6.4 -20.4 -5.4 -22.2 -4 -23Z";
const CARD_EDGE_SPINE =
  "M-0.6 -21.8C2.4 -22.4 4.4 -20.8 4.8 -18.4L5.4 18.2" +
  "C5.7 20.8 4 22.2 1 21.9C-0.4 21.7 -1.2 20.8 -1.3 19.4Z";

/* Paw mark used as the card-back device, cut in paper. */
const PAW =
  "M-6.6 1.4C-3.2 -3 3.4 -2.8 6.4 1.6C8.6 4.8 6.4 8.8 1.8 9" +
  "C-0.6 9.1 -3 9 -5.2 8.6C-9.4 7.8 -9.6 4.4 -6.6 1.4Z" +
  "M-9.2 -5C-7.4 -6.8 -4.8 -5.8 -4.7 -3.2C-4.6 -0.9 -6 0.4 -7.7 -0.1" +
  "C-9.6 -0.6 -10.7 -3.2 -9.2 -5Z" +
  "M-1.6 -8.4C0.2 -10.2 2.8 -9.2 2.9 -6.6C3 -4.2 1.6 -2.9 -0.1 -3.4" +
  "C-2 -3.9 -3.1 -6.6 -1.6 -8.4Z" +
  "M6.4 -6.6C8.2 -8.2 10.5 -7.1 10.4 -4.6C10.4 -2.4 9 -1.2 7.4 -1.8" +
  "C5.6 -2.5 4.8 -5 6.4 -6.6Z";

type Kind = "face" | "back" | "edge";

/* Ten cards on a tangential orbit of radius 80 about (120,152). The
   angles are evenly spaced and the wobble is a fixed table, not a
   random one — the deck has to come off the press the same way twice. */
const FLYERS: readonly { x: number; y: number; r: number; s: number; k: Kind }[] = [
  { x: 106, y: 73, r: -16, s: 1.04, k: "face" },
  { x: 158, y: 81, r: 33, s: 0.94, k: "back" },
  { x: 193, y: 119, r: 61, s: 1.0, k: "edge" },
  { x: 198, y: 171, r: 110, s: 1.06, k: "face" },
  { x: 169, y: 215, r: 137, s: 0.92, k: "back" },
  { x: 120, y: 232, r: 186, s: 1.02, k: "edge" },
  { x: 71, y: 215, r: 213, s: 0.98, k: "face" },
  { x: 42, y: 171, r: 261, s: 1.05, k: "back" },
  { x: 47, y: 119, r: 289, s: 0.9, k: "edge" },
  { x: 82, y: 81, r: 338, s: 1.0, k: "face" },
];

function FlyingCard({ kind }: { kind: Kind }): ReactElement {
  if (kind === "edge") {
    return (
      <g>
        <path d={CARD_EDGE} fill={PALETTE.red} transform="translate(-2.6 1.6)" />
        <path d={CARD_EDGE} fill={PALETTE.paper} stroke={INK} strokeWidth={3} strokeLinejoin="round" />
        <path d={CARD_EDGE_SPINE} fill={INK} />
      </g>
    );
  }
  if (kind === "back") {
    return (
      <g>
        <path d={CARD_FACE} fill={PALETTE.red} transform="translate(-2.8 1.7)" />
        <path d={CARD_FACE} fill={INK} />
        {/* card back: paper keyline and a paper paw, so a dark card still
            reads as a card and not as a hole in the ring */}
        <path
          d="M-10.8 -17.8C-10.8 -19 -10 -19.6 -8.8 -19.4L10.2 -17.4
             C11.4 -17.2 12 -16.4 11.9 -15.2L9.4 15.4
             C9.3 16.6 8.5 17.2 7.3 17L-9.4 15.2
             C-10.6 15.1 -11.2 14.3 -11.1 13.1Z"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={1.6}
          opacity={0.85}
        />
        <path d={PAW} fill={PALETTE.paper} transform="translate(0 -1) scale(0.92)" />
      </g>
    );
  }
  return (
    <g>
      <path d={CARD_FACE} fill={PALETTE.red} transform="translate(-2.8 1.7)" />
      <path d={CARD_FACE} fill={PALETTE.paper} stroke={INK} strokeWidth={3.2} strokeLinejoin="round" />
      {/* face side: a title bar and two rules of "type", in ink so the
          white card has something dark inside it at thumbnail size */}
      <path
        d="M-9.6 9.2C-3.2 9.8 3.2 10.5 9.6 11.2L9 16.4C2.6 15.7 -3.8 15 -10.2 14.4Z"
        fill={INK}
      />
      <g fill={INK} opacity={0.55}>
        <path d="M-8.2 -12.4C-2.6 -11.8 3 -11.2 8.6 -10.6L8.4 -8.6C2.8 -9.2 -2.8 -9.8 -8.4 -10.4Z" />
        <path d="M-8.6 -7C-3.8 -6.5 1 -6 5.8 -5.5L5.6 -3.5C0.8 -4 -4 -4.5 -8.8 -5Z" />
      </g>
      <path d={PAW} fill={INK} transform="translate(0 -0.5) scale(0.8)" />
    </g>
  );
}

/* ── the cat, tumbling ───────────────────────────────────────
   Built as overlapping ink masses rather than one contour, which is
   safe here because every one of them is the same ink: the union is
   the silhouette. Limbs are tapered wedges ending in a round mitt,
   so they thin out the way a drawn leg does instead of being pipes.
   Local space: body centred on the origin, head above it. */

const BODY =
  "M-31 -4C-31 -23 -15 -33 4 -31C25 -29 35 -12 33 9" +
  "C31 30 14 42 -5 39C-24 36 -33 20 -31 -4Z";

/* Each leg: a wedge out of the body, then the mitt on the end. */
const LEGS: readonly string[] = [
  /* up-left */
  "M-24 -12C-40 -24 -56 -32 -70 -30C-74 -24 -72 -16 -66 -12" +
    "C-54 -10 -40 -4 -28 4Z",
  /* up-right */
  "M20 -20C34 -34 50 -44 62 -43C65 -37 63 -28 57 -24" +
    "C45 -22 32 -14 22 -4Z",
  /* down-left */
  "M-24 12C-38 24 -50 40 -50 52C-45 56 -37 55 -33 50" +
    "C-29 38 -22 27 -13 20Z",
  /* down-right */
  "M18 16C32 26 44 40 47 53C42 58 34 58 29 54" +
    "C22 43 13 33 3 27Z",
];

const MITTS: readonly (readonly [number, number, number])[] = [
  [-71, -30, 10],
  [61, -42, 9.4],
  [-49, 53, 9.6],
  [47, 54, 9.2],
];

/* Tail: two beziers out and two back, so the taper is real geometry
   rather than a stroke pretending to be one. */
const TAIL =
  "M26 20C50 26 68 42 70 62C71 73 64 80 56 78C50 76 48 69 51 62" +
  "C55 50 46 38 22 32Z";

const SKULL =
  "M-35 -47C-35 -68 -19 -80 0 -80C19 -80 35 -68 35 -47" +
  "C35 -28 19 -17 0 -17C-19 -17 -35 -28 -35 -47Z";

/* Ears: broad triangles set on the OUTER top corners of the skull and
   swept back by the airflow. Narrow ears set high read as a rabbit,
   which is the single failure mode of a drawn cat. */
const EAR_L = "M-34 -58C-42 -70 -45 -84 -40 -94C-28 -88 -17 -76 -12 -64Z";
const EAR_R = "M34 -58C42 -70 45 -84 40 -94C28 -88 17 -76 12 -64Z";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate ─────────────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={288} fill={PALETTE.blue} filter="url(#ek-grain)" />

      {/* ── ray burst, dead centre, because the whole card spins ── */}
      <g transform="translate(120 152)" fill={INK} opacity={0.13}>
        {RAYS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>

      {/* ── tone fields ───────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={52} fill="url(#ek-halftone-fine)" opacity={0.22} />
      <rect x={6} y={232} width={228} height={62} fill="url(#ek-halftone)" opacity={0.18} />

      {/* ── spin ribbons: tapered paper crescents, not strokes, so
             they thin out at the ends the way ink does ────────── */}
      <g fill={PALETTE.paper} opacity={0.3}>
        <path
          d="M18 168C10 100 58 40 130 30C154 27 178 30 198 39
             C190 45 183 50 177 56C160 49 142 47 126 49
             C68 57 30 106 34 166Z"
        />
        <path
          d="M222 132C230 200 182 262 110 272C86 275 62 272 42 263
             C50 257 57 252 63 246C80 253 98 255 114 253
             C172 245 210 196 206 136Z"
        />
      </g>

      {/* ── the deck in orbit ─────────────────────────────── */}
      <g filter="url(#ek-ink)">
        {FLYERS.map((f, i) => (
          <g key={i} transform={`translate(${f.x} ${f.y}) rotate(${f.r}) scale(${f.s})`}>
            <FlyingCard kind={f.k} />
          </g>
        ))}
      </g>

      {/* ── whip-lines off the leading corners, in paper so they
             carry on the blue ─────────────────────────────── */}
      <g
        fill="none"
        stroke={PALETTE.paper}
        strokeWidth={2.6}
        strokeLinecap="round"
        opacity={0.7}
        filter="url(#ek-ink)"
      >
        <path d="M92 46C86 37 82 27 80 17" />
        <path d="M186 78C195 72 205 68 216 66" />
        <path d="M212 200C220 205 226 212 230 220" />
        <path d="M104 258C97 266 92 275 89 285" />
        <path d="M28 148C19 146 10 145 1 146" />
        <path d="M50 88C43 81 37 73 33 64" />
      </g>

      {/* ── the cat ───────────────────────────────────────── */}
      {/* off-register red plate, laid down first and a hair low-left */}
      <g transform="translate(117.2 154.7) rotate(-14) scale(0.73)" fill={PALETTE.red}>
        <path d={SKULL} />
        <path d={EAR_L} />
        <path d={EAR_R} />
        <path d={TAIL} />
        {LEGS.map((d, i) => (
          <path key={i} d={d} />
        ))}
        {MITTS.map(([cx, cy, r], i) => (
          <circle key={i} cx={cx} cy={cy} r={r} />
        ))}
        <path d={BODY} />
      </g>

      <g transform="translate(120 153) rotate(-14) scale(0.73)" filter="url(#ek-ink)">
        <g fill={INK}>
          <path d={TAIL} />
          {LEGS.map((d, i) => (
            <path key={i} d={d} />
          ))}
          {MITTS.map(([cx, cy, r], i) => (
            <circle key={i} cx={cx} cy={cy} r={r} />
          ))}
          <path d={BODY} />
          <path d={EAR_L} />
          <path d={EAR_R} />
          <path d={SKULL} />
        </g>

        {/* toe splits, cut back out of each mitt in paper */}
        <g fill="none" stroke={PALETTE.paper} strokeWidth={2.4} strokeLinecap="round" opacity={0.75}>
          <path d="M-79 -33C-76 -30 -73 -28 -69 -27" />
          <path d="M-72 -39C-71 -35 -70 -31 -68 -28" />
          <path d="M69 -45C66 -42 63 -40 59 -39" />
          <path d="M62 -51C61 -47 60 -43 58 -40" />
          <path d="M-57 51C-54 54 -51 56 -47 57" />
          <path d="M-50 45C-49 49 -48 53 -46 56" />
          <path d="M55 52C52 55 49 57 45 58" />
          <path d="M48 46C47 50 46 54 44 57" />
        </g>

        {/* belly patch + flank bars, in paper, so the body is not one
            bald black mass at reading distance */}
        <path
          d="M-12 6C-4 0 10 2 16 10C20 17 16 28 7 31C-3 34 -14 28 -17 19C-19 13 -16 9 -12 6Z"
          fill={PALETTE.paper}
          opacity={0.28}
        />
        <g fill={PALETTE.paper} opacity={0.6}>
          <path d="M-20 -18C-14 -22 -7 -24 -1 -24C-7 -20 -14 -17 -19 -13Z" />
          <path d="M-27 -6C-21 -11 -14 -14 -7 -15C-14 -11 -20 -7 -25 -2Z" />
          <path d="M24 4C20 10 15 14 9 17C13 10 18 6 23 -1Z" />
          <path d="M25 17C21 22 16 26 10 28C15 21 19 17 24 12Z" />
        </g>

        {/* tail band */}
        <path d="M55 68C58 61 57 55 53 50C60 54 63 62 61 70Z" fill={PALETTE.paper} opacity={0.75} />

        {/* inner ears, in the card's own blue */}
        <path d="M-31 -61C-36 -70 -38 -80 -35 -87C-27 -82 -20 -74 -16 -66Z" fill={PALETTE.blue} />
        <path d="M31 -61C36 -70 38 -80 35 -87C27 -82 20 -74 16 -66Z" fill={PALETTE.blue} />

        {/* ── the face ──────────────────────────────────────
            Full panic: whites showing all the way round a shrunken
            pupil, brows hauled up, mouth open and yelling. */}
        <path
          d="M-27 -52C-27 -62 -21 -68 -13 -68C-5 -68 0 -62 0 -52
             C0 -43 -5 -37 -13 -37C-21 -37 -27 -43 -27 -52Z"
          fill={PALETTE.paper}
        />
        <path
          d="M0 -53C0 -63 5 -69 13 -69C21 -69 27 -63 27 -53
             C27 -44 21 -38 13 -38C5 -38 0 -44 0 -53Z"
          fill={PALETTE.paper}
        />
        <path
          d="M-15.6 -57C-11.4 -57 -8.4 -53.6 -8.4 -49.4C-8.4 -45.2 -11.4 -41.8 -15.6 -41.8
             C-19.6 -41.8 -22.6 -45.2 -22.6 -49.4C-22.6 -53.6 -19.6 -57 -15.6 -57Z"
          fill={INK}
        />
        <path
          d="M11.4 -58C15.6 -58 18.6 -54.6 18.6 -50.4C18.6 -46.2 15.6 -42.8 11.4 -42.8
             C7.4 -42.8 4.4 -46.2 4.4 -50.4C4.4 -54.6 7.4 -58 11.4 -58Z"
          fill={INK}
        />
        {/* catchlights, so the panic has something wet in it */}
        <g fill={PALETTE.paper}>
          <path d="M-19 -53C-17 -54.6 -14.6 -54 -14 -52C-14.8 -50.6 -17 -50.2 -18.6 -51Z" />
          <path d="M8 -54C10 -55.6 12.4 -55 13 -53C12.2 -51.6 10 -51.2 8.4 -52Z" />
        </g>
        {/* brows, wrenched up and apart */}
        <g fill="none" stroke={PALETTE.paper} strokeWidth={3} strokeLinecap="round">
          <path d="M-30 -69C-25 -74 -17 -76 -10 -74" />
          <path d="M10 -75C17 -77 25 -75 30 -70" />
        </g>

        {/* muzzle: a paper patch with an open mouth cut into it */}
        <path
          d="M-19 -30C-13 -36 13 -36 19 -30C21 -22 12 -14 0 -14C-12 -14 -21 -22 -19 -30Z"
          fill={PALETTE.paper}
        />
        <path d="M-5.6 -33L5.6 -33L0 -26Z" fill={INK} />
        <path
          d="M-11 -24C-5 -27 5 -27 11 -24C12 -15 6 -9 0 -9C-6 -9 -12 -15 -11 -24Z"
          fill={INK}
        />
        <path
          d="M-4.4 -14C-1.4 -16.4 2.6 -16 4.2 -13C5.6 -10.2 3.6 -7.4 0.2 -7.6
             C-3 -7.8 -5.4 -11 -4.4 -14Z"
          fill={PALETTE.red}
        />
        {/* teeth */}
        <path
          d="M-8.4 -23.4L-5 -19.6L-1.4 -23L2.2 -19.4L6 -22.8"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={2}
          strokeLinejoin="round"
        />
        {/* whiskers, cut in paper straight off the muzzle */}
        <g fill={PALETTE.paper} opacity={0.9}>
          <path d="M-19 -28C-29 -29 -38 -27 -46 -23C-38 -25 -29 -25 -19 -24Z" />
          <path d="M-19 -22C-28 -19 -36 -14 -42 -8C-35 -13 -27 -17 -19 -18Z" />
          <path d="M19 -28C29 -29 38 -27 46 -23C38 -25 29 -25 19 -24Z" />
          <path d="M19 -22C28 -19 36 -14 42 -8C35 -13 27 -17 19 -18Z" />
        </g>
      </g>

      {/* ── impact star, breaking the ring at the top left ── */}
      <g transform="translate(48 62) rotate(-8)">
        <path
          d="M0 -22L6 -8L20 -13L11 -1L24 6L9 7L12 21L1 12L-8 23L-9 9L-23 11L-13 0L-24 -9L-10 -8Z"
          fill={PALETTE.red}
          transform="translate(-2.8 1.7)"
        />
        <path
          d="M0 -22L6 -8L20 -13L11 -1L24 6L9 7L12 21L1 12L-8 23L-9 9L-23 11L-13 0L-24 -9L-10 -8Z"
          fill={PALETTE.paper}
          filter="url(#ek-ink)"
        />
      </g>
    </g>
  );
}
