/* ─────────────────────────────────────────────────────────────
   HAIRY POTATO CAT

   The premise is that this animal is a root vegetable that was left in
   the cupboard too long and has begun, quietly, to become a cat. It is
   not a round cat. It is a sack. Nothing about it is symmetrical: one
   ear is a sail and the other is a nub, one eye is blown wide and the
   other has not been told anything, and the sprouts on its skull are
   the only part of it with ambition.

   Two decisions worth knowing before you edit this file:

   1. The silhouette is generated, not typed. A lumpy potato drawn by
      hand as a bezier chain always comes out as a circle with dents;
      summing four sine harmonics on the radius and running a
      Catmull-Rom through the samples gives real, unrepeating lumps. It
      is still bezier output — see `blobPath` — and it is deterministic
      at module load, so the card never changes between mounts.
   2. Because that outline is parametric, the fur can hang off it
      properly: every flick starts on the outline and leaves along the
      normal, with length and curl driven by the same angle. That is
      what makes this thing hairy rather than fuzzy-edged.

   Plates: paper + gold, with red doing only the off-register fringe.
   The "brown" is not a brown — it is the gold plate with an ink
   halftone over it, the way a two-colour press would actually get
   there. Flat fills only, per SPEC.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* ── the lump ─────────────────────────────────────────────────
   Centre, radii, and the harmonic stack that deforms it. The 2θ term
   makes it sag to one side; 3θ and 5θ are the big lumps; 9θ is the
   knuckly bit that keeps the outline from ever looking sanded. */
const BX = 118;
const BY = 154;
const RX = 80;
const RY = 74;

function lumpiness(t: number): number {
  return (
    1 +
    0.052 * Math.sin(2 * t + 0.4) +
    0.082 * Math.sin(3 * t + 1.05) +
    0.048 * Math.sin(5 * t + 2.35) +
    0.026 * Math.sin(9 * t - 0.7)
  );
}

function onEdge(t: number, k = 1): [number, number] {
  const r = lumpiness(t) * k;
  return [BX + Math.cos(t) * RX * r, BY + Math.sin(t) * RY * r];
}

/** Closed cubic path through samples of `onEdge`, Catmull-Rom → bezier. */
function blobPath(samples: number): string {
  const pts: [number, number][] = Array.from({ length: samples }, (_, i) =>
    onEdge((i / samples) * Math.PI * 2),
  );
  const at = (i: number) => pts[((i % samples) + samples) % samples]!;
  const f = (n: number) => n.toFixed(1);
  let d = `M${f(at(0)[0])} ${f(at(0)[1])}`;
  for (let i = 0; i < samples; i += 1) {
    const [x0, y0] = at(i - 1);
    const [x1, y1] = at(i);
    const [x2, y2] = at(i + 1);
    const [x3, y3] = at(i + 2);
    d +=
      `C${f(x1 + (x2 - x0) / 6)} ${f(y1 + (y2 - y0) / 6)}` +
      ` ${f(x2 - (x3 - x1) / 6)} ${f(y2 - (y3 - y1) / 6)}` +
      ` ${f(x2)} ${f(y2)}`;
  }
  return `${d}Z`;
}

const BODY = blobPath(22);

/* ── the pelt ─────────────────────────────────────────────────
   Flicks leaving the outline along its normal. `sway` curls each one so
   the coat has a direction (down and to the left, as if it has been
   slept on), and the length wobbles on a different harmonic so no two
   neighbours match. */
function furFlick(t: number, base: number, out: number, k = 1): string {
  const [x, y] = onEdge(t, k * 0.985);
  const nx = Math.cos(t);
  const ny = Math.sin(t);
  const len = base + out * (0.5 + 0.5 * Math.sin(t * 7.3 + 1.1)) + 2.2 * Math.sin(t * 3.1);
  const sway = 0.42 + 0.3 * Math.sin(t * 4.7);
  const mx = x + nx * len * 0.55 - ny * len * sway * 0.5;
  const my = y + ny * len * 0.55 + nx * len * sway * 0.5;
  const ex = x + nx * len - ny * len * sway;
  const ey = y + ny * len + nx * len * sway;
  const f = (n: number) => n.toFixed(1);
  return `M${f(x)} ${f(y)}Q${f(mx)} ${f(my)} ${f(ex)} ${f(ey)}`;
}

