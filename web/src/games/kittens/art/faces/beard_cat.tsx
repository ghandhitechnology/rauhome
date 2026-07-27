/* ─────────────────────────────────────────────────────────────
   BEARD CAT

   Drawn as a barbershop sign rather than as a portrait: a pinched
   cartouche with a gold double keyline and a bead ring, a sunburst
   behind it, and a subject posed dead centre with the composure of a
   gentleman who has never once doubted his own moustache.

   The joke is scale. The beard is a weather system and the cat is
   merely the thing it is attached to. Four rules keep it from reading
   as a navy bib, which is the failure mode this card lives next to:

   1. The head is *large*. A small dignified head is a nice idea and an
      unreadable card — at 60px it becomes a smudge on a blob, and the
      whole thing silhouettes as a lightbulb. It takes a third of the
      card's width so the face still lands at deck size.
   2. The hem is cut into six pointed lobes and every major groove runs
      from the chin to one of those points. Hair explains its own
      outline; if the grooves and the hem disagree, the grooves read as
      corduroy and the hem reads as a jellyfish.
   3. Groove weights alternate. Thirteen strokes at one width on an even
      pitch is a barcode no matter how well they are placed.
   4. The moustache is drawn last, filled paper, and waxed out past the
      width of the head — a blue moustache on a blue beard is invisible,
      and a rounded tip reads as a bone.

   Plates: paper + blue + gold. That is the SPEC's two-accent budget in
   full, so the off-register plate is gold rather than the house red —
   a warm fringe down the left of a navy beard, which is what a two-hit
   press actually gives you. The plate is stroked as well as filled,
   because a 1.5px shift alone vanishes under a 3.6px silhouette line.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

const CX = 120;
/** The house misregistration, shared with the frame and every sibling. */
const OFFSET = "translate(-1.5 1)";

/* The cartouche: a pinched oval, wider at the shoulders than at the
   waist. Clear of the frame's corner pips at (28,28) and (212,268) —
   it spans x 42→198, y 34→262. */
const CARTOUCHE = `M120 34
C162 34 198 58 198 96
C198 118 190 132 190 146
C190 162 198 184 198 210
C198 244 162 262 120 262
C78 262 42 244 42 210
C42 184 50 162 50 146
C50 132 42 118 42 96
C42 58 78 34 120 34Z`;

/* ── the head ─────────────────────────────────────────────────
   An egg, tall rather than round, drawn big enough to survive the
   deck's smallest render. The ears are separate paths laid in behind
   it so the weld needs no clipping. */
const HEAD = `M120 44
C142 44 160 60 162 82
C164 102 158 122 142 132
C128 140 112 140 98 132
C82 122 76 102 78 82
C80 60 98 44 120 44Z`;

const EAR_L = "M92 60C85 46 82 32 85 18C100 24 112 38 118 52Z";
const EAR_R = "M148 60C155 46 158 32 155 18C140 24 128 38 122 52Z";
const EAR_L_IN = "M95 52C91 43 90 34 91 27C99 33 105 41 109 49Z";
const EAR_R_IN = "M145 52C149 43 150 34 149 27C141 33 135 41 131 49Z";
/* Outer contours only — stroking the closed ear would draw its base
   chord straight across the skull. */
const EAR_L_LINE = "M92 60C85 46 82 32 85 18C100 24 112 38 118 52";
const EAR_R_LINE = "M148 60C155 46 158 32 155 18C140 24 128 38 122 52";

/* ── the beard ────────────────────────────────────────────────
   Cheeks → outer sweep → six pointed lobes around the hem → back up
   the far side → closed under the chin. Written out longhand in both
   directions rather than mirrored with a transform, so the two sides
   can disagree with each other by a pixel or two.

   Each lobe is two quadratics meeting at a cusp: curve out to the
   point, curve back in to the valley. A cusp is what makes it hair;
   a smooth join is what makes it cloth. */
const BEARD = `M80 96
C62 116 46 146 46 176
Q39 189 39 198
Q46 203 60 204
Q59 220 63 230
Q71 233 84 230
Q91 245 99 252
Q109 251 120 242
Q131 251 141 252
Q149 245 156 230
Q169 233 177 230
Q181 220 180 204
Q194 203 201 198
Q201 189 194 176
C194 146 178 116 160 96
C158 110 146 124 120 126
C94 124 82 110 80 96Z`;

