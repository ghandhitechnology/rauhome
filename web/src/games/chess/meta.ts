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

import { tr } from '../../i18n'
import type { PieceType, Placed } from './board'
import type { Promotion, TableState } from './useGame'

/**
 * Read through a function rather than held in a constant: the language can
 * change while a game is on the table, and a frozen record would keep naming
 * the pieces in whichever language the module was first imported under.
 */
export function pieceName(type: PieceType): string {
  return tr(`piece.${type}`)
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
  return tr('chess.pieceLabel', {
    color: tr(`piece.${piece.color}`),
    piece: pieceName(piece.type),
  })
}

/** What a square is, read out: its name, then whoever is standing on it. */
export function squareLabel(square: string, piece: Placed | undefined): string {
  return piece
    ? tr('chess.squareLabel', { square, piece: pieceLabel(piece) })
    : tr('chess.squareEmpty', { square })
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
function reasonLines(): Record<string, { won: string; lost: string; drawn: string }> {
  return {
    checkmate: {
      won: tr('chess.reason.checkmate.won'),
      lost: tr('chess.reason.checkmate.lost'),
      drawn: '',
    },
    resignation: {
      won: tr('chess.reason.resignation.won'),
      lost: tr('chess.reason.resignation.lost'),
      drawn: '',
    },
    stalemate: { won: '', lost: '', drawn: tr('chess.reason.stalemate') },
    'draw agreed': { won: '', lost: '', drawn: tr('chess.reason.agreed') },
    'threefold repetition': { won: '', lost: '', drawn: tr('chess.reason.threefold') },
    'fifty-move rule': { won: '', lost: '', drawn: tr('chess.reason.fifty') },
    'insufficient material': { won: '', lost: '', drawn: tr('chess.reason.material') },
  }
}

export type ResultLine = { title: string; note: string }

export function resultLine(table: TableState): ResultLine {
  const drawn = table.winner === null
  const won = table.winner === 'user'
  const lines = reasonLines()[table.over_reason]
  const note = lines
    ? (drawn ? lines.drawn : won ? lines.won : lines.lost) || table.over_reason
    : table.over_reason
  return {
    title: drawn ? tr('chess.drawn') : won ? tr('chess.youWin') : tr('chess.heWins'),
    note,
  }
}
