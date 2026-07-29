/**
 * The board, in the room.
 *
 * Two layers, and which one a thing belongs to is the only structural decision
 * in here — the same split the card table is built on:
 *
 *   `.ch-world`   camera-locked. The squares, the marks on them, and the men
 *                 standing on top. Authored in *stage units* — the room's own
 *                 coordinates — and carried onto the screen by a single CSS
 *                 matrix that `gameBridge` rewrites once a frame. These things
 *                 are on the table he is sitting behind.
 *
 *   `.ch-screen`  screen-locked. The promotion picker, resign and draw, the
 *                 line he just said. These are in your hands, and your hands
 *                 do not move when the camera does.
 *
 * Three things about the world layer are worth knowing before editing it.
 *
 * The squares are parallelograms, because the projection is oblique, and the
 * DOM can only lay out rectangles. So each one is its bounding box cut to shape
 * with a `clip-path` whose corners `board.ts` derives from the same two basis
 * vectors the canvas paints with. Nothing here has a hand-typed coordinate.
 *
 * Pointing at a sheared square is done with arithmetic rather than with hit
 * boxes. The bounding boxes overlap their neighbours by a seventh of their
 * width, so a click is resolved by inverting the projection — pixels to stage
 * units to a file and a rank — which is exact everywhere including the corners
 * clip-path support disagrees about. The sixty-four buttons underneath are
 * therefore not the mouse's target at all; they are the keyboard's and the
 * screen reader's, which is why they carry the labels and take no pointer
 * events.
 *
 * And the men are sorted back to front. A piece two ranks away is drawn at
 * nearly the same height as one in front of it — the board is six times wider
 * than it is deep — so paint order is the only depth cue there is.
 *
 * There is no game logic here, and in particular there are no move hints: no
 * dots, no glow, no legal-destination highlight. You pick a piece up and you
 * put it somewhere, and the server tells you whether that was a move. The two
 * marks the board does carry — the last move and a king in check — are things
 * that already happened rather than things you might do.
 */
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { BOARD_BOX } from '../../clawd/chessTableLayer'
import { gameBridge, type Pt } from '../../clawd/gameBridge'
import {
  ChessPiece,
  PieceDefs,
  PIECE_ANCHOR,
  PIECE_BASE,
  PIECE_HEIGHT,
  VIEW,
  type Finish,
} from './art'
import { diffBeats } from './beats'
import {
  fromLattice,
  parseFen,
  squareAt,
  squareCenter,
  squareName,
  toLattice,
  isPromotion,
  parseSquare,
  SQUARE_BOX,
  SQUARE_SHAPE,
  type Cell,
  type Orientation,
  type PieceColor,
  type Placed,
} from './board'
import { pieceName, PROMOTION_CHOICES, resultLine, squareLabel } from './meta'
import { useLocale } from '../../i18n'
import {
  gameStore,
  phaseStore,
  useGame,
  usePhase,
  type Move,
  type Promotion,
  type TableState,
} from './useGame'
import './Chess.css'

/**
 * A square's outline, as a clip path.
 *
 * Built once at module load from the projection's basis vectors, so the marks
 * on the board are the same parallelogram the canvas painted underneath them
 * even if the geometry is retuned.
 */
const SQUARE_CLIP = `polygon(${SQUARE_SHAPE.map(
  (p) => `${(p.x * 100).toFixed(3)}% ${(p.y * 100).toFixed(3)}%`,
).join(', ')})`

/**
 * How tall the king stands, in stage units, and therefore how tall everything
 * else does.
 *
 * This is the one number in the file worth arguing about, and it is not set by
 * chess. A real king is about one and two thirds of a square, which here would
 * be five and three quarter units — and a man that tall on the eighth rank
 * reaches up past 62, which is the top of Rau's head. The board is deliberately
 * painted no deeper than his eyes so that you can watch him lose; a set of
 * pieces that put itself in front of his face afterwards would undo that in
 * the one position they all start from.
 *
 * So the set is scaled to the room instead of to the ruler. At this height the
 * tallest thing on the back rank tops out level with where his head drops to
 * when he slumps, and the pieces read as a small travel set on a big board —
 * which is a look, and is the price of being able to see him.
 */
