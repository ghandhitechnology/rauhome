/* ─────────────────────────────────────────────────────────────
   SKIP — blue plate, green plate.

   Same skeleton as ATTACK at a third of the volume: flat plate →
   ray burst → halftone → ink subject with an off-register accent
   plate → one paper-coloured graphic device.

   ATTACK's device is three rips that go straight through the
   problem. SKIP's is a single swerve on the floor that goes around
   it. The cat is in full profile mid-stride, eyes shut, tail up,
   whistling — walking past a lit bomb it has decided is not its
   bomb.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

const RAYS: readonly string[] = Array.from({ length: 20 }, (_, i) => {
  const a = (i / 20) * Math.PI * 2 - 0.21;
  const h = 0.062;
  const r = 400;
  const x1 = (Math.cos(a - h) * r).toFixed(1);
  const y1 = (Math.sin(a - h) * r).toFixed(1);
  const x2 = (Math.cos(a + h) * r).toFixed(1);
  const y2 = (Math.sin(a + h) * r).toFixed(1);
  return `M0 0L${x1} ${y1}L${x2} ${y2}Z`;
});

/* ── the cat, in profile, facing right ───────────────────────
   One closed contour: rump → arched back → shoulder → skull → two
   ears → muzzle → throat → near foreleg → belly → near hind leg →
   back to the rump. Kept as a single silhouette because a walking
   cat has to survive the 60px black-shape test, and a cat welded
   together out of separate limbs never does. Local baseline y=98. */
const BODY =
  "M14 34C22 18 44 10 70 12C92 14 106 20 116 28" +
  "C118 16 124 6 132 2C127 -10 129 -22 136 -27C141 -21 143 -13 144 -6" +
  "C149 -10 155 -12 159 -10C159 -19 164 -26 170 -28C173 -20 173 -10 171 -3" +
  "C179 3 183 13 181 23C181 28 177 32 170 33C166 36 158 38 150 37" +
  "C142 42 134 46 126 46C124 58 122 72 122 88C122 96 116 100 110 98" +
  "C106 94 108 86 108 76C106 64 104 54 100 48" +
  "C90 54 76 58 60 58C58 70 60 84 56 94C52 100 44 100 40 96" +
  "C38 88 42 78 42 68C40 60 36 52 30 48C22 48 14 42 14 34Z";

/* The far pair of legs, a step out of phase so the stride reads. The
   foreleg used to start at x=104 — one unit clear of the near foreleg —
   so the two merged into a single black stump and the card had a
   two-legged cat on it. Pushed back 8 units and slimmed. */
const FAR_LEGS = [
  "M96 44C93 58 91 72 91 88C91 95 85 99 80 96C77 92 79 84 79 74C77 62 75 54 73 46Z",
  "M40 46C38 58 40 72 36 84C33 90 26 90 23 86C21 78 25 70 25 60C24 54 22 50 20 46Z",
];

/* Paper hairlines down the *near* legs' back edges. Four ink legs in
   front of an ink body is one silhouette; these two lines are the only
   thing that makes it a walk. */
const LEG_SPLIT = "M105 52C108 64 109 76 109 88M56 60C57 72 56 84 54 92";
/* Two toe ticks per planted foot, so the legs end in feet and not in
   blunt round stumps. */
const TOES =
  "M112 99L112 93M118 98L118 92" +
  "M46 99L46 93M52 98L52 92" +
  "M83 97L83 91M89 96L89 90" +
  "M26 88L26 82M31 87L31 81";

/* Tail: a tapered curl, thick at the base, whipping up over the
   rump. Two beziers out and two back, so the taper is real geometry
   rather than a stroke that pretends. */
const TAIL =
  "M14 36C-6 34 -18 18 -14 -2C-11 -20 6 -30 20 -26" +
  "C8 -24 -2 -16 -4 -2C-6 12 0 26 16 28Z";

