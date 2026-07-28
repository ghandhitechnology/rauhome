/**
 * The chess board, on the same table he plays cards at.
 *
 * The projection is **oblique**, and choosing that over the two obvious
 * alternatives is the decision the rest of this file falls out of. Top-down
 * is a diagram: correct, legible, and completely disconnected from the room
 * and the character sitting behind it. True perspective would need a vanishing
 * point, which the room does not have — every other surface here, the desk,
 * the rug, the table itself, is drawn as a flat band with a lit front edge,
 * and one correctly-projected object in the middle of that would look like it
 * had been pasted in from a different picture. Oblique is what the room is
 * already doing: squares stay parallelograms, each rank steps down the screen
 * and slightly left, and nothing converges.
 *
 * Which makes the geometry a 2×2 map — a square's centre is
 * `origin + file · fileVec + rank · rankVec` — and its inverse, the one the
 * DOM board needs to turn a click into a square, a two-by-two solve. The
 * numbers below are the only copy of that map, and they are tuned against
 * three things at once that none of them can be moved without breaking:
 *
 *   · the table is 40 units wide at x 72, so the board is 35 across and sits
 *     centred on it with about two and a half units of wood showing each side
 *   · the board is painted *over* him — the room draws the character and then
 *     the furniture — so the far rim is what decides how much of him you can
 *     see. It stops at 67.3, which leaves him visible from the eyes down to
 *     mid-body, and, more importantly, still visible when he folds: a slump
 *     drops his head to about 65.2, and a board a unit deeper would end the
 *     game by hiding the one reaction that matters
 *   · the near edge comes to 73, a little past the front of the slab, the
 *     same way the cards already overhang it
 *
 * What is left after those three is the depth, and it is not much: a square
 * is 3.45 across and 0.58 deep, close to six to one. That is the same order
 * of squash the rest of the room is drawn at — the worn felt under a card is
 * 5.1 by 0.9 — and it is the constraint the pieces have to be authored
 * against, because at this depth a piece of any height stands in front of
 * most of the board behind it.
 */

import type { TableGame } from './gameChoreographer'
import { drawTableCarcass, drawTableGlow, GAME_TABLE, TABLE_RISE } from './gameTableLayer'
import { mixHex, ROOM } from './palette'
import { contactShadow, STAGE } from './stage'
import type { Pt, Rect, TableSurface } from './tableSurface'

/**
 * The board's map from (file, rank) to stage units.
 *
 * `file` is 0 at the a-file and 7 at the h-file. `rank` is 0 at the **eighth**
 * rank and 7 at the first — it counts away from him and toward you, which is
 * the order things have to be drawn in, so it is the order the index runs in.
 */
export const CHESS_BOARD = {
  /** Stage-unit position of the centre of a8 — back-left from where you sit. */
  origin: { x: 62, y: 67.9 },
  /** One file to the next, a to h. */
  fileVec: { x: 3.45, y: 0 },
  /** One rank to the next, 8 toward 1 — down the screen and slightly left. */
  rankVec: { x: -0.55, y: 0.58 },
}

/**
 * The frame around the squares, in board units rather than stage units.
 *
 * Deeper at the near edge than anywhere else, because that is where the file
 * letters go and because a real board has a wider apron on the side you sit
 * at. Everything downstream measures from the playing area, so widening the
 * frame moves the board's footprint without touching a single square.
 */
const BORDER = { side: 0.32, back: 0.5, front: 1.2 }

/** How thick the near edge of the board reads, in stage units. */
const EDGE = 0.7

/**
 * Three woods, in order of value, and the order matters more than the hues.
 *
 * The board sits on a walnut table in a room where every wooden thing is some
 * shade of the same brown, so the danger is not that it looks wrong — it is
 * that it disappears. The frame is the darkest thing in the shot, the light
 * squares the lightest, and the dark squares land between them: whatever the
 * lamp is doing, the eight-by-eight grid stays the loudest edge on the table.
 * The pale one is mixed toward paper rather than picked, because nothing in
 * the room palette is boxwood and inventing a hex here would be one more
 * colour nobody else can match.
 */
const BOARD_WOOD = {
  frame: ROOM.woodDeep,
  frameLit: ROOM.walnutLit,
  light: mixHex(ROOM.woodLit, ROOM.paper, 0.45),
  dark: ROOM.walnut,
  /** The near edge's thickness, and the shadow line under it. */
  edge: '#241606',
  edgeLine: '#140B04',
}

const FILE_LETTERS = 'abcdefgh'

/**
 * The centre of a square, in stage units.
 *
 * The forward half of the transform. The inverse lives with the DOM board,
 * which is the only thing that ever needs to run it backwards.
 */
