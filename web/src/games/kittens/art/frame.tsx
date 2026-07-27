/* ─────────────────────────────────────────────────────────────
   Exploding Kittens — the die-cut

   <CardFrame/> is the printed object every face is stuck onto: stock,
   keyline, corner pips, title band. <CardBack/> is the face-down card,
   which is on screen more than any face and is therefore built as a
   different object entirely — dark stock, gold plate, no title band.
   ───────────────────────────────────────────────────────────── */

import type { ReactElement, ReactNode } from "react";
import { PALETTE, CARD_W, CARD_H } from "./defs";

export type CardKind = "cat" | "action" | "kitten" | "defuse";

export interface CardFrameProps {
  /** Displayed uppercase in the title band, and used as the card's a11y name. */
  title: string;
  /** One of PALETTE — the card's loud plate. */
  accent: string;
  /** The face: SVG children only. */
  children?: ReactNode;
  kind?: CardKind;
}

/* Title band geometry. The spec reserves the bottom 44px; the band itself
   sits inside that with the keyline still visible around it. */
const BAND = { x: 13, y: 289, w: CARD_W - 26, h: 36, r: 7 } as const;
const BAND_MID = BAND.y + BAND.h / 2;

/**
 * DM Sans 600 uppercase runs about 0.63em per glyph. Rather than measure at
 * runtime (which would make the card non-deterministic across fonts loading),
 * we estimate and clamp. "SEE THE FUTURE" lands at ~18px, "NOPE" at the 24px
 * ceiling — the range a real deck actually uses.
 */
function titleSize(title: string): number {
  const n = Math.max(1, title.trim().length);
  const emWidth = n * 0.63 - (n - 1) * 0.02;
  return Math.max(10.5, Math.min(24, (BAND.w - 26) / emWidth));
}

/** Up to two letters for the corner pip: "SEE THE FUTURE" → "SF", "NOPE" → "N". */
function initials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0]!.charAt(0).toUpperCase();
  return (words[0]!.charAt(0) + words[words.length - 1]!.charAt(0)).toUpperCase();
}

/* ── pip glyphs ──────────────────────────────────────────────
   Drawn inside a 20×20 box centred on the origin. Kept to a silhouette
   so they still read at a 60px-wide card. */

function CatPip(): ReactElement {
  return (
    <path
      d="M-6.4 -0.6C-6.4 -3.6 -4.9 -5.8 -2.5 -6.8L-5.7 -11.1C-6.3 -11.9 -5.4 -12.8 -4.6 -12.3L0.2 -9.4
         C0.9 -9.5 1.6 -9.5 2.3 -9.4L7 -12.3C7.8 -12.8 8.7 -11.9 8.1 -11.1L4.9 -6.8
         C7.3 -5.8 8.8 -3.6 8.8 -0.6C8.8 3.6 5.4 6.9 1.2 6.9C-3 6.9 -6.4 3.6 -6.4 -0.6Z"
      fill={PALETTE.paper}
      transform="translate(-1.2 1)"
    />
  );
}

function BombPip(): ReactElement {
  return (
    <g fill={PALETTE.paper}>
      <path d="M-1.2 -5.2C3.4 -5.2 6.6 -2.2 6.6 1.6C6.6 5.3 3.4 8 -1.2 8C-5.7 8 -8.8 5.3 -8.8 1.6C-8.8 -2.2 -5.7 -5.2 -1.2 -5.2Z" />
      <path
        d="M1.4 -5.4C2.6 -8.4 5.2 -9.4 7.4 -8.1"
        fill="none"
        stroke={PALETTE.paper}
        strokeWidth={2}
        strokeLinecap="round"
      />
      <path d="M8.6 -11.4L9.8 -8.6L12.6 -7.6L9.8 -6.6L8.6 -3.8L7.5 -6.6L4.7 -7.6L7.5 -8.6Z" />
    </g>
  );
}

function DefusePip(): ReactElement {
  return (
    <g fill="none" stroke={PALETTE.paper} strokeWidth={2} strokeLinecap="round">
      <path d="M-7.4 -6.4C-2.6 -1.6 2.2 3.2 7 8" />
      <path d="M7 -6.4C2.2 -1.6 -2.6 3.2 -7.4 8" />
      <circle cx={-7.6} cy={8.4} r={2.1} />
      <circle cx={7.2} cy={8.4} r={2.1} />
    </g>
  );
}