/* The swerve: a path painted on the floor that bellies up and out
   around the bomb, then runs flat off the right edge.

   It used to start at x=6, i.e. underneath the bomb, so the bomb — ink,
   with a paper keyline — sat inside a white ribbon and read as a hole
   punched in it. The ribbon now begins to the *right* of the bomb and
   tapers to a point there. Same joke, and it is finally legible: the
   path does not exist until after the thing it is avoiding. */
const SWERVE =
  "M86 280C92 258 106 244 130 239C156 233 176 234 192 239L189 252" +
  "C172 248 152 246 132 250C114 254 100 262 92 282Z";

const ARROWHEAD =
  "M0 -17C10 -10 21 -4 31 1C21 6 10 12 0 19C4 11 5 5 5 1C5 -4 4 -10 0 -17Z";

/* Eighth note — two counters, so it needs evenodd. */
const NOTE =
  "M0 0C0 -4 4 -7 8 -7C11 -7 13 -5 13 -2C13 2 9 5 5 5C2 5 0 3 0 0Z" +
  "M11 -6L11 -34C15 -30 21 -29 23 -24C24 -20 23 -17 20 -14C21 -19 18 -23 13 -26L13 -6Z";

const PRINT =
  "M-10 4C-7 -3 7 -3 10 4C12 9 8 14 0 14C-8 14 -12 9 -10 4Z" +
  "M-11 -6C-8 -6 -6 -3 -7 0C-8 3 -11 4 -13 2C-15 0 -14 -6 -11 -6Z" +
  "M-3 -11C0 -11 2 -8 1 -4C0 -1 -3 0 -5 -2C-7 -5 -6 -11 -3 -11Z" +
  "M6 -10C9 -9 10 -5 8 -2C6 0 3 0 2 -3C1 -7 3 -11 6 -10Z" +
  "M13 -4C15 -3 16 0 14 2C12 4 9 3 9 1C8 -2 11 -5 13 -4Z";

/* Cat sits at scale 0.95 with its local baseline (y=98) landing on
   the floor rule at y=234. */
