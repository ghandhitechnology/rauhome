/* ─────────────────────────────────────────────────────────────
   FAVOR — a tug of war you are not winning.

   Action-card skeleton, same as SKIP and ATTACK: flat saturated
   plate → ray burst → halftone bands → solid-ink subjects with an
   off-register red plate → one paper-coloured graphic device.

   ATTACK's device is three rips. SKIP's is a swerve on the floor.
   FAVOR's is the card itself — the one white object on the card,
   held in the middle of the frame, with a huge ink paw hooked over
   one end and a very small ink cat dug in on the other. The paw is
   winning. That is the whole joke, and it has to land at 60px, so
   the two combatants are black and the prize is white.

   Plates: paper + green + the red off-register fringe. Nothing else.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";
import { PALETTE, INK } from "../defs";

/* Ray burst, same generator and wedge width as the rest of the deck,
   thrown from behind the card so the struggle is lit from the middle. */
const RAYS: readonly string[] = Array.from({ length: 20 }, (_, i) => {
  const a = (i / 20) * Math.PI * 2 - 0.32;
  const h = 0.058;
  const r = 420;
  const x1 = (Math.cos(a - h) * r).toFixed(1);
  const y1 = (Math.sin(a - h) * r).toFixed(1);
  const x2 = (Math.cos(a + h) * r).toFixed(1);
  const y2 = (Math.sin(a + h) * r).toFixed(1);
  return `M0 0L${x1} ${y1}L${x2} ${y2}Z`;
});

/* ── the prize ───────────────────────────────────────────────
   Bowed along its length, because it is being pulled from both ends.
   Local space, centred, 112 × 76. */
const CARD =
  "M-56 -32C-30 -41 30 -41 56 -32L53 30C28 39 -28 39 -53 30Z";
const CARD_KEYLINE =
  "M-47 -24C-25 -31 25 -31 47 -24L44.6 22C24 28 -24 28 -44.6 22Z";

/* The paw device printed on the prize — the deck's own mark. */
const PRINT =
  "M-11 4C-7 -4 7 -4 11 4C13.4 9.4 9 15.4 0.6 15.6" +
  "C-3.4 15.7 -6.6 15.6 -9.6 15C-15.6 13.8 -14.6 8 -11 4Z" +
  "M-15.4 -6C-12.8 -9 -8.8 -7.6 -8.6 -3.6C-8.5 -0.2 -10.6 1.6 -13.2 0.7" +
  "C-16 -0.2 -17.6 -3.6 -15.4 -6Z" +
  "M-3.6 -11.6C-1 -14.6 3 -13.2 3.2 -9.2C3.3 -5.6 1.2 -3.8 -1.4 -4.8" +
  "C-4.2 -5.8 -5.8 -9.2 -3.6 -11.6Z" +
  "M9.4 -9.6C12 -12.2 15.6 -10.6 15.4 -6.8C15.3 -3.6 13.2 -2 10.8 -3" +
  "C8.2 -4.1 7.2 -7.4 9.4 -9.6Z";

/* ── the taker ───────────────────────────────────────────────
   One ink mass entering off the bottom-left corner: a foreleg that
   tapers as it rises, a mitt at the top of it, and three toes hooked
   over the near end of the card with the claws out. Drawn as
   overlapping ink shapes — the union is the silhouette. */
const ARM =
  "M2 300C4 262 12 222 30 194C40 179 52 168 66 161" +
  "C82 153 96 161 97 176C98 190 88 202 76 209" +
  "C62 218 53 236 47 257C42 274 40 288 40 300Z";
const MITT =
  "M46 158C56 143 76 138 90 147C104 156 108 172 104 189" +
  "C99 206 86 218 69 219C51 220 39 208 37 191C35 174 39 166 46 158Z";
const TOES: readonly string[] = [
  "M76 141C90 133 110 137 116 149C121 160 112 170 99 168C87 166 78 157 76 148Z",
  "M84 165C99 158 118 163 122 175C126 187 116 196 103 193C91 190 83 180 82 171Z",
  "M78 190C93 184 110 190 113 202C116 214 105 221 93 218C82 215 76 204 75 196Z",
];
const CLAWS: readonly string[] = [
  "M113 143C124 141 133 147 135 157C130 149 122 145 113 148Z",
  "M119 168C130 167 139 175 140 185C135 176 127 172 118 174Z",
  "M110 194C121 194 129 202 129 212C124 203 117 199 108 201Z",
];

/* ── the loser ───────────────────────────────────────────────
   Small, braced, and losing. Local space: origin at the chest, head
   up-left, rump down-right, both forepaws reaching left onto the
   card, hind legs skidding out from under it. */
const L_HAUNCH =
  "M4 8C22 2 40 12 46 32C52 52 45 74 30 82C14 90 -2 84 -8 70" +
  "C-14 54 -10 22 4 8Z";