const KING_HEIGHT = 2.7

/** Stage units per author unit. Everything below is a consequence of this. */
const PIECE_SCALE = KING_HEIGHT / PIECE_HEIGHT.k

/**
 * The box a man is drawn in — the whole authoring viewBox, scaled.
 *
 * Every piece gets the *same* box, which is the point: they share one viewBox
 * and stand at the same line inside it, so a king comes out taller than a
 * queen without anybody here knowing which is which. Sizing each box to its
 * own piece's height would flatten all six to the same height and throw away
 * the proportions the set is built on.
 */
const PIECE_BOX = { w: VIEW.w * PIECE_SCALE, h: VIEW.h * PIECE_SCALE }

/** How far below the top of that box the piece's contact line falls. */
const PIECE_BASELINE = PIECE_ANCHOR.y * PIECE_SCALE

/**
 * How far in front of the square's centre the contact line sits.
 *
 * The art measures a base from the *front* of its disc rather than from its
 * axis, so a piece anchored dead on the square's centre has its whole footprint
 * in the far half of the square. Nudging it forward by about half a base's
 * depth puts the disc back where a disc lying on that square would be.
 */
const FOOT = SQUARE_BOX.h * 0.14

/** Which wood a side is cut from. Pale for white, dark for black. */
const FINISH: Record<PieceColor, Finish> = { white: 'maple', black: 'walnut' }

/**
 * The area the mouse is listened to over: the board, plus room for the men.
 *
 * A piece stands two and a half units clear of the square it is on, so the
 * board's own footprint stops well short of the top of a king on the eighth
 * rank — and clicking the piece you are trying to move is the first thing
 * anybody does. Grown upward by exactly one king, and no further: everything
 * above that line is Rau, and he is still there to be poked at during a game.
 */
const HIT_RISE = KING_HEIGHT - FOOT

/**
 * Place a box in the world layer, centred on a stage-unit point.
 *
 * The numbers are stage units and the property is `px`, which looks wrong
 * until you remember the layer is scaled by the camera matrix: one "pixel"
 * here is one unit of the room.
 */
function boxAt(center: Pt, w: number, h: number): CSSProperties {
  return {
    left: `${center.x - w / 2}px`,
    top: `${center.y - h / 2}px`,
    width: `${w}px`,
    height: `${h}px`,
  }
}

/** Where a man stands: centred on his square, and standing *on* it. */
function manAt(center: Pt): CSSProperties {
  return {
    left: `${center.x - PIECE_BOX.w / 2}px`,
    top: `${center.y + FOOT - PIECE_BASELINE}px`,
    width: `${PIECE_BOX.w}px`,
    height: `${PIECE_BOX.h}px`,
  }
}

/* ───────────────────────────────────────────────────────── the world */

/**
 * The two squares of the last move, and the king that is in check.
 *
 * The only two marks on the board, and both are past tense. A last-move mark
 * is what a real board gives you for free — you watched the piece land — and
 * without it a position that arrived while you were reading his line is a
 * puzzle. The check pulse is the one thing the rules oblige you to notice.
 */
function Marks({ table, view }: { table: TableState; view: Orientation }) {
  const marks: { key: string; square: string; kind: string }[] = []
  if (table.last_move) {
    marks.push({ key: 'from', square: table.last_move.from, kind: 'is-from' })
    marks.push({ key: 'to', square: table.last_move.to, kind: 'is-to' })
  }
  if (table.check_square) {
    marks.push({ key: 'check', square: table.check_square, kind: 'is-check' })
  }
  return (
    <>
      {marks.map((mark) => {
        const sq = parseSquare(mark.square)
        if (!sq) return null
        const cell = toLattice(sq, view)
        return (
          <div
            key={mark.key}
            className={`ch-mark ${mark.kind}`}
            style={{
              ...boxAt(squareCenter(cell.file, cell.rank), SQUARE_BOX.w, SQUARE_BOX.h),
              clipPath: SQUARE_CLIP,
            }}
            aria-hidden
          />
        )
      })}
    </>
  )
}