/* The moustache: a handlebar hung off the muzzle at the centre and
   swept up and out to a waxed point at each end, past the width of the
   head and over the beard's cheeks. The tips must be cusps — where the
   tangent reverses on itself — because a rounded end makes the whole
   thing read as a bone. */
const MOUSTACHE = `M120 124
C113 121 106 123 100 128
C92 134 82 137 75 133
C70 130 67 121 68 108
C60 118 58 132 64 139
C72 146 84 146 96 141
C104 137 112 134 120 131
C128 134 136 137 144 141
C156 146 168 146 176 139
C182 132 180 118 172 108
C173 121 170 130 165 133
C158 137 148 134 140 128
C134 123 127 121 120 124Z`;

/* ── beard engraving ──────────────────────────────────────────
   Majors run from the chin to a lobe *point*; minors run to a lobe
   *valley* and stop short. The alternating weights are the whole
   reason this reads as a mass of hair rather than a fence. */
const GROOVE_MAJOR: readonly [string, number][] = [
  ["M86 104C70 122 52 152 44 190", 2.4],
  ["M92 116C82 148 70 194 65 226", 1.8],
  ["M106 124C100 160 98 210 100 246", 2.3],
  ["M120 132C118 168 118 208 120 238", 1.6],
  ["M134 124C140 160 142 210 140 246", 2.4],
  ["M148 116C158 148 170 194 175 226", 1.8],
  ["M154 104C170 122 188 152 196 190", 2.3],
];
/* Minors stop short of the hem. If every stroke runs the full drop the
   mass turns into corduroy no matter how well the ends are aimed. */
const GROOVE_MINOR: readonly [string, number][] = [
  ["M90 110C78 132 68 164 64 190", 1.5],
  ["M99 120C93 150 88 186 86 210", 1.9],
  ["M141 120C147 150 152 186 154 210", 1.4],
  ["M150 110C162 132 172 164 176 190", 1.8],
];

/* Two shallow waves crossing the fall of the grooves. Without something
   running the other way, thirteen strokes down a flat blue field is a
   barcode however carefully they are aimed. */
const WAVE: readonly string[] = [
  "M84 174C98 181 142 181 156 174",
  "M92 212C106 220 134 220 148 212",
];

/* Cheek flicks where the beard meets the face — the seam has to be hair
   rather than a hemline, or the mass goes back to reading as a garment. */
const CHEEK: readonly string[] = [
  "M84 100C89 103 92 108 93 114",
  "M92 112C98 115 102 120 104 126",
  "M102 122C108 125 113 128 118 129",
  "M156 100C151 103 148 108 147 114",
  "M148 112C142 115 138 120 136 126",
  "M138 122C132 125 127 128 122 129",
];

/* Bead ring on the cartouche. Deterministic, computed once at load. */
const BEADS: readonly { x: number; y: number }[] = Array.from({ length: 48 }, (_, i) => {
  const a = (i / 48) * Math.PI * 2 - Math.PI / 2;
  const wobble = 1 - 0.075 * Math.cos(a * 2);
  return {
    x: Number((CX + Math.cos(a) * 84 * wobble).toFixed(1)),
    y: Number((148 + Math.sin(a) * 122).toFixed(1)),
  };
});

