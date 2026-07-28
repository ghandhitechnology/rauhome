/**
 * What the game calls things, kept beside the board rather than inside `art/`.
 *
 * The art folder owns how a knight is *drawn*; this owns that it is a knight,
 * that the square under it is called e4, and that a game which ended on
 * `"stalemate"` should say so in a sentence rather than in a keyword. Same
 * split as the card table: one module for the shapes, one for the words.
 *
 * The words matter more here than they do next door. A chess board is mostly
 * silent — there is no card face to read, no title band, no countdown — so for
 * anyone not looking at it the labels in this file *are* the board, and they
 * are written to be heard in order: the square, then who is on it. "e4, white
 * knight" is a position being read out. "White knight on e4" is a commentator.
 */

import type { PieceType, Placed } from './board'
import type { Promotion, TableState } from './useGame'

export const PIECE_NAMES: Record<PieceType, string> = {
  p: 'pawn',
  n: 'knight',
  b: 'bishop',
  r: 'rook',
  q: 'queen',
  k: 'king',
}

/**
 * What a pawn may become, in the order the picker offers them.
 *
 * The queen first because it is the answer nine times in ten, and the knight
 * last but present because the one time in ten is the whole reason the choice
 * exists at all. Bishop and rook are almost never right, and are here because
 * a picker that quietly dropped two of the four legal answers would be the
 * client deciding the game again.
 */
export const PROMOTION_CHOICES: readonly Promotion[] = ['q', 'r', 'b', 'n']

/** `'white knight'` — what a piece is, for a label that has room for it. */
export function pieceLabel(piece: Placed): string {
  return `${piece.color} ${PIECE_NAMES[piece.type]}`
}

/** What a square is, read out: its name, then whoever is standing on it. */
export function squareLabel(square: string, piece: Placed | undefined): string {
  return piece ? `${square}, ${pieceLabel(piece)}` : `${square}, empty`
}

/**
 * How a finished game reads.
 *
 * The reason arrives from the server as a bare term — `checkmate`,
 * `resignation`, `fifty-move rule` — which is the right thing to store and the
 * wrong thing to put on screen underneath a heading. Anything unrecognised
 * falls through as itself: a new termination reason showing up verbatim is
 * mildly ugly, and better than a game that ended for no stated cause.
 */
const REASON_LINES: Record<string, { won: string; lost: string; drawn: string }> = {
  checkmate: {
    won: 'Mate. He had nowhere to put the king.',
    lost: 'Mate. Nowhere left to put the king.',
    drawn: '',
  },
  resignation: {
    won: 'He tipped his king over.',
    lost: 'You resigned.',
    drawn: '',
  },
  stalemate: {
    won: '',
    lost: '',
    drawn: 'Stalemate — no legal move, and no check to answer.',
  },
  'draw agreed': { won: '', lost: '', drawn: 'You shook on it.' },
  'threefold repetition': {
    won: '',
    lost: '',
    drawn: 'The same position, three times. Nobody was going anywhere.',
  },
  'fifty-move rule': {
    won: '',
    lost: '',
    drawn: 'Fifty moves without a capture or a pawn. That is the rule, not a verdict.',
  },
  'insufficient material': {
    won: '',
    lost: '',
    drawn: 'Nothing left on either side that could finish it.',
  },
}

export type ResultLine = { title: string; note: string }

export function resultLine(table: TableState): ResultLine {
  const drawn = table.winner === null
  const won = table.winner === 'user'
  const lines = REASON_LINES[table.over_reason]
  const note = lines
    ? (drawn ? lines.drawn : won ? lines.won : lines.lost) || table.over_reason
    : table.over_reason
  return {
    title: drawn ? 'Drawn.' : won ? 'You win.' : 'He wins.',
    note,
  }
}