/* ──────────────────────────────────────────────────────── the screen */

/**
 * The choice a pawn on the last rank has to make before it is even a move.
 *
 * In the screen layer rather than over the square, and not because it is
 * easier: the four carved men are the size of a card here, and the same four
 * shrunk onto a square half a unit deep would be a row of smudges. It is also
 * the one moment in the game where you are being asked something rather than
 * told something, and those live in your hands.
 */
function PromotionPicker({
  color,
  busy,
  onPick,
  onCancel,
}: {
  color: Orientation
  busy: boolean
  onPick: (piece: Promotion) => void
  onCancel: () => void
}) {
  const { t } = useLocale()
  return (
    <div className="ch-promote" role="group" aria-label={t('chess.promoteLabel')}>
      <h3>{t('chess.promoteTitle')}</h3>
      <div className="ch-promote-row">
        {PROMOTION_CHOICES.map((type) => (
          <button
            key={type}
            type="button"
            className="ch-promote-pick"
            disabled={busy}
            onClick={() => onPick(type)}
            aria-label={pieceName(type)}
            title={pieceName(type)}
          >
            <ChessPiece type={type} finish={FINISH[color]} />
            <span>{pieceName(type)}</span>
          </button>
        ))}
      </div>
      <button type="button" className="ch-quiet" onClick={onCancel}>
        {t('chess.putBack')}
      </button>
    </div>
  )
}

/**
 * Resign, and the draw, which is a conversation rather than a button.
 *
 * A draw offer can be his or yours, and the difference is the whole control:
 * yours is a thing you are waiting on, his is a question with two answers.
 * Both states are shown, because an offer that vanished into the log would
 * leave you wondering whether it had been heard.
 */
function Controls({
  table,
  busy,
  onMove,
}: {
  table: TableState
  busy: boolean
  onMove: (move: Move) => void
}) {
  const { t } = useLocale()
  if (table.phase === 'over') return null
  const theirs = table.offer && table.offer.by === 'rau'
  const yours = table.offer && table.offer.by === 'user'

  return (
    <div className="ch-controls" role="group" aria-label={t('chess.controlsLabel')}>
      {theirs ? (
        <>
          <span className="ch-offer">{t('chess.offering')}</span>
          <button
            type="button"
            className="ch-btn ch-btn-primary"
            disabled={busy}
            onClick={() => onMove({ move: 'accept_draw' })}
          >
            {t('chess.takeIt')}
          </button>
          <button
            type="button"
            className="ch-btn"
            disabled={busy}
            onClick={() => onMove({ move: 'decline_draw' })}
          >
            {t('chess.playOn')}
          </button>
        </>
      ) : (
        <>
          {yours && <span className="ch-offer is-waiting">{t('chess.drawOffered')}</span>}
          {!yours && (
            <button
              type="button"
              className="ch-btn"
              disabled={busy}
              onClick={() => onMove({ move: 'offer_draw' })}
            >
              {t('chess.offerDraw')}
            </button>
          )}
          {table.can_claim_draw && (
            <button
              type="button"
              className="ch-btn"
              disabled={busy}
              onClick={() => onMove({ move: 'claim_draw' })}
              title={t('chess.claimHint')}
            >
              {t('chess.claimDraw')}
            </button>
          )}
          <button
            type="button"
            className="ch-btn"
            disabled={busy}
            onClick={() => onMove({ move: 'resign' })}
          >
            {t('chess.resign')}
          </button>
        </>
      )}
    </div>
  )
}