const FUR_EDGE: readonly string[] = Array.from({ length: 38 }, (_, i) =>
  furFlick((i / 38) * Math.PI * 2 + 0.06, 7, 7),
);
/* One inner rank only. A second and third rank read as scratches on the
   belly rather than as coat, and at 60px they close the body up into a
   solid dark mass — which is what killed the first pass. */
const FUR_INNER: readonly string[] = Array.from({ length: 20 }, (_, i) =>
  furFlick((i / 20) * Math.PI * 2 + 0.31, 4.5, 4, 0.8),
);

/* ── radiating wedges behind the subject ─────────────────────── */
const RAYS: readonly string[] = Array.from({ length: 18 }, (_, i) => {
  const step = (Math.PI * 2) / 18;
  const r = 270;
  const p = (a: number) =>
    `${(120 + Math.cos(a) * r).toFixed(1)} ${(150 + Math.sin(a) * r).toFixed(1)}`;
  return `M120 150L${p(i * step - 0.115)}L${p(i * step + 0.115)}Z`;
});

/* ── potato eyes ──────────────────────────────────────────────
   The dimple-and-sprout kind. These only work on the *flanks*: the face
   occupies x 56→184, y 92→222 once the brows, whiskers and mouth are in,
   and a sprout landing anywhere inside that box reads as a tick on the
   cat rather than as an eye on the potato. So there are four, all on the
   narrow rim outside the face, each aimed outward along the lump's
   normal so the sprout grows away from the head. */
interface Dimple {
  x: number;
  y: number;
  s: number;
  a: number;
}
const DIMPLES: readonly Dimple[] = [
  { x: 183, y: 135, s: 0.8, a: 64 },
  { x: 188, y: 173, s: 0.72, a: 96 },
  { x: 59, y: 139, s: 0.62, a: -104 },
  { x: 61, y: 166, s: 0.55, a: -118 },
];

function DimpleMark({ x, y, s, a }: Dimple): ReactElement {
  return (
    <g transform={`translate(${x} ${y}) rotate(${a}) scale(${s})`}>
      {/* the pit — an almond, not a circle */}
      <path
        d="M-5.4 0.4C-5.6-3.6-2.8-6.6 0-6.6C2.9-6.6 5.5-3.4 5.4 0.4C5.3 3.8 2.8 6 0 6C-2.9 6-5.3 3.8-5.4 0.4Z"
        fill={INK}
        strokeWidth={0}
      />
      <path
        d="M-2.6-3.4C-1.2-4.6 0.8-4.6 2.2-3.6"
        fill="none"
        stroke={PALETTE.paper}
        strokeWidth={1.3}
        opacity={0.55}
      />
      {/* the sprout, with a bud that gave up halfway */}
      <path d="M0.6-5.6C2.4-9.4 6.2-11 9.4-13.6" fill="none" strokeWidth={1.9} />
      <path
        d="M9.6-13.8C12.4-16.6 15-15.2 14.2-12.4C13.6-10.2 11-9.8 9.6-11.4Z"
        fill={PALETTE.gold}
        strokeWidth={1.3}
      />
    </g>
  );
}

/* The ears. Hand-drawn, one sail and one nub, laid down *behind* the
   body fill so the weld is hidden without any clipping. */
const EAR_L = "M62 102C52 86 45 64 48 44C64 52 80 70 92 92Z";
const EAR_R = "M156 84C166 66 182 50 198 44C200 62 194 82 184 98Z";
/* The tail is a closed, tapered shape — fat at the root, cusped at the
   tip — and not a stroked centreline. Three reasons, all learned the
   hard way:
     · a tight curl stroked at 13px closes its own hole and prints as a
       floating gold hoop;
     · stroking the same open path again in ink draws a line *down the
       middle* of the tail rather than around it;
     · ek-ink's filter region is bbox ±8%, so a 16px stroke on a path
       this short overflows the region and gets guillotined into a
       rectangle. A filled outline's bbox is its own visible extent, so
       the region always fits.
   It roots at the lump's lower right — inside the silhouette, since the
   body fill is laid down after this — and clears it by ~28px at the
   widest, which is the whole point of moving it off the flank. */