const L_HIND =
  "M22 74C36 78 46 90 46 102C46 110 38 114 30 110C22 106 14 98 10 88Z";
const L_TORSO =
  "M-30 -4C-18 -18 6 -20 18 -8C30 4 28 26 14 34C-2 43 -24 36 -30 20" +
  "C-34 11 -34 2 -30 -4Z";
const L_TAIL =
  "M40 20C58 8 76 8 86 20C92 28 88 38 79 38C73 38 70 32 72 26" +
  "C74 18 62 14 44 26Z";
const L_SKULL =
  "M-46 -32C-46 -50 -32 -62 -14 -62C4 -62 18 -50 18 -33" +
  "C18 -16 4 -4 -14 -4C-32 -4 -46 -15 -46 -32Z";
/* Ears pinned flat back against the skull — broad triangles off the
   outer top corners, not spires off the crown. */
const L_EAR_A = "M-42 -44C-52 -50 -60 -60 -60 -68C-48 -68 -34 -62 -26 -54Z";
const L_EAR_B = "M12 -46C18 -56 28 -64 38 -66C38 -56 30 -46 20 -40Z";
/* Inner ear, kept to roughly half the ear. Fill more than that and the
   ear stops reading as a cat's ear and starts reading as a leaf. */
const L_EAR_A_IN = "M-41 -50C-45 -53 -48 -57 -49 -61C-44 -60 -39 -58 -36 -55Z";
const L_EAR_B_IN = "M17 -49C21 -54 26 -59 32 -61C32 -55 27 -50 22 -47Z";

/* ── the loser's grip ────────────────────────────────────────
   Drawn in card-space rather than cat-space, and painted AFTER the
   card, because a grip that ends up behind the thing it is gripping
   is not a grip. Two mitts hooked over the far edge, claws in. */
const GRIP: readonly string[] = [
  "M170 138C180 134 190 140 190 150C190 161 181 167 170 165" +
    "C159 163 153 157 153 149C153 142 163 139 170 138Z",
  "M176 174C186 170 196 176 196 186C196 197 187 203 176 201" +
    "C165 199 159 193 159 185C159 178 169 175 176 174Z",
];
const GRIP_CLAWS: readonly string[] = [
  "M155 155C147 157 141 163 139 171C143 164 149 160 156 161Z",
  "M156 145C148 144 142 148 140 155C144 149 150 146 157 148Z",
  "M161 191C153 193 147 198 145 206C149 199 155 195 162 196Z",
  "M162 181C154 180 148 184 146 191C150 185 156 182 163 184Z",
];

