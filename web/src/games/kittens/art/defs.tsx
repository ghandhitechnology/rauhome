/* ─────────────────────────────────────────────────────────────
   Exploding Kittens — shared print plate

   Everything in this file exists so that thirteen cards drawn by
   thirteen different hands come off the same press. Mount <CardDefs/>
   exactly once, at the table root; every face references its ids.

   The look is a cheap three-colour screenprint on uncoated stock:
   the ink sits slightly proud of the paper, the paper fibre eats a
   little of it, and one plate is off register. All three of those are
   filters here rather than hand-drawn per card, because doing them by
   hand thirteen times guarantees thirteen slightly different decks.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement } from "react";

/** Card stock, linework, and the five accent plates. Never hardcode a hex. */
export const PALETTE = {
  paper: "#F2E8D5",
  ink: "#17130F",
  red: "#D6402F",
  blue: "#2C5F8A",
  green: "#4E8B5A",
  gold: "#E0A32E",
  pink: "#E08CA0",
  violet: "#6B4C93",
} as const;

/** Shorthand for the one colour every card draws linework in. */
export const INK = PALETTE.ink;

export type PaletteKey = keyof typeof PALETTE;

/** A card face: SVG children only, no <svg> wrapper, no props, no randomness. */
export type Face = () => ReactElement;

/* Geometry the frame and the faces agree on. */
export const CARD_W = 240;
export const CARD_H = 336;
/** Illustration safe area — x 16→224, y 16→280. */
export const SAFE = { x: 16, y: 16, w: 208, h: 264 } as const;