const TAIL = `M164 216
C184 228 206 224 214 206
C218 196 216 188 208 182
C212 192 210 202 202 208
C192 215 178 212 168 204Z`;

/* Outer contours of the ears only. The closed EAR_* paths carry a base
   chord that runs *under* the body; stroking the closed path draws that
   chord straight across the shoulder. */
const EAR_L_LINE = "M62 102C52 86 45 64 48 44C64 52 80 70 92 92";
const EAR_R_LINE = "M156 84C166 66 182 50 198 44C200 62 194 82 184 98";

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── background plate ─────────────────────────────────── */}
      <rect
        x={8}
        y={8}
        width={224}
        height={282}
        fill={PALETTE.gold}
        opacity={0.22}
        filter="url(#ek-grain)"
      />
      <g clipPath="url(#ek-face-clip)">
        <g fill={PALETTE.gold} opacity={0.36}>
          {RAYS.map((d, i) => (
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
        {/* soil line — this thing was dug up, not born */}
        <path
          d="M8 248C34 240 58 246 82 242C108 238 126 246 152 242C176 238 206 246 232 240L232 292L8 292Z"
          fill={PALETTE.gold}
          opacity={0.45}
        />
        <path
          d="M8 248C34 240 58 246 82 242C108 238 126 246 152 242C176 238 206 246 232 240L232 292L8 292Z"
          fill="url(#ek-halftone)"
          opacity={0.2}
        />
        {/* clods */}
        <g fill={INK} opacity={0.4}>
          <path d="M28 258C33 253 41 254 43 259C44 264 36 266 31 264Z" />
          <path d="M196 254C202 250 209 252 210 257C210 262 202 263 198 260Z" />
          <path d="M62 268C67 264 74 266 74 270C74 274 66 275 62 272Z" />
        </g>
      </g>

      {/* cast shadow — a halftone smear, never a soft gradient */}
      <ellipse cx={116} cy={246} rx={82} ry={15} fill="url(#ek-halftone)" opacity={0.34} />

      {/* ── off-register plate ───────────────────────────────────
          The whole subject in red at the house offset — the same
          translate(-1.5 1) the frame's keyline and every sibling card
          uses, so the whole deck misregisters by the same amount.
          Everything after this is the ink plate landing on top of it
          slightly wrong, which is the entire trick.

          The plate is stroked as well as filled: a 1.5px shift alone
          disappears entirely under a 3.8px silhouette line, so the red
          is spread ~2px proud of its own edge — which is what trapping
          on a real press does, and is why the fringe reads at all. */}
      <g
        transform="translate(-1.5 1)"
        opacity={0.92}
        stroke={PALETTE.red}
        strokeWidth={4}
        strokeLinejoin="round"
      >
        <path d={EAR_L} fill={PALETTE.red} />
        <path d={EAR_R} fill={PALETTE.red} />
        <path d={BODY} fill={PALETTE.red} />
        <path d={TAIL} fill={PALETTE.red} />
      </g>

      {/* ── the potato ───────────────────────────────────────── */}
      {/* tail, drawn before the body so its root is buried by the fill */}
      <g filter="url(#ek-ink)">
        <path
          d={TAIL}
          fill={PALETTE.gold}
          stroke={INK}
          strokeWidth={3.4}
          strokeLinejoin="round"
        />
      </g>
      {/* feet, behind the body so only the toes show */}
      <path d="M84 220C74 232 77 248 93 248C108 248 114 238 108 222Z" fill={PALETTE.gold} />
      <path d="M136 222C130 236 139 250 154 248C167 246 169 234 161 220Z" fill={PALETTE.gold} />
      {/* ears, behind the body fill so the weld needs no clip. Fill only —
          their outline is stroked inside the ek-ink group with everything
          else, so it carries the same bleed as the rest of the linework. */}
      <path d={EAR_L} fill={PALETTE.gold} />
      <path d={EAR_R} fill={PALETTE.gold} />

      <path d={BODY} fill={PALETTE.gold} />
      {/* the tone: halftone over gold is how a two-colour press makes brown —
          halftone alone, though, with no flat ink wash. The wash plus the fur
          rim closed the whole body into a dark mass at 60px, which put
          this card two values below every sibling. */}
      <path d={BODY} fill="url(#ek-halftone)" opacity={0.26} />
      {/* underside, denser */}
      <path
        d="M40 160C48 210 82 238 124 236C160 234 190 210 198 176C204 216 164 250 118 248C70 246 34 212 40 160Z"
        fill="url(#ek-halftone)"
        opacity={0.4}
      />

      {/* ── linework ─────────────────────────────────────────── */}
      <g
        filter="url(#ek-ink)"
        fill="none"
        stroke={INK}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* the pelt, outermost first so the silhouette closes over it */}
        <g strokeWidth={2}>
          {FUR_EDGE.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        {/* the tail is part of the same animal — it gets flicks too */}
        <g strokeWidth={1.8}>
          <path d="M186 214C188 221 192 226 198 228" />
          <path d="M199 208C204 213 209 214 214 213" />
          <path d="M207 194C212 196 216 195 219 192" />
        </g>
        <path d={EAR_L_LINE} strokeWidth={3.4} />
        <path d={EAR_R_LINE} strokeWidth={3.4} />
        <path d={BODY} strokeWidth={3.8} />
        <g strokeWidth={1.8} opacity={0.85}>
          {FUR_INNER.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>

        {/* toes */}
        <path d="M84 220C74 232 77 248 93 248C108 248 114 238 108 222" strokeWidth={3.2} />
        <path d="M136 222C130 236 139 250 154 248C167 246 169 234 161 220" strokeWidth={3.2} />
        <path
          d="M85 242C88 237 92 237 95 241M97 244C100 239 105 239 108 243M141 243C144 238 148 238 151 242M153 243C156 238 160 239 162 242"
          strokeWidth={1.8}
        />

        {/* inner ear folds — the nub is pinched, the sail is a windsock */}
        <path d="M60 96C58 82 57 68 58 58" strokeWidth={2.2} />
        <path d="M172 92C176 76 184 60 192 52" strokeWidth={2.2} />
        <path d="M64 64C70 72 76 80 82 86" strokeWidth={1.6} opacity={0.7} />
        <path d="M186 58C182 70 178 82 174 90" strokeWidth={1.6} opacity={0.7} />
        {/* ear tufts, because of course */}
        <g strokeWidth={1.8}>
          <path d="M54 74C48 71 45 66 46 60" />
          <path d="M56 88C50 87 45 83 44 77" />
          <path d="M191 62C197 58 200 52 199 46" />
          <path d="M186 78C193 76 197 71 197 65" />
        </g>

        {/* ── skull sprouts ─────────────────────────────────────
            The only ambitious part of the animal. */}
        <g strokeWidth={2.6}>
          <path d="M100 88C93 68 97 52 110 42" />
          <path d="M118 82C123 60 136 50 143 36" />
          <path d="M133 86C139 72 139 58 132 46" />
        </g>
        <g strokeWidth={1.5} fill={PALETTE.gold}>
          <path d="M110.4 42.2C113 34 122 33 123 40C124 47 115 49 110.4 44.6Z" />
          <path d="M143.2 36.4C142 27 150 22 153 28C156 34 149 40 144.6 38Z" />
          <path d="M131.8 46.2C125 41 128 32 133 33C139 34 138.5 43 134 47.4Z" />
        </g>

        {/* ── the face ──────────────────────────────────────────
            The big eye is blown wide; the small eye has not been told
            anything yet. Both pupils are aimed slightly wrong. */}
        <ellipse cx={92} cy={146} rx={25} ry={26} fill={PALETTE.paper} strokeWidth={3.2} />
        <ellipse cx={155} cy={138} rx={13} ry={14.5} fill={PALETTE.paper} strokeWidth={3} />
        <path
          d="M96 152.5C89.4 152.5 84 147.2 84 140.6C84 134 89.4 128.6 96 128.6C102.6 128.6 108 134 108 140.6C108 147.2 102.6 152.5 96 152.5Z"
          fill={INK}
          strokeWidth={0}
        />
        <path
          d="M158.6 142.6C155.6 142.6 153.2 140.2 153.2 137.2C153.2 134.2 155.6 131.8 158.6 131.8C161.6 131.8 164 134.2 164 137.2C164 140.2 161.6 142.6 158.6 142.6Z"
          fill={INK}
          strokeWidth={0}
        />
        <circle cx={90} cy={135} r={3.6} fill={PALETTE.paper} strokeWidth={0} />
        <circle cx={156.4} cy={135} r={1.5} fill={PALETTE.paper} strokeWidth={0} />
        {/* bags. It has not slept. */}
        <path d="M74 166C82 172 96 173 106 168" strokeWidth={1.7} opacity={0.75} />
        <path d="M147 152C152 156 161 156 165 153" strokeWidth={1.6} opacity={0.7} />

        {/* brows: tufts, not lines — one flat and furious, one at the ceiling */}
        <g strokeWidth={3.6}>
          <path d="M64 118C76 110 92 109 106 114" />
          <path d="M140 108C148 96 164 94 174 102" />
        </g>
        <g strokeWidth={2}>
          <path d="M70 116C67 110 68 104 72 100" />
          <path d="M83 111C81 105 83 99 88 96" />
          <path d="M97 111C96 105 99 100 104 98" />
          <path d="M148 104C147 97 150 92 155 89" />
          <path d="M161 99C161 92 165 88 170 86" />
        </g>

        {/* nose: a lump, off centre, red plate showing beneath */}
        <path
          d="M110 170C117 165 130 165 137 171C139 179 132 187 123 187C114 187 108 179 110 170Z"
          fill={PALETTE.red}
          strokeWidth={0}
          transform="translate(-1.5 1)"
        />
        <path
          d="M110 170C117 165 130 165 137 171C139 179 132 187 123 187C114 187 108 179 110 170Z"
          fill={INK}
          strokeWidth={2.4}
        />
        <path d="M116 172C119 170 124 170 127 172" stroke={PALETTE.paper} strokeWidth={1.6} opacity={0.5} />

        {/* mouth: open, crooked, one tooth doing all the work */}
        <path d="M123 187L122 194" strokeWidth={2.4} />
        <path
          d="M94 190C104 187 115 190 122 195C130 189 143 186 152 191C149 213 133 222 121 221C108 220 96 209 94 190Z"
          fill={INK}
          strokeWidth={2.8}
        />
        <path
          d="M110 208C114 202 128 202 134 207C132 216 126 220 120 220C114 219 110 214 110 208Z"
          fill={PALETTE.red}
          strokeWidth={0}
        />
        <path d="M110 191L114 200L119 191Z" fill={PALETTE.paper} strokeWidth={1.2} />
        <path d="M143 192L146 199L149 191Z" fill={PALETTE.paper} strokeWidth={1.2} />

        {/* whiskers — thin, drooping, defeated */}
        <g strokeWidth={2}>
          <path d="M104 180C90 183 74 182 60 176" />
          <path d="M104 187C92 194 76 197 62 194" />
          <path d="M104 194C94 204 80 211 68 211" />
          <path d="M146 180C158 181 172 178 182 171" />
          <path d="M146 187C158 192 172 193 182 188" />
          <path d="M146 194C156 203 168 208 178 205" />
        </g>

        {/* ── potato eyes over the body ─────────────────────── */}
        {DIMPLES.map((d, i) => (
          <DimpleMark key={i} {...d} />
        ))}
      </g>
    </g>
  );
}