function GameOverScene({
  table,
  onAgain,
  onLeave,
}: {
  table: TableState
  onAgain: () => void
  onLeave: () => void
}) {
  const { t } = useLocale()
  const { title, note } = resultLine(table)
  const drawn = table.winner === null
  return (
    <div
      className={`ch-over ${drawn ? 'is-draw' : table.winner === 'user' ? 'is-win' : 'is-loss'}`}
      role="alertdialog"
      aria-label={t('chess.gameOver')}
    >
      <div className="ch-over-card">
        <h2>{title}</h2>
        <p>{note}</p>
        {table.result && <p className="ch-over-score">{table.result}</p>}
        <div className="ch-over-actions">
          <button type="button" className="ch-btn ch-btn-primary" onClick={onAgain}>
            {t('chess.again')}
          </button>
          <button type="button" className="ch-btn ch-btn-quiet" onClick={onLeave}>
            {t('chess.leaveBoard')}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ───────────────────────────────────────────────────────────── board */

export default memo(function ChessTable() {
  const { t } = useLocale()
  const { table, busy, error } = useGame()
  const phase = usePhase()

  /** The square you have picked a man up from, if any. */
  const [from, setFrom] = useState<string | null>(null)
  /** A move that cannot be sent until you say what the pawn becomes. */
  const [promoting, setPromoting] = useState<{ from: string; to: string } | null>(null)
  /**
   * The square that just refused a move, and a counter to replay the shake
   * with.
   *
   * Two illegal attempts from the same square are two shakes, and a CSS
   * animation only restarts on an element the browser considers new — so the
   * counter goes in the man's React key. Nothing clears this on a timer: the
   * animation ends on its own, and holding the value until the position
   * changes means the second attempt has something to differ from.
   */
  const [refused, setRefused] = useState<{ square: string; nonce: number } | null>(null)
  /** Which square the pointer is over, for the outline that follows it. */
  const [hover, setHover] = useState<string | null>(null)
  /** The keyboard's position on the board, kept apart from the pointer's. */
  const [cursor, setCursor] = useState('e2')

  const prevTable = useRef<TableState | null>(null)
  const squareEls = useRef(new Map<string, HTMLButtonElement>())
  /** Set when the cursor moved by key, so focus follows it and not the mouse. */
  const chaseCursor = useRef(false)
  const refuseCount = useRef(0)

  const worldRef = useRef<HTMLDivElement | null>(null)
  const attachWorld = useCallback((el: HTMLDivElement | null) => {
    worldRef.current = el
    gameBridge.attachWorld(el)
  }, [])

  /*
    Claim the world layer again on every render.

    There is one bridge and two tables, and when he clears one game to start
    the other the new table mounts before the old one has finished standing
    up — so the old table's cleanup runs last and detaches a layer that is no
    longer its own. The board would then sit wherever the camera was when that
    happened. Reclaiming it costs a field write and one forced transform, which
    is less than the render it is riding on.
  */
  /**
   * The element we handed the bridge, kept where React cannot null it.
   *
   * The cleanup below has to name what it is giving back, and by the time it
   * runs `worldRef` may already have been cleared — so the answer is recorded
   * on the way in rather than looked up on the way out.
   */
  const ownedWorld = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (worldRef.current) {
      ownedWorld.current = worldRef.current
      gameBridge.attachWorld(worldRef.current)
    }
  })

  // Leaving the room must not leave him staring at a square that is gone — and
  // must not take the layer out from under the card table if this is a handoff
  // rather than a departure. `releaseWorld` is a no-op once the cards own it.
  useEffect(
    () => () => {
      gameBridge.hoverPoint = null
      gameBridge.releaseWorld(ownedWorld.current)
    },
    [],
  )

  const view: Orientation = table?.user_color ?? 'white'
  /* The position, as a string, so everything derived from it is keyed on the
     one value the server actually changed rather than on the object it
     arrived in — a push that only moved his hover must not rebuild the men. */
  const fen = table?.fen ?? ''
  const pieces = useMemo(() => parseFen(fen), [fen])
  const bySquare = useMemo(() => {
    const map = new Map<string, Placed>()
    for (const piece of pieces) map.set(piece.square, piece)
    return map
  }, [pieces])

  /**
   * The men, back to front.
   *
   * Sorted by drawn row rather than by rank, so the order flips with the board
   * when you are playing black. Ties broken by column only to keep the list
   * stable — two men on the same rank never overlap.
   */
  const ordered = useMemo(() => {
    const withCell = pieces.map((piece) => {
      const sq = parseSquare(piece.square)
      const cell: Cell = sq ? toLattice(sq, view) : { file: 0, rank: 0 }
      return { piece, cell }
    })
    withCell.sort((a, b) => a.cell.rank - b.cell.rank || a.cell.file - b.cell.file)
    return withCell
  }, [pieces, view])

  /* ── his body ───────────────────────────────────────────────────── */

  useEffect(() => {
    if (!table) return
    const prev = prevTable.current
    prevTable.current = table
    if (phase !== 'playing' || !prev || prev.game_id !== table.game_id) return
    const beats = diffBeats(prev, table)
    if (beats.length > 0) gameBridge.choreography?.observe(beats)
  }, [table, phase])

  // A position that changed under a selection makes the selection meaningless:
  // the man you picked up may not be there any more.
  useEffect(() => {
    setFrom(null)
    setPromoting(null)
    setRefused(null)
  }, [fen])

  /* ── moves ──────────────────────────────────────────────────────── */

  const send = useCallback(async (move: Move) => {
    const origin = move.move === 'move' ? move.from : null
    const ok = await gameStore.play(move)
    setFrom(null)
    setPromoting(null)
    if (!ok && origin) {
      refuseCount.current += 1
      setRefused({ square: origin, nonce: refuseCount.current })
    }
  }, [])

  const interactive =
    !!table && phase === 'playing' && table.phase === 'playing' && table.your_turn && !busy

  /**
   * One click on one square.
   *
   * Click-click rather than drag: a piece dragged across a board this shallow
   * spends the whole gesture covering the squares it is travelling over, and
   * the board is only half a unit deep per rank, so it never looks like it is
   * moving *along* anything. Picking up and putting down is also the gesture
   * that survives a touch screen without a second code path.
   */
  const touch = useCallback(
    (square: string) => {
      if (!table || !interactive || promoting) return
      const here = bySquare.get(square)
      const mine = here && here.color === table.user_color

      if (!from) {
        // His men and empty squares do nothing. Not a rule the client is
        // enforcing — it is that there is no gesture that starts there.
        if (mine) setFrom(square)
        return
      }
      if (square === from) {
        setFrom(null)
        return
      }
      if (mine) {
        setFrom(square)
        return
      }
      if (isPromotion(pieces, from, square)) {
        setPromoting({ from, to: square })
        return
      }
      void send({ move: 'move', from, to: square, promotion: null })
    },
    [table, interactive, promoting, bySquare, from, pieces, send],
  )

  /* ── pointing at a sheared square ───────────────────────────────── */

  /**
   * What is under the pointer, as a square name.
   *
   * Two passes, and the order is the whole of it. A man standing on a square
   * is nowhere near it on screen — he is two ranks up the board — so pointing
   * at the piece you mean to move would otherwise select whatever empty square
   * happens to be behind his head. The men are tested first, front to back,
   * which is the order they are painted in and therefore the order in which
   * one of them is the one you can actually see. Only if the pointer is on
   * none of them does the projection get inverted for the square itself.
   *
   * Each man is tested against a box the width of his base and the height of
   * his own carving rather than of the shared viewBox — a pawn claiming a
   * king's worth of air above his head would make the two squares behind him
   * unclickable for no reason a player could see.
   */
  const squareUnder = useCallback(
    (x: number, y: number): string | null => {
      const p = gameBridge.toStage({ x, y })
      for (let i = ordered.length - 1; i >= 0; i--) {
        const { piece, cell } = ordered[i]
        const c = squareCenter(cell.file, cell.rank)
        const w = PIECE_BASE[piece.type] * 2 * PIECE_SCALE * 1.15
        const h = PIECE_HEIGHT[piece.type] * PIECE_SCALE
        const foot = c.y + FOOT
        if (p.x >= c.x - w / 2 && p.x <= c.x + w / 2 && p.y >= foot - h && p.y <= foot) {
          return piece.square
        }
      }
      return squareAt(p, view)
    },
    [ordered, view],
  )

  const onBoardMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      // Only while the move is yours. A square lighting up under the cursor
      // during his think would read as the board answering you, and it is not
      // answering anybody until he has put a piece down.
      const square = interactive ? squareUnder(e.clientX, e.clientY) : null
      // Only on a change: this runs on every pointer move, and re-rendering
      // sixty-four squares because the cursor travelled four pixels inside the
      // one it was already in is sixty renders a second for nothing.
      setHover((was) => (was === square ? was : square))
      gameBridge.hoverPoint = square ? { x: e.clientX, y: e.clientY } : null
    },
    [interactive, squareUnder],
  )

  const onBoardLeave = useCallback(() => {
    setHover(null)
    gameBridge.hoverPoint = null
  }, [])

  const onBoardDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      const square = squareUnder(e.clientX, e.clientY)
      if (!square) return
      e.preventDefault()
      setCursor(square)
      touch(square)
    },
    [squareUnder, touch],
  )

  /* ── the same board, by keyboard ────────────────────────────────── */

  const onGridKey = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      const step: Record<string, [number, number]> = {
        ArrowLeft: [-1, 0],
        ArrowRight: [1, 0],
        ArrowUp: [0, -1],
        ArrowDown: [0, 1],
      }
      const move = step[e.key]
      if (!move) return
      const sq = parseSquare(cursor)
      if (!sq) return
      const cell = toLattice(sq, view)
      const next: Cell = {
        file: Math.min(7, Math.max(0, cell.file + move[0])),
        rank: Math.min(7, Math.max(0, cell.rank + move[1])),
      }
      e.preventDefault()
      chaseCursor.current = true
      setCursor(squareName(fromLattice(next, view)))
    },
    [cursor, view],
  )

  // Moving the cursor with a key has to move the focus with it, or the next
  // arrow press goes to whichever button the browser still thinks is current.
  useEffect(() => {
    if (!chaseCursor.current) return
    chaseCursor.current = false
    squareEls.current.get(cursor)?.focus()
  }, [cursor])

  if (!table) return null

  const considering = table.phase === 'thinking' ? (table.thinking?.hover ?? null) : null
  const lastLine = table.log[table.log.length - 1]
  const waiting = !table.your_turn && table.phase !== 'over'

  return (
    <div className="ch-room" role="region" aria-label={t('chess.region')}>
      <PieceDefs />

      {/* ── on the table ─────────────────────────────────────────── */}
      <div className="ch-world" ref={attachWorld}>
        <Marks table={table} view={view} />

        {/*
          The keyboard's board, and the screen reader's. One tab stop, arrow
          keys inside it: sixty-four consecutive tab stops between the top of
          the page and whatever is after them would be a worse thing to have
          built than no keyboard support at all.
        */}
        <div
          className="ch-squares"
          role="group"
          aria-label={t('chess.boardLabel', { color: t(`piece.${table.user_color}`) })}
          onKeyDown={onGridKey}
        >
          {Array.from({ length: 64 }, (_, i) => {
            const cell: Cell = { file: i % 8, rank: Math.floor(i / 8) }
            const square = squareName(fromLattice(cell, view))
            const selected = from === square
            return (
              <button
                key={square}
                type="button"
                ref={(el) => {
                  if (el) squareEls.current.set(square, el)
                  else squareEls.current.delete(square)
                }}
                className={`ch-square ${selected ? 'is-picked' : ''} ${
                  hover === square ? 'is-under' : ''
                }`}
                style={{
                  ...boxAt(squareCenter(cell.file, cell.rank), SQUARE_BOX.w, SQUARE_BOX.h),
                  clipPath: SQUARE_CLIP,
                }}
                tabIndex={cursor === square ? 0 : -1}
                aria-label={squareLabel(square, bySquare.get(square))}
                aria-pressed={selected}
                onClick={() => touch(square)}
                onFocus={() => setCursor(square)}
              />
            )
          })}
        </div>

        <div className="ch-men">
          {ordered.map(({ piece, cell }) => {
            const lifted = from === piece.square
            const shaking = refused?.square === piece.square
            return (
              <div
                /*
                  Keyed on who is standing there, not just on where. A capture
                  leaves the same square occupied by a different man, and a key
                  that only named the square would have React swap the drawing
                  inside an element it considered unchanged — so the piece that
                  took the square would arrive without ever having landed.
                */
                key={`${piece.square}-${piece.color[0]}${piece.type}-${
                  shaking && refused ? refused.nonce : 0
                }`}
                className={`ch-man ${lifted ? 'is-lifted' : ''} ${
                  shaking ? 'is-refused' : ''
                } ${considering === piece.square ? 'is-considered' : ''} ${
                  table.last_move?.to === piece.square ? 'is-landed' : ''
                }`}
                style={manAt(squareCenter(cell.file, cell.rank))}
                aria-hidden
              >
                <ChessPiece type={piece.type} finish={FINISH[piece.color]} />
              </div>
            )
          })}
        </div>

        {/*
          The mouse's board: one surface over the playing area and the men
          standing on it, resolving a click by geometry rather than by asking
          which overlapping bounding box the pointer happened to land in.
        */}
        <div
          className={`ch-hit ${interactive ? 'is-live' : ''}`}
          style={{
            left: `${BOARD_BOX.x}px`,
            top: `${BOARD_BOX.y - HIT_RISE}px`,
            width: `${BOARD_BOX.w}px`,
            height: `${BOARD_BOX.h + HIT_RISE}px`,
          }}
          onPointerDown={onBoardDown}
          onPointerMove={onBoardMove}
          onPointerLeave={onBoardLeave}
          aria-hidden
        />
      </div>

      {/* ── in your hands ────────────────────────────────────────── */}
      <div className="ch-screen">
        <div className="ch-strip">
          <span className={`ch-turn ${waiting ? 'is-his' : ''}`}>
            {table.phase === 'over'
              ? t('chess.gameOver')
              : table.your_turn
                ? t('chess.yourMove')
                : table.phase === 'thinking'
                  ? t('chess.thinking')
                  : t('chess.rauToMove')}
          </span>
          {table.check_square && table.phase !== 'over' && (
            <span className="ch-alarm">{t('chess.check')}</span>
          )}
          {lastLine && <span className="ch-log">{lastLine.text}</span>}
          <button
            type="button"
            className="ch-quiet ch-leave"
            onClick={() => void phaseStore.leave()}
          >
            {t('chess.leave')}
          </button>
        </div>

        <Controls table={table} busy={busy} onMove={(move) => void send(move)} />

        {error && (
          <p className="ch-error" role="alert" onClick={() => gameStore.clearError()}>
            {error}
          </p>
        )}

        {promoting && (
          <PromotionPicker
            color={table.user_color}
            busy={busy}
            onPick={(piece) =>
              void send({
                move: 'move',
                from: promoting.from,
                to: promoting.to,
                promotion: piece,
              })
            }
            onCancel={() => setPromoting(null)}
          />
        )}

        {table.phase === 'over' && (
          <GameOverScene
            table={table}
            onAgain={() => void phaseStore.again()}
            onLeave={() =>
              void phaseStore.leave(
                table.winner === 'user' ? 'win' : table.winner === 'rau' ? 'loss' : null,
              )
            }
          />
        )}
      </div>
    </div>
  )
})
