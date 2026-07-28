/**
 * The board's arithmetic, with nothing else in it.
 *
 * `clawd/chessTableLayer.ts` owns the projection — a square's centre is
 * `origin + file · fileVec + rank · rankVec` — and it only ever runs that
 * forwards, because a canvas only ever needs to know where to paint. The DOM
 * board needs it in both directions and in three different coordinate systems
 * at once, and that is what this file is: the inverse of the projection, the
 * translation between what the server calls a square and what the lattice
 * calls one, and nothing that touches React or a socket, so all of it can be
 * checked with a number and an equals sign.
 *
 * Three spaces, and confusing two of them is the only real bug this module can
 * have, so they are named apart:
 *
 *   **square** — chess coordinates, the ones the world outside agrees on.
 *     `file` 0 is the a-file, `rank` 0 is the *first* rank. `e4` is
 *     `{file: 4, rank: 3}`, which is also what python-chess would say, which
 *     is what the server is built on.
 *
 *   **lattice** — the eight-by-eight grid as it is drawn. Column 0 is the
 *     leftmost one on screen and row 0 is the farthest away, because that is
 *     the order things have to be painted in for nearer pieces to overlap
 *     farther ones. It is the index `boardPoint` takes.
 *
 *   **stage** — the room's own units, which `gameBridge` turns into pixels.
 *
 * The bridge between the first two is the orientation, and it is not a detail:
 * the board is always drawn from the user's side of the table, so playing
 * black flips both axes and every single square changes lattice address while
 * keeping its name. Doing that conversion in one pair of functions, here, is
 * what keeps the flip from having to be remembered in eight different places
 * in the view.
 */

import { CHESS_BOARD, boardPoint } from '../../clawd/chessTableLayer'
import type { Pt } from '../../clawd/gameBridge'

/** A square in chess coordinates: `{file: 4, rank: 3}` is e4. */
export type Square = { file: number; rank: number }

/** A cell of the drawn grid: column 0 leftmost, row 0 farthest from you. */
export type Cell = { file: number; rank: number }

export type PieceType = 'p' | 'n' | 'b' | 'r' | 'q' | 'k'
export type PieceColor = 'white' | 'black'

/** Which side of the table you are sitting on, which is what the board faces. */
export type Orientation = PieceColor

/** One man on the board, as the view needs him: a name, a shape, a side. */
export type Placed = {
  /** Algebraic square name, `'e4'`. Unique per position, so it is the key. */
  square: string
  type: PieceType
  color: PieceColor
}

const FILES = 'abcdefgh'

/* ─────────────────────────────────────────────────── the projection */

/**
 * The centre of a lattice cell, in stage units.
 *
 * A one-line wrapper over the layer's own transform, and worth having anyway:
 * everything else in this file is written against the lattice, and a reader
 * should not have to know that `boardPoint` happens to take the same numbers.
 */
export function squareCenter(file: number, rank: number): Pt {
  return boardPoint(file, rank)
}

/**
 * The determinant of the projection, computed once.
 *
 * Zero would mean the two basis vectors are parallel — a board squashed to a
 * line — and there would be no cell under any point at all. It cannot happen
 * with the tuned constants, but the inverse below divides by this, and a
 * silent `Infinity` leaking out of a hit test as a plausible-looking square
 * index is a far worse failure than returning "you did not click a square".
 */
const DET = CHESS_BOARD.fileVec.x * CHESS_BOARD.rankVec.y -
  CHESS_BOARD.rankVec.x * CHESS_BOARD.fileVec.y

/**
 * Which lattice cell a stage point falls in, or null if it misses the board.
 *
 * The inverse of `squareCenter`: two equations, two unknowns, solved by
 * Cramer's rule because at this size that is both the shortest way to write it
 * and the fastest way to run it. The result is rounded rather than floored —
 * the indices name cell *centres*, so a cell owns everything within half a
 * step of its middle, which is exactly the parallelogram the canvas painted.
 */
