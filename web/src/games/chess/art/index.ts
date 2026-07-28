/* ─────────────────────────────────────────────────────────────
   Chess — art barrel

   The only import the board needs. Mount <PieceDefs/> once at the
   board root — the wood, the grain and the light all live in there —
   and then render <ChessPiece type="n" finish="walnut"/> per square.

   `ChessPiece` mounts the <svg> and nothing else. It sets the viewBox,
   it sets `data-chess-finish`, and that attribute is the entire
   mechanism by which one set of drawings comes out in two woods: the
   stylesheet in `defs.tsx` hangs the custom properties off it, and no
   file under `pieces/` names a colour or knows which side it is on.

   Written with `createElement` rather than JSX because the contract
   names this file `index.ts`. It is one element; it is not worth a
   second file to get angle brackets.

   Two things the board owns and this does not:

   · **Accessibility.** Every piece is `aria-hidden`. Thirty-two SVGs
     announcing themselves is noise, and a chess position is not
     legible as a list of images in any case — the board must carry
     the position as text.

   · **Scale and stacking.** Pieces are authored base-down in a fixed
     120×200 box, with the contact point of every base on the same y
     no matter how wide it is (see `FLOOR` in `defs.tsx`). Sizing a
     square's worth of piece, and sorting nearer ranks in front of
     farther ones, is the board's geometry, not the art's.
   ───────────────────────────────────────────────────────────── */

import { createElement, type ReactElement } from 'react'

import Pawn from './pieces/pawn'
import Knight from './pieces/knight'
import Bishop from './pieces/bishop'
import Rook from './pieces/rook'
import Queen from './pieces/queen'
import King from './pieces/king'
import { VIEW } from './defs'

/** The six, in `python-chess`'s letters so nothing has to be translated. */
export type PieceType = 'p' | 'n' | 'b' | 'r' | 'q' | 'k'

export type Finish = 'maple' | 'walnut'

export const PIECE_TYPES: readonly PieceType[] = ['p', 'n', 'b', 'r', 'q', 'k'] as const

export const PIECE_ART: Record<PieceType, () => ReactElement> = {
  p: Pawn,
  n: Knight,
  b: Bishop,
  r: Rook,
  q: Queen,
  k: King,
}

/**
 * Overall height in author units, base to apex.
 *
 * These are the relative proportions of the set and they are the reason it
 * reads as one set rather than six drawings. A board that scales pieces to a
 * uniform height throws all of it away — the king has to be taller than the
 * queen, and both have to tower over the rook, or the position is unreadable
 * at a glance.
 */
export const PIECE_HEIGHT: Record<PieceType, number> = {
  p: 108,
  n: 148,
  b: 150,
  r: 128,
  q: 168,
  k: 182,
}

/**
 * Half the diameter of each base, in the same units.
 *
 * The board needs this to check a piece fits its square: a square is 3.45
 * stage units across, so the scale that makes a king's 58-unit foot sit
 * inside one is the scale every other piece has to be drawn at too.
 */
export const PIECE_BASE: Record<PieceType, number> = {
  p: 21,
  n: 24,
  b: 23,
  r: 24,
  q: 27,
  k: 29,
}

/** The turning axis and the contact line, for placing a piece on a square. */
export const PIECE_ANCHOR = { x: 60, y: 196 } as const

export function ChessPiece({
  type,
  finish,
}: {
  type: PieceType
  finish: Finish
}): ReactElement {
  return createElement(
    'svg',
    {
      viewBox: `0 0 ${VIEW.w} ${VIEW.h}`,
      width: '100%',
      height: '100%',
      // The base is at the bottom of the box and the apex floats: if the box
      // it is given is the wrong aspect, the piece must keep standing on the
      // square rather than drift up off it.
      preserveAspectRatio: 'xMidYMax meet',
      'data-chess-finish': finish,
      'aria-hidden': true,
      focusable: 'false',
      style: { display: 'block', overflow: 'visible' },
    },
    createElement(PIECE_ART[type]),
  )
}

export { PieceDefs, VIEW, CX, FLOOR, SQUASH } from './defs'