export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* ── plate ─────────────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={288} fill={PALETTE.green} filter="url(#ek-grain)" />

      {/* ── ray burst behind the prize ────────────────────── */}
      <g transform="translate(116 158)" fill={INK} opacity={0.13}>
        {RAYS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>

      {/* ── tone fields ───────────────────────────────────── */}
      <rect x={6} y={6} width={228} height={54} fill="url(#ek-halftone-fine)" opacity={0.24} />
      <rect x={6} y={230} width={228} height={64} fill="url(#ek-halftone)" opacity={0.2} />

      {/* ── the pull: two long arcs dragging back to the paw ── */}
      <g
        fill="none"
        stroke={PALETTE.paper}
        strokeWidth={3}
        strokeLinecap="round"
        opacity={0.45}
        filter="url(#ek-ink)"
      >
        <path d="M18 132C34 100 62 78 98 68" />
        <path d="M12 172C16 132 38 98 72 78" />
      </g>

      {/* ── the loser, behind the card ─────────────────────── */}
      <g transform="translate(188.6 133.7) rotate(12) scale(0.86)" fill={PALETTE.red}>
        <path d={L_TAIL} />
        <path d={L_HAUNCH} />
        <path d={L_HIND} />
        <path d={L_TORSO} />
        <path d={L_EAR_A} />
        <path d={L_EAR_B} />
        <path d={L_SKULL} />
      </g>
      <g transform="translate(191 132) rotate(12) scale(0.86)" filter="url(#ek-ink)">
        <g fill={INK}>
          <path d={L_TAIL} />
          <path d={L_HAUNCH} />
          <path d={L_HIND} />
          <path d={L_TORSO} />
          <path d={L_EAR_A} />
          <path d={L_EAR_B} />
          <path d={L_SKULL} />
        </g>

        {/* inner ears, in the card's own green */}
        <path d={L_EAR_A_IN} fill={PALETTE.green} />
        <path d={L_EAR_B_IN} fill={PALETTE.green} />

        {/* flank bars + a rump patch, cut in paper, so the little cat is
            not one bald black bean at reading distance */}
        <g fill={PALETTE.paper} opacity={0.55}>
          <path d="M14 20C20 26 24 33 25 41C20 34 15 28 9 24Z" />
          <path d="M10 38C17 44 21 51 22 59C16 52 11 46 5 42Z" />
          <path d="M4 55C11 60 15 67 16 74C10 68 5 62 -1 58Z" />
        </g>
        <path
          d="M6 16C18 12 30 20 34 34C37 47 32 62 22 68C13 74 2 70 -2 60C-6 47 -4 24 6 16Z"
          fill={PALETTE.paper}
          opacity={0.22}
        />
        <path d="M78 30C82 26 82 20 79 16C86 18 90 26 88 34Z" fill={PALETTE.paper} opacity={0.7} />

        {/* ── the face ──────────────────────────────────────
            Eyes blown wide with the pupils shrunk to pinpricks, brows
            hauled up and inward, teeth gritted. It knows how this ends. */}
        <path
          d="M-38 -36C-38 -45 -32 -51 -25 -51C-18 -51 -12 -45 -12 -36
             C-12 -28 -18 -22 -25 -22C-32 -22 -38 -28 -38 -36Z"
          fill={PALETTE.paper}
        />
        <path
          d="M-11 -37C-11 -45 -6 -51 0 -51C6 -51 11 -45 11 -37
             C11 -29 6 -23 0 -23C-6 -23 -11 -29 -11 -37Z"
          fill={PALETTE.paper}
        />
        <path
          d="M-27.6 -40C-24.4 -40 -22 -37.4 -22 -34.2C-22 -31 -24.4 -28.4 -27.6 -28.4
             C-30.6 -28.4 -33 -31 -33 -34.2C-33 -37.4 -30.6 -40 -27.6 -40Z"
          fill={INK}
        />
        <path
          d="M-1.4 -41C1.6 -41 4 -38.4 4 -35.2C4 -32 1.6 -29.4 -1.4 -29.4
             C-4.4 -29.4 -6.8 -32 -6.8 -35.2C-6.8 -38.4 -4.4 -41 -1.4 -41Z"
          fill={INK}
        />
        <g fill="none" stroke={PALETTE.paper} strokeWidth={2.8} strokeLinecap="round">
          <path d="M-42 -50C-37 -55 -29 -56 -23 -54" />
          <path d="M-4 -55C2 -57 10 -55 14 -50" />
        </g>
        {/* strain ticks off the temple */}
        <g fill={PALETTE.paper} opacity={0.8}>
          <path d="M-52 -50C-56 -54 -59 -58 -61 -63C-57 -60 -53 -56 -49 -53Z" />
          <path d="M-58 -36C-63 -37 -68 -39 -72 -42C-67 -41 -62 -40 -56 -39Z" />
        </g>
        {/* gritted mouth, cut in paper with the teeth ruled across it */}
        <path
          d="M-27 -14C-19 -19 -3 -19 5 -14C6 -4 -3 3 -11 3C-19 3 -28 -4 -27 -14Z"
          fill={PALETTE.paper}
        />
        <path
          d="M-24 -12C-16 -16 -4 -16 3 -12C3 -8 -2 -5 -11 -5C-19 -5 -25 -8 -24 -12Z"
          fill={INK}
        />
        <path
          d="M-21.6 -12.6L-17.6 -9L-13.6 -12.6L-9.6 -9L-5.6 -12.6L-1.6 -9"
          fill="none"
          stroke={PALETTE.paper}
          strokeWidth={1.9}
          strokeLinejoin="round"
        />
        {/* whiskers, cut in paper straight off the muzzle */}
        <g fill={PALETTE.paper} opacity={0.9}>
          <path d="M-30 -12C-40 -14 -50 -14 -58 -12C-50 -16 -40 -17 -30 -16Z" />
          <path d="M-29 -5C-39 -3 -48 0 -55 5C-47 -1 -38 -4 -29 -9Z" />
        </g>
      </g>

      {/* sweat bead flung off the loser's head */}
      <g transform="translate(206 78) rotate(18)">
        <path
          d="M0 -12C4 -5 7 0 7 4C7 9 4 12 0 12C-4 12 -7 9 -7 4C-7 0 -4 -5 0 -12Z"
          fill={PALETTE.red}
          transform="translate(-2.8 1.7)"
        />
        <path
          d="M0 -12C4 -5 7 0 7 4C7 9 4 12 0 12C-4 12 -7 9 -7 4C-7 0 -4 -5 0 -12Z"
          fill={PALETTE.paper}
          filter="url(#ek-ink)"
        />
      </g>

      {/* ── the prize ─────────────────────────────────────── */}
      <g transform="translate(114 182) rotate(-12) scale(1.1)">
        <path d={CARD} fill={PALETTE.red} transform="translate(-3 1.8)" />
        <g filter="url(#ek-ink)">
          <path d={CARD} fill={PALETTE.paper} stroke={INK} strokeWidth={3.4} strokeLinejoin="round" />
          <path
            d={CARD_KEYLINE}
            fill="none"
            stroke={PALETTE.green}
            strokeWidth={2.6}
            strokeLinejoin="round"
          />
          {/* title band, so it reads as one of these cards and not a napkin */}
          <path d="M-40 14C-18 9 18 9 40 14L38.6 24C17 19 -17 19 -38.6 24Z" fill={INK} />
          <path d={PRINT} fill={INK} transform="translate(15 -4) scale(1.18)" />
          {/* stress creases running out of both grips */}
          <g fill="none" stroke={INK} strokeWidth={1.8} strokeLinecap="round" opacity={0.55}>
            <path d="M-42 -14C-30 -10 -20 -8 -10 -8" />
            <path d="M-41 4C-29 2 -20 2 -12 4" />
            <path d="M42 -16C32 -12 24 -10 16 -10" />
            <path d="M41 6C31 4 23 4 15 6" />
          </g>
        </g>
      </g>

      {/* ── the loser's grip, hooked over the far edge ─────── */}
      <g transform="translate(-3 1.8)" fill={PALETTE.red}>
        {GRIP.map((d, i) => (
          <path key={i} d={d} />
        ))}
        {GRIP_CLAWS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      <g filter="url(#ek-ink)">
        <g fill={INK}>
          {GRIP.map((d, i) => (
            <path key={i} d={d} />
          ))}
          {GRIP_CLAWS.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        <g fill="none" stroke={PALETTE.paper} strokeWidth={2.2} strokeLinecap="round" opacity={0.8}>
          <path d="M167 141C169 146 170 152 169 158" />
          <path d="M179 140C181 145 182 151 181 157" />
          <path d="M173 177C175 182 176 188 175 194" />
          <path d="M185 176C187 181 188 187 187 193" />
        </g>
      </g>

      {/* ── the one it already lost, face-down on the floor ── */}
      <g transform="translate(172 254) rotate(26) scale(0.4)">
        <path d={CARD} fill={PALETTE.red} transform="translate(-7 4.4)" />
        <g filter="url(#ek-ink)">
          <path d={CARD} fill={PALETTE.paper} stroke={INK} strokeWidth={8.5} strokeLinejoin="round" />
          <path d={PRINT} fill={INK} transform="scale(1.5)" />
        </g>
      </g>

      {/* skid marks — the heels are dug in and it is not helping */}
      <g
        fill="none"
        stroke={PALETTE.paper}
        strokeWidth={3}
        strokeLinecap="round"
        opacity={0.55}
        filter="url(#ek-ink)"
      >
        <path d="M206 218C214 226 219 236 220 248" />
        <path d="M190 232C197 239 201 249 202 260" />
      </g>

      {/* ── the taker, in front of everything ─────────────── */}
      <g transform="translate(-26.8 19.8) scale(0.94)" fill={PALETTE.red}>
        <path d={ARM} />
        <path d={MITT} />
        {TOES.map((d, i) => (
          <path key={i} d={d} />
        ))}
        {CLAWS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      <g transform="translate(-24 18) scale(0.94)" filter="url(#ek-ink)">
        <g fill={INK}>
          <path d={ARM} />
          <path d={MITT} />
          {TOES.map((d, i) => (
            <path key={i} d={d} />
          ))}
          {CLAWS.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        {/* toe separations and knuckle folds, cut back out in paper */}
        <g fill="none" stroke={PALETTE.paper} strokeWidth={2.4} strokeLinecap="round" opacity={0.85}>
          <path d="M79 155C70 158 61 158 52 155" />
          <path d="M85 179C75 182 65 182 56 179" />
          <path d="M79 199C70 202 61 202 53 199" />
          <path d="M46 216C55 224 64 228 75 228" opacity={0.5} />
        </g>
        {/* fur tufts breaking the long edge of the leg */}
        <g fill={PALETTE.paper} opacity={0.5}>
          <path d="M25 224C33 226 39 232 42 240C36 234 30 230 22 228Z" />
          <path d="M13 258C21 259 27 264 30 271C24 265 19 262 11 261Z" />
          <path d="M40 194C48 195 54 199 58 205C51 200 45 198 37 197Z" />
        </g>
      </g>

      {/* ── strain marks where the card is being pulled apart ── */}
      <g
        fill="none"
        stroke={PALETTE.paper}
        strokeLinecap="round"
        strokeWidth={2.8}
        opacity={0.75}
        filter="url(#ek-ink)"
      >
        <path d="M104 116C100 109 98 102 97 95" />
        <path d="M130 112C130 104 131 97 133 91" />
        <path d="M154 114C157 107 161 101 166 96" />
        <path d="M100 216C96 223 93 230 91 237" />
        <path d="M136 220C137 228 137 235 136 243" />
      </g>
    </g>
  );
}
