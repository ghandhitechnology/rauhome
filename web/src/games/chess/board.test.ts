/**
 * The board's arithmetic, checked against itself.
 *
 * Every one of these is a claim the rest of the feature is built on top of and
 * cannot notice being wrong about. The projection is a sheared 2×2 map, so a
 * hit test that is off by one square does not look broken — it looks like the
 * board is fine and the mouse is haunted. The orientation flip is worse: play
 * black and every square keeps its name while changing its address, and the
 * only way that shows up is as a move sent for a square you did not click.
 *
 * So the round trips are the point. `squareCenter → hitSquare` for all
 * sixty-four, `squarePoint → squareAt` for all sixty-four in both seats, and
 * the FEN read back as the pieces it names. If those hold, everything above
 * them is placing rectangles.
 */
import { describe, expect, it } from 'vitest'

import { BOARD_BOX, BOARD_CORNERS, CHESS_BOARD } from '../../clawd/chessTableLayer'
import { GAME_TABLE } from '../../clawd/gameTableLayer'
import {
  fromLattice,
  hitSquare,
  isPromotion,
  material,
  parseFen,
  parseSquare,
  squareAt,
  squareCenter,
  squareName,
  squarePoint,
  toLattice,
  SQUARE_BOX,
  SQUARE_SHAPE,
  type Orientation,
} from './board'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const SEATS: Orientation[] = ['white', 'black']

/** Every lattice cell, in the order the board is painted in. */
const CELLS = Array.from({ length: 64 }, (_, i) => ({
  file: i % 8,
  rank: Math.floor(i / 8),
}))

describe('the projection', () => {
  it('is invertible at all', () => {
    // Parallel basis vectors would be a board squashed to a line, and every
    // hit test on it would divide by zero.
    const det =
      CHESS_BOARD.fileVec.x * CHESS_BOARD.rankVec.y -
      CHESS_BOARD.rankVec.x * CHESS_BOARD.fileVec.y
    expect(Math.abs(det)).toBeGreaterThan(0.5)
  })

  it('puts every cell back where it came from', () => {
    for (const cell of CELLS) {
      expect(hitSquare(squareCenter(cell.file, cell.rank))).toEqual(cell)
    }
  })

  it('keeps a cell all the way to its own corners', () => {
    // A click anywhere inside the parallelogram the canvas painted has to land
    // on the square it painted, not on the neighbour it overlaps the box of.
    // Just inside each corner, so the test is not asking about the boundary.
    const { fileVec, rankVec } = CHESS_BOARD
    for (const cell of CELLS) {
      const c = squareCenter(cell.file, cell.rank)
      for (const sf of [-0.45, 0.45]) {
        for (const sr of [-0.45, 0.45]) {
          const p = {
            x: c.x + sf * fileVec.x + sr * rankVec.x,
            y: c.y + sf * fileVec.y + sr * rankVec.y,
          }
          expect(hitSquare(p)).toEqual(cell)
        }
      }
    }
  })

  it('says nothing at all off the board', () => {
    const beyond = squareCenter(-1, -1)
    expect(hitSquare(beyond)).toBeNull()
    expect(hitSquare(squareCenter(8, 8))).toBeNull()
  })

  it('agrees with the corners the canvas frames the squares with', () => {
    // The four outer corners are half a square out from the outer centres, so
    // they are the same numbers read from the other end.
    const a8 = squareCenter(0, 0)
    expect(BOARD_CORNERS.a8.x).toBeCloseTo(
      a8.x - (CHESS_BOARD.fileVec.x + CHESS_BOARD.rankVec.x) / 2,
      6,
    )
    expect(BOARD_CORNERS.a8.y).toBeCloseTo(
      a8.y - (CHESS_BOARD.fileVec.y + CHESS_BOARD.rankVec.y) / 2,
      6,
    )
    expect(BOARD_BOX.w).toBeCloseTo(BOARD_CORNERS.h8.x - BOARD_CORNERS.a1.x, 6)
  })
})

describe('the board on the table', () => {
  it('stands centred on the table it is laid on', () => {
    // The middle of the eight-by-eight, which is the corner between d4 and e5.
    const middle = squareCenter(3.5, 3.5)
    expect(middle.x).toBeCloseTo(GAME_TABLE.x, 0)
  })

  it('keeps every square over the wood', () => {
    // The board is a parallelogram and the table is not, so the far edge sits
    // further right than the near one — but no part of either may hang off.
    const left = GAME_TABLE.x - GAME_TABLE.w / 2
    const right = GAME_TABLE.x + GAME_TABLE.w / 2
    for (const corner of Object.values(BOARD_CORNERS)) {
      expect(corner.x).toBeGreaterThan(left)
      expect(corner.x).toBeLessThan(right)
    }
  })

  it('stops short of his face at the back and past the slab at the front', () => {
    // Both are composition, not arithmetic, and both are the reason the squares
    // are as shallow as they are: the far rim has to leave his head visible,
    // and the near edge has to overhang the table the way the cards do.
    expect(BOARD_CORNERS.a8.y).toBeGreaterThan(66)
    expect(BOARD_CORNERS.a8.y).toBeLessThan(GAME_TABLE.topY)
    expect(BOARD_CORNERS.a1.y).toBeGreaterThan(GAME_TABLE.topY)
  })

  it('gives the marks a box the square actually fits in', () => {
    expect(SQUARE_BOX.w).toBeCloseTo(
      Math.abs(CHESS_BOARD.fileVec.x) + Math.abs(CHESS_BOARD.rankVec.x),
      6,
    )
    for (const corner of SQUARE_SHAPE) {
      expect(corner.x).toBeGreaterThanOrEqual(0)
      expect(corner.x).toBeLessThanOrEqual(1)
      expect(corner.y).toBeGreaterThanOrEqual(0)
      expect(corner.y).toBeLessThanOrEqual(1)
    }
  })
})