const CAT_AT = "translate(26 141) scale(0.95)";
const CAT_PLATE_AT = "translate(23.4 142.6) scale(0.95)";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate ─────────────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={288} fill={PALETTE.blue} filter="url(#ek-grain)" />

      {/* ── ray burst thrown from up-right, so the cat is walking
             out of the light rather than posing in it ────────── */}
      <g transform="translate(124 152)" fill={INK} opacity={0.12}>
        {RAYS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>

      {/* ── tone fields ───────────────────────────────────── */}
      <rect x={6} y={228} width={228} height={66} fill="url(#ek-halftone)" opacity={0.2} />
      <rect x={6} y={6} width={228} height={48} fill="url(#ek-halftone-fine)" opacity={0.24} />
      {/* the upper-left quarter had nothing in it but three ray edges */}
      <rect x={6} y={6} width={92} height={158} fill="url(#ek-halftone-fine)" opacity={0.14} />

      {/* ── floor ─────────────────────────────────────────── */}
      <path
        d="M12 237C56 231 106 230 154 233C182 235 208 238 228 242"
        fill="none"
        stroke={PALETTE.green}
        strokeWidth={3}
        strokeLinecap="round"
        opacity={0.9}
      />
      <path
        d="M14 234C58 228 108 227 156 230C184 232 210 235 230 239"
        fill="none"
        stroke={INK}
        strokeWidth={2.4}
        strokeLinecap="round"
        filter="url(#ek-ink)"
      />

      {/* ── the swerve ────────────────────────────────────── */}
      <path d={SWERVE} fill={PALETTE.green} transform="translate(-2.8 1.7)" />
      <g filter="url(#ek-ink)">
        <path d={SWERVE} fill={PALETTE.paper} />
      </g>
      <g transform="translate(191 244) rotate(11) scale(0.78)">
        <path d={ARROWHEAD} fill={PALETTE.green} transform="translate(-3.4 2.1)" />
        <g filter="url(#ek-ink)">
          <path d={ARROWHEAD} fill={PALETTE.paper} />
        </g>
      </g>
      {/* prints already left along the swerve */}
      <g fill={INK} opacity={0.32}>
        {[
          { x: 100, y: 256, s: 0.5, r: 8 },
          { x: 134, y: 250, s: 0.42, r: -6 },
          { x: 162, y: 248, s: 0.34, r: 10 },
        ].map((p, i) => (
          <path
            key={i}
            d={PRINT}
            transform={`translate(${p.x} ${p.y}) rotate(${p.r}) scale(${p.s})`}
          />
        ))}
      </g>

      {/* ── the only motion cue a cat this unbothered will give.
             Was a paper puff at (22,220) sitting a clear 20px above the
             floor with nothing under it — it read as a cloud in the sky.
             Two ticks off the rump instead. ───────────────────── */}
      <g
        fill="none"
        stroke={PALETTE.paper}
        strokeWidth={2.8}
        strokeLinecap="round"
        opacity={0.4}
      >
        <path d="M16 158C10 172 10 186 15 198" />
        <path d="M29 152C24 166 24 180 28 191" />
      </g>

      {/* ── the cat ───────────────────────────────────────── */}
      <g transform={CAT_PLATE_AT} fill={PALETTE.green} opacity={0.95}>
        <path d={TAIL} />
        <path d={BODY} />
      </g>

      <g transform={CAT_AT} filter="url(#ek-ink)">
        {FAR_LEGS.map((d, i) => (
          <path key={i} d={d} fill={INK} />
        ))}
        <path d={TAIL} fill={INK} />
        <path d={BODY} fill={INK} />

        {/* the walk */}
        <path
          d={LEG_SPLIT}
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={1.9}
          strokeLinecap="round"
          opacity={0.42}
        />
        <path
          d={TOES}
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={1.7}
          strokeLinecap="round"
          opacity={0.6}
        />

        {/* banded tail tip */}
        <path d="M-13 -8C-10 -20 0 -27 12 -25C4 -22 -4 -17 -8 -8Z" fill={PALETTE.paper} opacity={0.85} />

        {/* back stripes — short tapered slivers so they read as fur,
            not ribs */}
        <path d="M52 14C56 20 57 26 55 32C52 26 50 20 48 15Z" fill={PALETTE.paper} opacity={0.5} />
        <path d="M70 12C74 19 75 25 73 32C70 25 68 19 66 13Z" fill={PALETTE.paper} opacity={0.5} />
        <path d="M88 14C92 21 93 28 91 34C88 27 86 21 84 15Z" fill={PALETTE.paper} opacity={0.5} />

        {/* inner ears */}
        <path d="M134 -21C137 -15 139 -10 140 -6C136 -10 134 -15 133 -20Z" fill={PALETTE.green} />
        <path d="M167 -22C166 -16 165 -11 164 -7C167 -12 168 -17 169 -21Z" fill={PALETTE.green} />

        {/* the face. The first cut stacked a 3.4px shut-eye arc and a
            2.2px brow arc 9 units apart and both bowing the same way:
            at card size that is a pair of spectacles, and at 60px it is
            a smear. One heavy shut eye, arcing *up* — the contented
            curve — with a flick down at the outer corner; the brow moved
            well clear and shortened so it cannot pair off with it. */}
        <path
          d="M145 8C151 -2 162 -2 168 7"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={4.2}
          strokeLinecap="round"
        />
        <path
          d="M167 6C170 8 171 11 171 14"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={3}
          strokeLinecap="round"
        />
        {/* No brow. The first cut had one 9 units above the eye and the
            second had one 18 above; both bow the same way as the eye and
            both are paper on ink, so either way the card carries two
            white arcs stacked on a black head and the viewer reads
            spectacles. One eye, drawn heavy, is the whole face. */}
        {/* muzzle: nose, cheek line, and a whistle big enough to be a
            whistle. At r≈3 it was a speck lost inside the whiskers. */}
        <path
          d="M179 13C182 13 184 15 183 18C182 21 179 21 177 19C175 17 176 13 179 13Z"
          fill={PALETTE.green}
        />
        <path
          d="M179 20C178 25 175 28 172 28"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={2.2}
          strokeLinecap="round"
          opacity={0.8}
        />
        {/* Solid, not an annulus. A paper ring with an ink centre on the
            muzzle is a white circle with a black pupil in it, and it read
            as a second — open — eye sitting below the shut one. The two
            notes overhead are what say "whistling"; this only has to be a
            pursed hole. */}
        <path
          d="M173 22C177 22 179.5 24.5 179.5 27.5C179.5 30.8 177 33 173 33C169 33 167 30.8 167 27.5C167 24.5 169 22 173 22Z"
          fill={PALETTE.paper}
        />
        {/* whiskers — pushed off the muzzle so they clear the whistle */}
        <path d="M174 16C183 17 192 21 200 27C191 24 182 21 173 20Z" fill={PALETTE.paper} opacity={0.9} />
        <path d="M176 34C184 38 191 44 196 51C189 45 182 40 174 37Z" fill={PALETTE.paper} opacity={0.9} />
      </g>

      {/* ── the problem: on the floor, lit, and being walked straight
             past. It used to sit at (40,260): an ink sphere on the ink
             swerve-shadow with an ink fuse, half of it under the face
             clip, and its spark 45 units away from the fuse it was
             supposed to be on. Moved fully inboard onto the floor line,
             given a paper keyline so it separates from everything ink
             around it, and the fuse now runs up under the cat's belly
             with the spark actually on its end. ─────────────────── */}
      <g transform="translate(50 252)">
        <g filter="url(#ek-ink)">
          <path
            d="M-2 -12C11 -12 21 -4 21 8C21 20 11 29 -2 29C-15 29 -25 20 -25 8C-25 -4 -15 -12 -2 -12Z"
            fill={INK}
          />
          <path
            d="M5 -12C3 -20 -3 -26 -11 -28"
            fill="none"
            stroke={PALETTE.paper}
            strokeWidth={4.4}
            strokeLinecap="round"
          />
          <path
            d="M5 -12C3 -20 -3 -26 -11 -28"
            fill="none"
            stroke={INK}
            strokeWidth={1.8}
            strokeLinecap="round"
            opacity={0.55}
          />
          <path
            d="M-13 1C-10 -5 -5 -8 0 -8"
            fill="none"
            stroke={PALETTE.paper}
            strokeWidth={2.6}
            strokeLinecap="round"
            opacity={0.7}
          />
        </g>
        <path
          d="M-17 -40L-13.5 -31.5L-5 -28L-13.5 -24.5L-17 -16L-20.5 -24.5L-29 -28L-20.5 -31.5Z"
          fill={PALETTE.paper}
          transform="translate(-2.8 1.7)"
        />
        <path
          d="M-17 -40L-13.5 -31.5L-5 -28L-13.5 -24.5L-17 -16L-20.5 -24.5L-29 -28L-20.5 -31.5Z"
          fill={PALETTE.green}
          filter="url(#ek-ink)"
        />
      </g>

      {/* ── whistled notes, green plate off register ──────── */}
      <g transform="translate(196 88) rotate(-8)">
        <path d={NOTE} fill={PALETTE.green} transform="translate(-2.6 1.6)" fillRule="evenodd" />
        <path d={NOTE} fill={PALETTE.paper} filter="url(#ek-ink)" fillRule="evenodd" />
      </g>
      <g transform="translate(212 52) rotate(11) scale(0.72)">
        <path d={NOTE} fill={PALETTE.green} transform="translate(-3.4 2.1)" fillRule="evenodd" />
        <path d={NOTE} fill={PALETTE.paper} filter="url(#ek-ink)" fillRule="evenodd" />
      </g>
    </g>
  );
}