export function CardDefs(): ReactElement {
  return (
    <svg
      width={0}
      height={0}
      aria-hidden="true"
      focusable="false"
      style={{
        position: "absolute",
        width: 0,
        height: 0,
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      <defs>
        {/* ── ek-grain ────────────────────────────────────────────
            Applied to a face's flat background plate. Two things happen:
            a very low-frequency displacement (scale 1.5) so the edge of
            the plate is not laser-straight, and a sparse dark speckle
            multiplied back in so the flat fill has fibre in it.

            The speckle alpha is a thresholded noise luminance — most of
            the field clamps to zero, so you get scattered flecks rather
            than an even grey veil. Turn numOctaves up and it becomes TV
            static, which is why it is 3 and stays 3. */}
        <filter
          id="ek-grain"
          x="-6%"
          y="-6%"
          width="112%"
          height="112%"
          filterUnits="objectBoundingBox"
          colorInterpolationFilters="sRGB"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.045"
            numOctaves={2}
            seed={7}
            result="ek-warp"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="ek-warp"
            scale={1.5}
            xChannelSelector="R"
            yChannelSelector="G"
            result="ek-plate"
          />
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.85"
            numOctaves={3}
            seed={13}
            result="ek-fibre"
          />
          {/* flat warm-black fleck; alpha = 0.62·luma − 0.30, so it is mostly empty */}
          <feColorMatrix
            in="ek-fibre"
            type="matrix"
            values="0 0 0 0 0.09
                    0 0 0 0 0.075
                    0 0 0 0 0.06
                    0.21 0.21 0.20 0 -0.30"
            result="ek-fleck"
          />
          <feComposite in="ek-fleck" in2="ek-plate" operator="in" result="ek-fleckClipped" />
          <feBlend in="ek-plate" in2="ek-fleckClipped" mode="multiply" />
        </filter>

        {/* ── ek-ink ──────────────────────────────────────────────
            Applied to a face's linework group. A hair of wobble so the
            strokes are not machine-perfect, then dilate + blur + an alpha
            gain that pulls the edge back sharp. Net effect: strokes read
            ~0.4px fatter with a soft bloom where they meet, the way ink
            spreads into uncoated stock. It should never look blurry — if
            it does, slope on the feFuncA is too low. */}
        <filter
          id="ek-ink"
          x="-8%"
          y="-8%"
          width="116%"
          height="116%"
          filterUnits="objectBoundingBox"
          colorInterpolationFilters="sRGB"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.09"
            numOctaves={2}
            seed={21}
            result="ek-jitter"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="ek-jitter"
            scale={0.9}
            xChannelSelector="R"
            yChannelSelector="G"
            result="ek-wobbled"
          />
          <feMorphology in="ek-wobbled" operator="dilate" radius={0.28} result="ek-spread" />
          <feGaussianBlur in="ek-spread" stdDeviation={0.42} result="ek-bleed" />
          <feComponentTransfer in="ek-bleed">
            <feFuncA type="linear" slope={2.1} intercept={-0.28} />
          </feComponentTransfer>
        </filter>

        {/* ── ek-misprint ─────────────────────────────────────────
            The single trick that sells "printed" over "rendered": a red
            plate laid down 1.5px off register, showing as a fringe on the
            left/top of whatever it is applied to. Apply it to a shape
            whose own fill is ink or an accent; the fringe appears behind.

            Faces that want a *coloured* misprint (e.g. the blue plate on
            a blue card) should instead duplicate the shape by hand at
            translate(-1.5, 1) — this filter is the quick, uniform one. */}
        <filter
          id="ek-misprint"
          x="-12%"
          y="-12%"
          width="124%"
          height="124%"
          filterUnits="objectBoundingBox"
          colorInterpolationFilters="sRGB"
        >
          <feOffset in="SourceAlpha" dx={-1.5} dy={1} result="ek-shift" />
          <feFlood floodColor={PALETTE.red} floodOpacity={0.85} result="ek-plateRed" />
          <feComposite in="ek-plateRed" in2="ek-shift" operator="in" result="ek-fringe" />
          <feMerge>
            <feMergeNode in="ek-fringe" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* ── ek-halftone ─────────────────────────────────────────
            Shading fields. 5px grid, staggered so the dots sit on a 45°
            lattice like a real screen. Ink-coloured; drop the opacity on
            the rect that uses it to control tone. Two extra tints are
            provided because accent-coloured shading in a pattern cannot
            inherit fill from the referencing element. */}
        <pattern id="ek-halftone" patternUnits="userSpaceOnUse" width={5} height={5}>
          <circle cx={1.25} cy={1.25} r={1.05} fill={PALETTE.ink} />
          <circle cx={3.75} cy={3.75} r={1.05} fill={PALETTE.ink} />
        </pattern>
        <pattern id="ek-halftone-fine" patternUnits="userSpaceOnUse" width={3} height={3}>
          <circle cx={0.75} cy={0.75} r={0.55} fill={PALETTE.ink} />
          <circle cx={2.25} cy={2.25} r={0.55} fill={PALETTE.ink} />
        </pattern>
        <pattern id="ek-halftone-red" patternUnits="userSpaceOnUse" width={5} height={5}>
          <circle cx={1.25} cy={1.25} r={1.15} fill={PALETTE.red} />
          <circle cx={3.75} cy={3.75} r={1.15} fill={PALETTE.red} />
        </pattern>

        {/* Radiating rays — drop behind a subject for cheap comic energy. */}
        <pattern
          id="ek-rays"
          patternUnits="userSpaceOnUse"
          width={12}
          height={12}
          patternTransform="rotate(24)"
        >
          <rect width={12} height={12} fill="none" />
          <path d="M0 0 L4 0 L4 12 L0 12 Z" fill={PALETTE.ink} opacity={0.9} />
        </pattern>

        {/* ── ek-foil ─────────────────────────────────────────────
            Warm metallic, gold→bronze→gold with a hot band at 46%.
            exploding_kitten only. */}
        <linearGradient id="ek-foil" x1="0" y1="0" x2="0.85" y2="1">
          <stop offset="0%" stopColor="#8A5A16" />
          <stop offset="18%" stopColor={PALETTE.gold} />
          <stop offset="40%" stopColor="#FBE6A8" />
          <stop offset="46%" stopColor="#FFF6DC" />
          <stop offset="56%" stopColor={PALETTE.gold} />
          <stop offset="78%" stopColor="#A96E1C" />
          <stop offset="100%" stopColor="#E8BC5C" />
        </linearGradient>

        {/* ── ek-foil-dark ────────────────────────────────────────
            Cooler, steel-and-violet. defuse only. */}
        <linearGradient id="ek-foil-dark" x1="0.1" y1="0" x2="0.9" y2="1">
          <stop offset="0%" stopColor="#20303F" />
          <stop offset="20%" stopColor={PALETTE.blue} />
          <stop offset="42%" stopColor="#BFD4E4" />
          <stop offset="50%" stopColor="#E9F1F7" />
          <stop offset="60%" stopColor="#6E8FAC" />
          <stop offset="80%" stopColor={PALETTE.violet} />
          <stop offset="100%" stopColor="#4A6B87" />
        </linearGradient>

        {/* Vignette for the card back — keeps the emblem the brightest thing. */}
        <radialGradient id="ek-back-glow" cx="0.5" cy="0.44" r="0.62">
          <stop offset="0%" stopColor="#33261C" />
          <stop offset="62%" stopColor="#1D1611" />
          <stop offset="100%" stopColor="#100C09" />
        </radialGradient>

        {/* Card back lattice — tiny paw + fuse marks on a diagonal grid. */}
        <pattern
          id="ek-back-lattice"
          patternUnits="userSpaceOnUse"
          width={26}
          height={26}
          patternTransform="rotate(-18)"
        >
          <g fill={PALETTE.gold} opacity={0.17}>
            <path d="M6 9c1.4-1.9 4-1.9 5.4 0 1 1.4.2 3-1.6 3.2-1 .1-1.9.1-2.9 0-1.7-.2-2-1.8-.9-3.2Z" />
            <ellipse cx={5.1} cy={6.2} rx={1.05} ry={1.5} transform="rotate(-16 5.1 6.2)" />
            <ellipse cx={8.7} cy={5.3} rx={1.05} ry={1.6} />
            <ellipse cx={12.2} cy={6.4} rx={1.05} ry={1.5} transform="rotate(16 12.2 6.4)" />
          </g>
          <g
            stroke={PALETTE.red}
            strokeWidth={1.3}
            fill="none"
            opacity={0.28}
            strokeLinecap="round"
          >
            <path d="M18 20.5c2.6-.4 3.2-3 1.3-4.2" />
            <circle cx={20.6} cy={14.9} r={1.1} fill={PALETTE.red} stroke="none" />
          </g>
        </pattern>

        {/* Clips the frame and the illustration area. Shared so faces can
            reuse them without minting colliding ids. */}
        <clipPath id="ek-card-clip">
          <rect x={0} y={0} width={CARD_W} height={CARD_H} rx={15} ry={15} />
        </clipPath>
        <clipPath id="ek-face-clip">
          <rect x={8} y={8} width={CARD_W - 16} height={CARD_H - 8 - 46} rx={9} ry={9} />
        </clipPath>
      </defs>
    </svg>
  );
}

export default CardDefs;