describe('names', () => {
  it('round-trips every square', () => {
    for (let file = 0; file < 8; file++) {
      for (let rank = 0; rank < 8; rank++) {
        const name = squareName({ file, rank })
        expect(parseSquare(name)).toEqual({ file, rank })
      }
    }
  })

  it('knows the two ends of the board by name', () => {
    expect(squareName({ file: 4, rank: 3 })).toBe('e4')
    expect(parseSquare('a1')).toEqual({ file: 0, rank: 0 })
    expect(parseSquare('h8')).toEqual({ file: 7, rank: 7 })
  })

  it('refuses squares that are not on it', () => {
    expect(parseSquare('e9')).toBeNull()
    expect(parseSquare('j4')).toBeNull()
    expect(parseSquare('e')).toBeNull()
    expect(squareName({ file: 8, rank: 0 })).toBe('')
  })
})

describe('which way round it is', () => {
  it('puts your own first rank nearest, whichever colour you are', () => {
    // Row 7 is the near one. White's back rank is the first, black's the eighth.
    expect(toLattice({ file: 0, rank: 0 }, 'white')).toEqual({ file: 0, rank: 7 })
    expect(toLattice({ file: 0, rank: 7 }, 'black')).toEqual({ file: 7, rank: 7 })
  })

  it('is its own inverse in both seats', () => {
    for (const view of SEATS) {
      for (const cell of CELLS) {
        expect(toLattice(fromLattice(cell, view), view)).toEqual(cell)
      }
    }
  })

  it('points back at the square it drew, in both seats', () => {
    for (const view of SEATS) {
      for (const cell of CELLS) {
        const name = squareName(fromLattice(cell, view))
        const p = squarePoint(name, view)
        expect(p).not.toBeNull()
        if (p) expect(squareAt(p, view)).toBe(name)
      }
    }
  })

  it('has no square under a point beyond the frame', () => {
    expect(squareAt({ x: 0, y: 0 }, 'white')).toBeNull()
    expect(squarePoint('e9', 'white')).toBeNull()
  })
})

describe('reading a position', () => {
  it('finds thirty-two men in the starting one', () => {
    const pieces = parseFen(START)
    expect(pieces).toHaveLength(32)
    expect(pieces.filter((p) => p.color === 'white')).toHaveLength(16)
  })

  it('puts the right men on the right squares', () => {
    const at = new Map(parseFen(START).map((p) => [p.square, p]))
    expect(at.get('e1')).toEqual({ square: 'e1', type: 'k', color: 'white' })
    expect(at.get('d8')).toEqual({ square: 'd8', type: 'q', color: 'black' })
    expect(at.get('a2')).toEqual({ square: 'a2', type: 'p', color: 'white' })
    expect(at.get('e4')).toBeUndefined()
  })

  it('counts the runs of empty squares', () => {
    const pieces = parseFen('4k3/8/8/8/8/8/8/4K3 w - - 0 1')
    expect(pieces.map((p) => p.square).sort()).toEqual(['e1', 'e8'])
  })

  it('survives a FEN it cannot read', () => {
    // Half a board beats a render that threw, so a malformed placement comes
    // back as whatever of it made sense — never as an exception, and never as
    // more men than there are squares.
    expect(parseFen('')).toEqual([])
    expect(parseFen('nonsense').length).toBeLessThanOrEqual(64)
    expect(parseFen('8/8/8/8/8/8/8/8/8/8/8 w - - 0 1').length).toBe(0)
  })

  it('counts material the way a person does, kings excluded', () => {
    expect(material(START, 'white')).toBe(39)
    expect(material(START, 'black')).toBe(39)
    expect(material('4k3/8/8/8/8/8/8/4K3 w - - 0 1', 'white')).toBe(0)
  })
})

describe('a pawn getting to the end', () => {
  const pieces = parseFen('8/P6p/8/8/8/8/8/4K2k w - - 0 1')

  it('knows a pawn is about to become something', () => {
    expect(isPromotion(pieces, 'a7', 'a8')).toBe(true)
    expect(isPromotion(pieces, 'h7', 'h6')).toBe(false)
  })

  it('sends the black pawns to the other end', () => {
    const black = parseFen('8/8/8/8/8/8/7p/4K2k b - - 0 1')
    expect(isPromotion(black, 'h2', 'h1')).toBe(true)
    expect(isPromotion(black, 'h2', 'h8')).toBe(false)
  })

  it('says no about anything that is not a pawn, and about nothing at all', () => {
    expect(isPromotion(pieces, 'e1', 'e8')).toBe(false)
    expect(isPromotion(pieces, 'd4', 'd8')).toBe(false)
  })
})