export function hitSquare(p: Pt): Cell | null {
  if (DET === 0) return null
  const { origin, fileVec, rankVec } = CHESS_BOARD
  const dx = p.x - origin.x
  const dy = p.y - origin.y
  const file = Math.round((dx * rankVec.y - rankVec.x * dy) / DET)
  const rank = Math.round((fileVec.x * dy - dx * fileVec.y) / DET)
  if (file < 0 || file > 7 || rank < 0 || rank > 7) return null
  // Just short of the a-file and just short of the eighth rank the solve comes
  // out slightly negative, and `Math.round` hands that back as `-0`. It indexes
  // and compares as zero everywhere except under `Object.is`, which is what a
  // memoisation key or a deep-equality check would be using — so the sign is
  // normalised here rather than left as a trap one caller down.
  return { file: file + 0, rank: rank + 0 }
}

/**
 * How big one square's bounding box is, in stage units.
 *
 * The cell is a parallelogram and the DOM only positions rectangles, so every
 * square-shaped thing in the view — the last-move marks, the check pulse, the
 * hit targets — is laid out as this box centred on the square, then cut to
 * shape with a clip path. The box is derived rather than typed in so that
 * retuning the projection moves the marks with the paint.
 */
export const SQUARE_BOX = {
  w: Math.abs(CHESS_BOARD.fileVec.x) + Math.abs(CHESS_BOARD.rankVec.x),
  h: Math.abs(CHESS_BOARD.fileVec.y) + Math.abs(CHESS_BOARD.rankVec.y),
}

/**
 * The four corners of a square, as fractions of its bounding box.
 *
 * In drawing order from the far-left corner. `0.1375, 0` and so on — the shape
 * a `clip-path: polygon()` wants, in the one form that survives the box being
 * scaled by the camera.
 */
export const SQUARE_SHAPE: readonly Pt[] = (() => {
  const { fileVec, rankVec } = CHESS_BOARD
  const corners: Pt[] = [
    { x: (-fileVec.x - rankVec.x) / 2, y: (-fileVec.y - rankVec.y) / 2 },
    { x: (fileVec.x - rankVec.x) / 2, y: (fileVec.y - rankVec.y) / 2 },
    { x: (fileVec.x + rankVec.x) / 2, y: (fileVec.y + rankVec.y) / 2 },
    { x: (-fileVec.x + rankVec.x) / 2, y: (-fileVec.y + rankVec.y) / 2 },
  ]
  return corners.map((c) => ({
    x: c.x / SQUARE_BOX.w + 0.5,
    y: c.y / SQUARE_BOX.h + 0.5,
  }))
})()

/* ────────────────────────────────────────────────────────── names */

/** `{file: 4, rank: 3}` → `'e4'`. Out-of-range indices give an empty string. */
export function squareName(sq: Square): string {
  if (sq.file < 0 || sq.file > 7 || sq.rank < 0 || sq.rank > 7) return ''
  return `${FILES[sq.file]}${sq.rank + 1}`
}

/** `'e4'` → `{file: 4, rank: 3}`. Anything else is null, including `'e9'`. */
export function parseSquare(name: string): Square | null {
  if (name.length !== 2) return null
  const file = FILES.indexOf(name[0].toLowerCase())
  const rank = name.charCodeAt(1) - 49 // '1' → 0
  if (file < 0 || rank < 0 || rank > 7) return null
  return { file, rank }
}

/* ──────────────────────────────────────────────────── orientation */

/**
 * Where a named square sits on the drawn grid, from where you are sitting.
 *
 * Playing white, the a-file is on your left and the first rank is nearest, so
 * row counts down from the eighth. Playing black, both axes turn over. The
 * mapping is its own inverse in each case, which is why `fromLattice` can be
 * the same arithmetic read the other way rather than a second table to keep
 * in step.
 */