/* Sunburst behind the sign — signage energy without a third colour. */
const WEDGES: readonly string[] = Array.from({ length: 16 }, (_, i) => {
  const step = (Math.PI * 2) / 16;
  const r = 230;
  const p = (a: number) =>
    `${(CX + Math.cos(a) * r).toFixed(1)} ${(108 + Math.sin(a) * r).toFixed(1)}`;
  return `M${CX} 108L${p(i * step - 0.09)}L${p(i * step + 0.09)}Z`;
});

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── background plate ─────────────────────────────────── */}
      <rect
        x={8}
        y={8}
        width={224}
        height={282}
        fill={PALETTE.blue}
        opacity={0.18}
        filter="url(#ek-grain)"
      />
      <g clipPath="url(#ek-face-clip)">
        <g fill={PALETTE.blue} opacity={0.24}>
          {WEDGES.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        <rect
          x={8}
          y={8}
          width={224}
          height={282}
          fill="url(#ek-halftone-fine)"
          opacity={0.11}
        />
        {/* corner rules — the four bracket cuts a sign shop would make */}
        <g stroke={PALETTE.gold} strokeWidth={1.8} fill="none" opacity={0.75}>
          <path d="M16 44C24 30 36 20 50 15" />
          <path d="M224 44C216 30 204 20 190 15" />
          <path d="M16 254C24 268 36 278 50 283" />
          <path d="M224 254C216 268 204 278 190 283" />
        </g>
      </g>

      {/* ── cartouche ────────────────────────────────────────── */}
      <path d={CARTOUCHE} fill={PALETTE.paper} />
      {/* a flat gold tint, or the sign is paper on paper and disappears */}
      <path d={CARTOUCHE} fill={PALETTE.gold} opacity={0.17} />
      <path d={CARTOUCHE} fill="url(#ek-halftone-fine)" opacity={0.09} />
      <path
        d={CARTOUCHE}
        fill="none"
        stroke={PALETTE.gold}
        strokeWidth={4.2}
        transform={OFFSET}
      />
      <path d={CARTOUCHE} fill="none" stroke={INK} strokeWidth={2.8} filter="url(#ek-ink)" />
      <path
        d={CARTOUCHE}
        fill="none"
        stroke={PALETTE.gold}
        strokeWidth={1.4}
        opacity={0.9}
        transform={`translate(${CX} 148) scale(0.93) translate(${-CX} -148)`}
      />
      <g fill={PALETTE.gold}>
        {BEADS.map((b, i) => (
          <circle key={i} cx={b.x} cy={b.y} r={1.5} />
        ))}
      </g>

      {/* ── off-register plate ───────────────────────────────────
          The whole subject in blue at the house offset, filled *and*
          stroked so the fringe survives the 3.6px silhouette line
          landing on top of it. Blue rather than the house red because
          this card's two accents are already spent; a blue fringe on
          the gold cartouche reads exactly as loudly. */}
      <g
        transform={OFFSET}
        opacity={0.85}
        fill={PALETTE.blue}
        stroke={PALETTE.blue}
        strokeWidth={4}
        strokeLinejoin="round"
      >
        <path d={EAR_L} />
        <path d={EAR_R} />
        <path d={HEAD} />
        <path d={BEARD} />
        <path d={MOUSTACHE} />
      </g>

      {/* ── ears, behind the head ────────────────────────────── */}
      <path d={EAR_L} fill={PALETTE.paper} />
      <path d={EAR_R} fill={PALETTE.paper} />

      {/* ── head ─────────────────────────────────────────────── */}
      <path d={HEAD} fill={PALETTE.paper} />
      <path d={HEAD} fill="url(#ek-halftone-fine)" opacity={0.13} />

      {/* Skull linework goes down *before* the beard, so the beard fill
          buries the jaw. Drawn the other way round the beard hangs off
          the widest point of the head and the card reads as a cat in a
          hooded cape — which is exactly how the previous pass failed. */}
      <g
        filter="url(#ek-ink)"
        fill="none"
        stroke={INK}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d={EAR_L_IN} fill={PALETTE.gold} strokeWidth={1.6} />
        <path d={EAR_R_IN} fill={PALETTE.gold} strokeWidth={1.6} />
        <path d={EAR_L_LINE} strokeWidth={3.2} />
        <path d={EAR_R_LINE} strokeWidth={3.2} />
        <path d={HEAD} strokeWidth={3.6} />
        <g strokeWidth={1.8} opacity={0.9}>
          <path d="M92 54C86 50 83 43 85 37" />
          <path d="M148 53C154 49 157 42 155 36" />
        </g>
      </g>

      {/* ── beard mass ───────────────────────────────────────── */}
      <path d={BEARD} fill={PALETTE.blue} />
      <path d={BEARD} fill="url(#ek-halftone)" opacity={0.16} />
      {/* the flanks fall away from the light; halftone again, not a 2nd blue */}
      <path
        d="M52 168C56 198 68 226 84 244C74 244 60 224 53 200C49 190 50 176 52 168Z
           M188 168C184 198 172 226 156 244C166 244 180 224 187 200C191 190 190 176 188 168Z"
        fill="url(#ek-halftone)"
        opacity={0.38}
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
        <path d={BEARD} strokeWidth={3.6} />
        <g>
          {GROOVE_MAJOR.map(([d, w], i) => (
            <path key={i} d={d} strokeWidth={w} />
          ))}
        </g>
        <g opacity={0.6}>
          {GROOVE_MINOR.map(([d, w], i) => (
            <path key={i} d={d} strokeWidth={w} />
          ))}
        </g>
        <g strokeWidth={1.5} opacity={0.45}>
          {WAVE.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        <g strokeWidth={1.7} opacity={0.85}>
          {CHEEK.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>

        {/* ── the face ──────────────────────────────────────────
            Half-lidded: the heavy upper lid is the whole expression,
            and the eye under it is barely open. He is being addressed
            by a lesser cat and is deciding whether to reply. */}
        <path
          d="M90 92C96 82 110 82 116 92C110 101 96 101 90 92Z"
          fill={PALETTE.paper}
          strokeWidth={2.4}
        />
        <path
          d="M124 92C130 82 144 82 150 92C144 101 130 101 124 92Z"
          fill={PALETTE.paper}
          strokeWidth={2.4}
        />
        <path
          d="M98 88C105 85 111 88 111 93C111 98 105 100 100 98C96 96 95 90 98 88Z"
          fill={INK}
          strokeWidth={0}
        />
        <path
          d="M132 88C139 85 145 88 145 93C145 98 139 100 134 98C130 96 129 90 132 88Z"
          fill={INK}
          strokeWidth={0}
        />
        <circle cx={101} cy={89} r={1.7} fill={PALETTE.paper} strokeWidth={0} />
        <circle cx={135} cy={89} r={1.7} fill={PALETTE.paper} strokeWidth={0} />
        {/* the lids, dropped a third of the way — heavier than the rim */}
        <path d="M89 91C95 81 111 81 117 90" strokeWidth={3.6} />
        <path d="M123 90C129 81 145 81 151 92" strokeWidth={3.6} />
        {/* brows: short, heavy tufts rather than long thin arcs, which at
            this spacing read as a second pair of lids. The right one has
            been raised for some time now and is not coming down. */}
        <path d="M88 75C95 68 105 67 113 70" strokeWidth={4.2} />
        <path d="M128 65C136 59 147 61 153 69" strokeWidth={4.2} />
        <g strokeWidth={1.6} opacity={0.8}>
          <path d="M91 73C89 69 90 65 93 62" />
          <path d="M103 68C102 64 104 60 108 58" />
          <path d="M134 63C134 58 137 55 141 54" />
          <path d="M147 64C148 59 151 57 155 56" />
        </g>

        {/* muzzle + nose */}
        <path d="M120 100L120 106" strokeWidth={1.8} opacity={0.7} />
        <path
          d="M112 108C115 105 125 105 128 108C128 114 124 118 120 118C116 118 112 114 112 108Z"
          fill={PALETTE.gold}
          strokeWidth={2.2}
        />
        <path d="M120 118L120 128" strokeWidth={1.8} opacity={0.85} />

        {/* ── moustache ───────────────────────────────────────
            Last, on top, filled paper: it grows off the muzzle so it
            wants the muzzle's value, and silver on navy looks
            expensive. Its own gold plate sits under it. */}
        <path d={MOUSTACHE} fill={PALETTE.paper} strokeWidth={3.2} />
        <path
          d={MOUSTACHE}
          fill="url(#ek-halftone-fine)"
          stroke="none"
          opacity={0.16}
        />
        {/* combing, running with the sweep rather than across it */}
        <g strokeWidth={1.5} opacity={0.85}>
          <path d="M114 137C102 139 88 136 76 129C70 125 64 122 60 119" />
          <path d="M112 143C99 145 87 143 76 137C69 133 65 129 61 125" />
          <path d="M110 149C99 150 91 148 83 143" />
          <path d="M126 137C138 139 152 136 164 129C170 125 176 122 180 119" />
          <path d="M128 143C141 145 153 143 164 137C171 133 175 129 179 125" />
          <path d="M130 149C141 150 149 148 157 143" />
          <path d="M120 141L120 152" />
        </g>
      </g>
    </g>
  );
}