export function boardPoint(file: number, rank: number): Pt {
  const { origin, fileVec, rankVec } = CHESS_BOARD
  return {
    x: origin.x + file * fileVec.x + rank * rankVec.x,
    y: origin.y + file * fileVec.y + rank * rankVec.y,
  }
}

/**
 * A corner of the square lattice: `(0, 0)` is the far corner beyond a8, and
 * `(8, 8)` the near corner beyond h1. Half a square out from the centres, on
 * both axes, which is what makes the four outer values whole numbers.
 */
function lattice(fi: number, ri: number): Pt {
  return boardPoint(fi - 0.5, ri - 0.5)
}

/** The playing area's four outer corners, named for the square they belong to. */
export const BOARD_CORNERS = {
  a8: lattice(0, 0),
  h8: lattice(8, 0),
  a1: lattice(0, 8),
  h1: lattice(8, 8),
}

/** Smallest axis-aligned rect the 64 squares fit inside, in stage units. */
export const BOARD_BOX: Rect = (() => {
  const xs = Object.values(BOARD_CORNERS).map((p) => p.x)
  const ys = Object.values(BOARD_CORNERS).map((p) => p.y)
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y }
})()

/**
 * The over-the-board shot.
 *
 * A little tighter and a little higher than the card-table one. Kittens fills
 * the bottom third of the frame with the hand you are holding; chess has
 * nothing down there worth seeing, so the shot spends that room on the board
 * instead. `x` is still just how far the table is off centre — the camera
 * scales about the middle of the stage, and the board is centred on the table.
 */
export const CHESS_CAMERA = {
  x: GAME_TABLE.x - STAGE.w / 2,
  y: 23.5,
  zoom: 2.45,
  lambda: 2.4,
}

/** Chess dims a shade harder than cards: there is less to see off the board. */
export const CHESS_DIM = 0.66

type Ctx = CanvasRenderingContext2D

/** Fill a polygon given in stage units. */
function poly(ctx: Ctx, u: number, points: Pt[], fill: string) {
  ctx.fillStyle = fill
  ctx.beginPath()
  ctx.moveTo(points[0].x * u, points[0].y * u)
  for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x * u, points[i].y * u)
  ctx.closePath()
  ctx.fill()
}

/** Slide a point straight down the screen, for edges and thicknesses. */
function down(p: Pt, dy: number): Pt {
  return { x: p.x, y: p.y + dy }
}

function drawBoard(ctx: Ctx, u: number, presence: number, time: number) {
  const frameBackLeft = lattice(-BORDER.side, -BORDER.back)
  const frameBackRight = lattice(8 + BORDER.side, -BORDER.back)
  const frameFrontRight = lattice(8 + BORDER.side, 8 + BORDER.front)
  const frameFrontLeft = lattice(-BORDER.side, 8 + BORDER.front)

  // It is a heavy object resting on a table, and without this it is a
  // rectangle floating a centimetre above one.
  ctx.globalAlpha = 1
  contactShadow(
    ctx,
    u,
    BOARD_BOX.x + BOARD_BOX.w / 2,
    frameFrontLeft.y - 0.2,
    BOARD_BOX.w * 0.56,
    1.3,
    0.5 * presence,
  )

  ctx.globalAlpha = Math.min(1, presence)

  // The near edge first, so the frame lands on top of it and the two read as
  // one slab with a thickness rather than a board sitting on a plinth.
  poly(
    ctx,
    u,
    [
      frameFrontLeft,
      frameFrontRight,
      down(frameFrontRight, EDGE),
      down(frameFrontLeft, EDGE),
    ],
    BOARD_WOOD.edge,
  )
  poly(
    ctx,
    u,
    [
      down(frameFrontLeft, EDGE - 0.22),
      down(frameFrontRight, EDGE - 0.22),
      down(frameFrontRight, EDGE),
      down(frameFrontLeft, EDGE),
    ],
    BOARD_WOOD.edgeLine,
  )

  // The frame, then a lit rim along its far edge — the lamp is over the
  // table, so the light on a horizontal surface collects at the back.
  poly(ctx, u, [frameBackLeft, frameBackRight, frameFrontRight, frameFrontLeft], BOARD_WOOD.frame)
  poly(
    ctx,
    u,
    [
      frameBackLeft,
      frameBackRight,
      down(frameBackRight, 0.22),
      down(frameBackLeft, 0.22),
    ],
    BOARD_WOOD.frameLit,
  )

  // Back to front, rank 8 first. The squares tile exactly, so this is not
  // about overlap — it is so that anything drawn per rank on top of them,
  // now or later, inherits the same order the pieces are stacked in.
  for (let ri = 0; ri < 8; ri++) {
    for (let fi = 0; fi < 8; fi++) {
      // a1 is dark, which fixes the parity for the other sixty-three.
      const lightSquare = (fi + ri) % 2 === 0
      poly(
        ctx,
        u,
        [lattice(fi, ri), lattice(fi + 1, ri), lattice(fi + 1, ri + 1), lattice(fi, ri + 1)],
        lightSquare ? BOARD_WOOD.light : BOARD_WOOD.dark,
      )
    }
  }

  // A hairline of shadow where the squares meet the far frame, so the frame
  // reads as standing slightly proud of them.
  ctx.globalAlpha = 0.3 * presence
  poly(
    ctx,
    u,
    [lattice(0, 0), lattice(8, 0), down(lattice(8, 0), 0.16), down(lattice(0, 0), 0.16)],
    '#000000',
  )

  // The lamp, breathing over the squares at a rate you would not notice.
  ctx.globalAlpha = (0.055 + Math.sin(time * 0.5) * 0.008) * presence
  poly(
    ctx,
    u,
    [lattice(1, 0), lattice(7, 0), lattice(7, 6), lattice(1, 6)],
    ROOM.lamp,
  )

  // File letters along the near border. Nothing here ever labels the ranks:
  // the near edge is the one you read without turning your head, and eight
  // more characters up the side would be clutter on a board this shallow.
  ctx.globalAlpha = 0.55 * presence
  ctx.save()
  ctx.font = `${Math.max(6, Math.round(0.85 * u))}px "DM Sans", system-ui, sans-serif`
  ctx.fillStyle = ROOM.paperShade
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (let fi = 0; fi < 8; fi++) {
    const p = boardPoint(fi, 7.5 + BORDER.front / 2)
    ctx.fillText(FILE_LETTERS[fi], p.x * u, p.y * u)
  }
  ctx.restore()
}