export function toLattice(sq: Square, view: Orientation): Cell {
  return view === 'white'
    ? { file: sq.file, rank: 7 - sq.rank }
    : { file: 7 - sq.file, rank: sq.rank }
}

/** The named square at a cell of the drawn grid. The inverse of `toLattice`. */
export function fromLattice(cell: Cell, view: Orientation): Square {
  return view === 'white'
    ? { file: cell.file, rank: 7 - cell.rank }
    : { file: 7 - cell.file, rank: cell.rank }
}

/** Stage-unit centre of a named square, as it is drawn for this seat. */
export function squarePoint(name: string, view: Orientation): Pt | null {
  const sq = parseSquare(name)
  if (!sq) return null
  const cell = toLattice(sq, view)
  return squareCenter(cell.file, cell.rank)
}

/** Which named square a stage point is over, or null if it is off the board. */
export function squareAt(p: Pt, view: Orientation): string | null {
  const cell = hitSquare(p)
  if (!cell) return null
  return squareName(fromLattice(cell, view))
}

/* ─────────────────────────────────────────────────────────── FEN */

const PIECE_OF: Record<string, PieceType> = {
  p: 'p',
  n: 'n',
  b: 'b',
  r: 'r',
  q: 'q',
  k: 'k',
}

/**
 * The men on the board, read out of the position the server sent.
 *
 * The FEN is the whole reason there is no piece bookkeeping anywhere in this
 * feature. Tracking pieces move by move on the client means holding a second
 * copy of the game and being wrong about castling, en passant and promotion in
 * three different ways; re-reading the position after every push means the
 * board on screen is the board on the server by construction.
 *
 * Only the first field is looked at. A malformed rank is skipped rather than
 * thrown on — half a board drawn beats a blank screen when the alternative is
 * a render that crashed.
 */
export function parseFen(fen: string): Placed[] {
  const placement = fen.split(' ')[0] ?? ''
  const out: Placed[] = []
  const rows = placement.split('/')
  for (let row = 0; row < rows.length && row < 8; row++) {
    // The first row of a FEN is the eighth rank, and the rank index counts the
    // other way, so the eighth rank is index 7.
    const rank = 7 - row
    let file = 0
    for (const ch of rows[row]) {
      if (ch >= '1' && ch <= '8') {
        file += ch.charCodeAt(0) - 48
        continue
      }
      const type = PIECE_OF[ch.toLowerCase()]
      if (!type || file > 7) continue
      out.push({
        square: squareName({ file, rank }),
        type,
        color: ch === ch.toUpperCase() ? 'white' : 'black',
      })
      file += 1
    }
  }
  return out
}

/**
 * What a side has left, counted the way a person counts it by looking.
 *
 * Used for one thing only: telling, from two positions, that somebody just
 * lost something worth losing. It is not an evaluation and must not become
 * one — the whole engine layer exists so that no number describing how the
 * game is going ever reaches the browser, and a client-side score would be a
 * hole straight through that.
 */
const VALUE: Record<PieceType, number> = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 }

export function material(fen: string, color: PieceColor): number {
  let total = 0
  for (const piece of parseFen(fen)) {
    if (piece.color === color) total += VALUE[piece.type]
  }
  return total
}

/**
 * Whether a move would land a pawn on the last rank, so the view knows to ask.
 *
 * This is the one piece of rules knowledge the client is allowed, and it is
 * not legality: it is knowing that a promotion needs a choice attached before
 * the move can even be phrased. Sending the move first and being asked
 * afterwards is not a thing the wire format can express.
 */
export function isPromotion(pieces: Placed[], from: string, to: string): boolean {
  const target = parseSquare(to)
  if (!target) return false
  const mover = pieces.find((p) => p.square === from)
  if (!mover || mover.type !== 'p') return false
  return mover.color === 'white' ? target.rank === 7 : target.rank === 0
}