function LetterPip({ text }: { text: string }): ReactElement {
  return (
    <text
      x={0}
      y={0}
      textAnchor="middle"
      dominantBaseline="central"
      fontFamily='"DM Sans", system-ui, sans-serif'
      fontWeight={600}
      fontSize={text.length > 1 ? 11 : 14}
      letterSpacing={-0.5}
      fill={PALETTE.paper}
    >
      {text}
    </text>
  );
}

function Pip({
  kind,
  accent,
  label,
}: {
  kind: CardKind;
  accent: string;
  label: string;
}): ReactElement {
  return (
    <g>
      {/* off-register accent plate under the ink lozenge */}
      <circle cx={-1.5} cy={1} r={12.5} fill={accent} opacity={0.9} />
      <circle cx={0} cy={0} r={12.5} fill={PALETTE.ink} />
      <g transform="scale(0.86)">
        {kind === "cat" ? (
          <CatPip />
        ) : kind === "kitten" ? (
          <BombPip />
        ) : kind === "defuse" ? (
          <DefusePip />
        ) : (
          <LetterPip text={label} />
        )}
      </g>
    </g>
  );
}

export function CardFrame({
  title,
  accent,
  children,
  kind = "action",
}: CardFrameProps): ReactElement {
  const label = title.toUpperCase();
  const size = titleSize(label);
  const pipLabel = initials(title);

  return (
    <svg
      viewBox={`0 0 ${CARD_W} ${CARD_H}`}
      width="100%"
      height="100%"
      role="img"
      aria-label={title}
      style={{ display: "block", overflow: "visible" }}
    >
      <title>{title}</title>

      {/* ── card stock ─────────────────────────────────────── */}
      <g clipPath="url(#ek-card-clip)">
        <rect
          x={0}
          y={0}
          width={CARD_W}
          height={CARD_H}
          fill={PALETTE.paper}
          filter="url(#ek-grain)"
        />

        {/* faint halftone wash in the corners so the stock is never bare */}
        <g opacity={0.07}>
          <rect x={0} y={0} width={CARD_W} height={64} fill="url(#ek-halftone-fine)" />
          <rect x={0} y={CARD_H - 90} width={CARD_W} height={90} fill="url(#ek-halftone-fine)" />
        </g>

        {/* ── face art ─────────────────────────────────────── */}
        <g clipPath="url(#ek-face-clip)">{children}</g>

        {/* ── keyline: 2px, inset, with its accent plate off register ── */}
        <rect
          x={8.5 - 1.5}
          y={8.5 + 1}
          width={CARD_W - 17}
          height={CARD_H - 17}
          rx={10}
          ry={10}
          fill="none"
          stroke={accent}
          strokeWidth={2}
          opacity={0.75}
        />
        <rect
          x={8.5}
          y={8.5}
          width={CARD_W - 17}
          height={CARD_H - 17}
          rx={10}
          ry={10}
          fill="none"
          stroke={PALETTE.ink}
          strokeWidth={2}
          filter="url(#ek-ink)"
        />

        {/* ── corner pips ──────────────────────────────────── */}
        <g transform="translate(28 28)">
          <Pip kind={kind} accent={accent} label={pipLabel} />
        </g>
        <g transform={`translate(${CARD_W - 28} 268) rotate(180)`}>
          <Pip kind={kind} accent={accent} label={pipLabel} />
        </g>

        {/* ── title band ───────────────────────────────────── */}
        <g filter="url(#ek-ink)">
          <rect
            x={BAND.x - 1.5}
            y={BAND.y + 1}
            width={BAND.w}
            height={BAND.h}
            rx={BAND.r}
            fill={accent}
          />
          <rect
            x={BAND.x}
            y={BAND.y}
            width={BAND.w}
            height={BAND.h}
            rx={BAND.r}
            fill={PALETTE.ink}
          />
        </g>
        {/* hairline rule inside the band, broken by the type */}
        <rect
          x={BAND.x + 8}
          y={BAND.y + BAND.h - 6}
          width={BAND.w - 16}
          height={1.4}
          fill={accent}
          opacity={0.55}
        />
        <text
          x={CARD_W / 2}
          y={BAND_MID - 1}
          textAnchor="middle"
          dominantBaseline="central"
          fontFamily='"DM Sans", system-ui, sans-serif'
          fontWeight={600}
          fontSize={size}
          letterSpacing={-0.4}
          fill={PALETTE.paper}
        >
          {label}
        </text>

        {/* ── edge burn: the die-cut never has a perfectly clean rim ── */}
        <rect
          x={0.75}
          y={0.75}
          width={CARD_W - 1.5}
          height={CARD_H - 1.5}
          rx={14.5}
          ry={14.5}
          fill="none"
          stroke={PALETTE.ink}
          strokeWidth={1.5}
          opacity={0.28}
        />
      </g>
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────
   CardBack — deliberately not a face card: dark stock, gold plate,
   no title band, an emblem instead of an illustration.
   ───────────────────────────────────────────────────────────── */

export function CardBack(): ReactElement {
  return (
    <svg
      viewBox={`0 0 ${CARD_W} ${CARD_H}`}
      width="100%"
      height="100%"
      role="img"
      aria-label="Face-down card"
      style={{ display: "block", overflow: "visible" }}
    >
      <title>Face-down card</title>
      <g clipPath="url(#ek-card-clip)">
        <rect
          x={0}
          y={0}
          width={CARD_W}
          height={CARD_H}
          fill="url(#ek-back-glow)"
          filter="url(#ek-grain)"
        />
        <rect x={0} y={0} width={CARD_W} height={CARD_H} fill="url(#ek-back-lattice)" />

        {/* double keyline in gold, with a red plate a hair off register */}
        <rect
          x={9.5}
          y={12.5}
          width={CARD_W - 22}
          height={CARD_H - 22}
          rx={11}
          fill="none"
          stroke={PALETTE.red}
          strokeWidth={2}
          opacity={0.55}
        />
        <rect
          x={11}
          y={11}
          width={CARD_W - 22}
          height={CARD_H - 22}
          rx={11}
          fill="none"
          stroke={PALETTE.gold}
          strokeWidth={2}
        />
        <rect
          x={17}
          y={17}
          width={CARD_W - 34}
          height={CARD_H - 34}
          rx={7}
          fill="none"
          stroke={PALETTE.gold}
          strokeWidth={0.9}
          opacity={0.5}
        />

        {/* corner ticks */}
        <g stroke={PALETTE.gold} strokeWidth={1.6} strokeLinecap="round" opacity={0.8}>
          <path d="M23 34 L23 23 L34 23" fill="none" />
          <path d="M217 34 L217 23 L206 23" fill="none" />
          <path d="M23 302 L23 313 L34 313" fill="none" />
          <path d="M217 302 L217 313 L206 313" fill="none" />
        </g>

        {/* ── emblem ───────────────────────────────────────── */}
        <g transform={`translate(${CARD_W / 2} 168)`}>
          {/* starburst behind the medallion */}
          <g fill={PALETTE.red} opacity={0.85}>
            <path
              d="M0 -96 L13 -62 L38 -88 L27 -54 L62 -66 L38 -40 L74 -38 L41 -22 L74 -4
                 L38 -2 L60 26 L27 12 L36 48 L12 22 L0 58 L-12 22 L-36 48 L-27 12
                 L-60 26 L-38 -2 L-74 -4 L-41 -22 L-74 -38 L-38 -40 L-62 -66 L-27 -54
                 L-38 -88 L-13 -62 Z"
              transform="scale(0.82) rotate(6)"
              opacity={0.34}
            />
          </g>

          {/* medallion */}
          <circle cx={-2} cy={1.5} r={56} fill={PALETTE.red} opacity={0.7} />
          <circle cx={0} cy={0} r={56} fill={PALETTE.gold} />
          <circle
            cx={0}
            cy={0}
            r={51}
            fill="none"
            stroke={PALETTE.ink}
            strokeWidth={2}
            opacity={0.55}
          />

          {/* bead ring */}
          <g fill={PALETTE.ink} opacity={0.45}>
            {Array.from({ length: 28 }, (_, i) => {
              const a = (i / 28) * Math.PI * 2;
              return (
                <circle
                  key={i}
                  cx={Math.cos(a) * 47}
                  cy={Math.sin(a) * 47}
                  r={1.5}
                />
              );
            })}
          </g>

          {/* cat head — off-register red plate, then the ink plate */}
          <g transform="translate(-1.6 1.2)" opacity={0.75}>
            <path
              d="M-30 -2C-30 -15 -22 -25 -11 -29L-26 -48C-27.5 -50.5 -25 -52.5 -22.5 -51L-4 -39
                 C-1 -39.6 1 -39.6 4 -39L22.5 -51C25 -52.5 27.5 -50.5 26 -48L11 -29
                 C22 -25 30 -15 30 -2C30 16 18 30 0 30C-18 30 -30 16 -30 -2Z"
              fill={PALETTE.red}
              transform="scale(0.78) translate(0 6)"
            />
          </g>
          <g transform="scale(0.78) translate(0 6)" filter="url(#ek-ink)">
            <path
              d="M-30 -2C-30 -15 -22 -25 -11 -29L-26 -48C-27.5 -50.5 -25 -52.5 -22.5 -51L-4 -39
                 C-1 -39.6 1 -39.6 4 -39L22.5 -51C25 -52.5 27.5 -50.5 26 -48L11 -29
                 C22 -25 30 -15 30 -2C30 16 18 30 0 30C-18 30 -30 16 -30 -2Z"
              fill={PALETTE.ink}
            />
            {/* eyes: half-lidded, unimpressed */}
            <path
              d="M-17 -4C-13 -9 -7 -9 -3.5 -4"
              fill="none"
              stroke={PALETTE.gold}
              strokeWidth={3.2}
              strokeLinecap="round"
            />
            <path
              d="M3.5 -4C7 -9 13 -9 17 -4"
              fill="none"
              stroke={PALETTE.gold}
              strokeWidth={3.2}
              strokeLinecap="round"
            />
            {/* whisker nub + mouth */}
            <path
              d="M-5 7C-3 9.5 3 9.5 5 7"
              fill="none"
              stroke={PALETTE.gold}
              strokeWidth={2.6}
              strokeLinecap="round"
            />
          </g>

          {/* fuse + spark, breaking the medallion edge so it reads as an object */}
          <g fill="none" strokeLinecap="round">
            <path
              d="M13 -38C22 -50 34 -48 37 -60C39.5 -70 33 -76 27 -74"
              stroke={PALETTE.ink}
              strokeWidth={4.5}
            />
            <path
              d="M13 -38C22 -50 34 -48 37 -60C39.5 -70 33 -76 27 -74"
              stroke={PALETTE.gold}
              strokeWidth={1.6}
              opacity={0.5}
            />
          </g>
          <g transform="translate(25 -76)">
            <path
              d="M0 -13L4.4 -4.4L13 0L4.4 4.4L0 13L-4.4 4.4L-13 0L-4.4 -4.4Z"
              fill={PALETTE.red}
              transform="translate(-1.5 1)"
            />
            <path
              d="M0 -12L4 -4L12 0L4 4L0 12L-4 4L-12 0L-4 -4Z"
              fill={PALETTE.gold}
              filter="url(#ek-ink)"
            />
          </g>
        </g>

        {/* wordmark */}
        <text
          x={CARD_W / 2}
          y={269}
          textAnchor="middle"
          fontFamily='"DM Sans", system-ui, sans-serif'
          fontWeight={600}
          fontSize={16}
          letterSpacing={2.6}
          fill={PALETTE.gold}
        >
          EXPLODING
        </text>
        <text
          x={CARD_W / 2}
          y={289}
          textAnchor="middle"
          fontFamily='"DM Sans", system-ui, sans-serif'
          fontWeight={600}
          fontSize={16}
          letterSpacing={4.2}
          fill={PALETTE.gold}
          opacity={0.82}
        >
          KITTENS
        </text>
        <g stroke={PALETTE.red} strokeWidth={1.4} opacity={0.7}>
          <path d="M62 297 L178 297" />
        </g>

        <rect
          x={0.75}
          y={0.75}
          width={CARD_W - 1.5}
          height={CARD_H - 1.5}
          rx={14.5}
          ry={14.5}
          fill="none"
          stroke="#000"
          strokeWidth={1.5}
          opacity={0.5}
        />
      </g>
    </svg>
  );
}

export default CardFrame;