/**
 * Draw the table with a board on it.
 *
 * Same carcass and the same arrival as the card table — it is the same piece
 * of furniture, and a second one that rose a fraction differently would be
 * noticed even by someone who could not say what they had noticed.
 */
export function drawChessTable(ctx: Ctx, u: number, presence: number, time: number) {
  if (presence <= 0.002) return

  ctx.save()
  ctx.globalAlpha = Math.min(1, presence)
  ctx.translate(0, (1 - presence) * TABLE_RISE * u)

  drawTableCarcass(ctx, u, presence)
  drawTableGlow(ctx, u, presence, time)
  drawBoard(ctx, u, presence, time)

  ctx.restore()
}

/** A named point, for a spot that is a position rather than an area. */
function at(p: Pt): Rect {
  return { x: p.x, y: p.y, w: 0, h: 0 }
}

export const CHESS_SURFACE: TableSurface = {
  id: 'chess',
  table: GAME_TABLE,
  camera: CHESS_CAMERA,
  dim: CHESS_DIM,
  /**
   * The four corners of the playing area and the box around them.
   *
   * The DOM board is positioned from these, which means it is positioned from
   * the same numbers the canvas paints with — the whole reason the geometry
   * lives in a layer module and not inside a draw call.
   */
  spots: {
    a8: at(BOARD_CORNERS.a8),
    h8: at(BOARD_CORNERS.h8),
    a1: at(BOARD_CORNERS.a1),
    h1: at(BOARD_CORNERS.h1),
    board: BOARD_BOX,
  },
  draw: drawChessTable,
}

/**
 * What each beat of a game does to his body.
 *
 * `hover` and `think` are terminal because they are postures he stays in, not
 * gestures he performs: the claw waits over a square, or the chin stays
 * propped, until the server says something has changed. Every other game in
 * this room only holds a pose at the very end.
 */
export const CHESS_GAME: TableGame = {
  surface: CHESS_SURFACE,
  verbClips: {
    hover: 'reachHover',
    pull: 'pullBack',
    think: 'chinRest',
    move: 'placePiece',
    capture: 'snatchCapture',
    check: 'leanCheck',
    blunder: 'slumpBlunder',
    cheer: 'sitCheer',
    /*
      Losing the game folds him the same way realising he has lost does, and
      deliberately not the way the card table does it. `slumpLoss` was authored
      for a table with cards lying flat on it; a board has pieces standing up on
      it, and its far rim sits at stage y 67.3 while a full slump takes his eyes
      to about 67.6 — so the reaction the whole beat exists to be watched for
      would play out behind the furniture. `slumpBlunder` holds a unit higher for
      exactly this reason, and its own docstring is where that is worked out.
    */
    slump: 'slumpBlunder',
  },
  interrupting: new Set(['blunder', 'cheer', 'slump']),
  terminal: new Set(['hover', 'think', 'blunder', 'cheer', 'slump']),
}
