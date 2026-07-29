/**
 * The table, in the room.
 *
 * Two layers, and which one a thing belongs to is the only structural
 * decision in here:
 *
 *   `.ek-world`   camera-locked. The deck, the discard, the cards in his
 *                 claws. Authored in *stage units* — the same coordinates the
 *                 canvas draws the room in — and carried onto the screen by a
 *                 single CSS matrix that `gameBridge` rewrites once a frame.
 *                 These things are in the room.
 *
 *   `.ek-screen`  screen-locked. The hand you are holding, the card you have
 *                 raised to read, the countdown. These are in your hands, and
 *                 your hands do not move when the camera does.
 *
 * There is still no game logic here. The server decides what is legal; the
 * raised card only reads back flags it was handed, and the one thing computed
 * locally is the Nope countdown, from the deadline in the payload.
 */
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { gameBridge, type Pt } from '../../clawd/gameBridge'
import { GAME_CARD, GAME_TABLE, KNOWN_TOP_SPOT } from '../../clawd/gameTableLayer'
import { CARD_ART, CardBack, CardDefs, CardFrame, type CardId } from './art'
import { diffBeats } from './beats'
import {
  arrivedSlots,
  diffFlights,
  reducedMotion,
  runFlight,
  DEAL_STAGGER_MS,
  type FlightSpot,
} from './flights'
import {
  handLocked,
  handReducer,
  IDLE_HAND,
  raisedIndices,
  type HandEvent,
  type Picker,
} from './handMachine'
import { CARD_IDS, cardMeta, cardTitle } from './meta'
import { tr, useLocale } from '../../i18n'
import { phaseStore, usePhase } from './phase'
import { gameStore, useCountdownVar, useGame, type Move, type TableState } from './useGame'
import './Kittens.css'

const NEVER_PLAYABLE_ALONE = new Set<CardId>(['exploding_kitten', 'defuse', 'nope'])

/** The full width of the Nope window, in ms. Matches the server. */
const NOPE_MS = 5000

const Card = memo(function Card({ id }: { id: CardId }) {
  const meta = cardMeta(id)
  const Face = CARD_ART[id]
  return (
    <CardFrame title={meta.title} accent={meta.accent} kind={meta.kind}>
      <Face />
    </CardFrame>
  )
})

/**
 * Place something in the world layer.
 *
 * The numbers are stage units and the property is `px`, which looks wrong
 * until you remember the layer is scaled by the camera matrix: one "pixel"
 * here is one unit of the room.
 */
function worldStyle(
  x: number,
  y: number,
  w = GAME_CARD.w,
  h = GAME_CARD.h,
): CSSProperties {
  return { left: `${x - w / 2}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` }
}

type Action = {
  label: string
  hint: string
  /** Null when the card needs a choice made before there is a move at all. */
  move: Move | null
  picker?: Picker
}

/**
 * What the chosen cards would do.
 *
 * Every branch here is a restatement of a rule the server enforces anyway —
 * it exists so the button can be labelled, not so the client can decide.
 */
function actionFor(table: TableState, chosen: CardId[]): Action | null {
  if (chosen.length === 0) return null
  const allSame = chosen.every((c) => c === chosen[0])
  const first = chosen[0]

  if (chosen.length === 1 && !NEVER_PLAYABLE_ALONE.has(first) && cardMeta(first).kind !== 'cat') {
    return {
      label: tr('ek.playCard', { card: cardMeta(first).title }),
      hint: cardMeta(first).effect,
      move: { move: 'play', card: first },
    }
  }
  if (chosen.length === 2 && allSame) {
    return {
      label: tr('ek.stealRandom'),
      hint: tr('ek.stealHint'),
      move: { move: 'combo', cards: chosen },
    }
  }
  if (chosen.length === 3 && allSame) {
    return {
      label: tr('ek.demandCard'),
      hint: tr('ek.demandHint'),
      move: null,
      picker: 'demand',
    }
  }
  if (chosen.length === 5 && new Set(chosen).size === 5 && table.discard.length > 0) {
    return {
      label: tr('ek.raidPile'),
      hint: tr('ek.raidHint'),
      move: { move: 'combo', cards: chosen },
    }
  }
  return null
}

/** How long the fan takes to open a gap. Matches `ek-make-room` in the CSS. */
const GAP_MS = 200

/* ───────────────────────────────────────────────────────── the world */

function DeckPile({
  table,
  onDraw,
  live,
}: {
  table: TableState
  onDraw: () => void
  live: boolean
}) {
  const style = worldStyle(GAME_TABLE.deckX, GAME_TABLE.cardY)
  const label = live ? tr('ek.drawEnd') : tr('ek.cardsLeft', { count: table.deck_count })
  return (
    <div className="ek-pile-slot" style={style}>
      <div className="ek-stack" aria-hidden />
      <button
        type="button"
        className={`ek-pile-face ek-deck ${live ? 'is-live' : ''}`}
        disabled={!live}
        onClick={onDraw}
        title={label}
        aria-label={label}
      >
        <CardBack />
      </button>
    </div>
  )
}

function DiscardPile({
  table,
  glowing,
  dropTarget,
}: {
  table: TableState
  glowing: boolean
  dropTarget: boolean
}) {
  const top = table.discard[table.discard.length - 1]
  const style = worldStyle(GAME_TABLE.discardX, GAME_TABLE.cardY)
  return (
    <div
      className={`ek-pile-slot ek-discard ${glowing ? 'is-pending' : ''} ${
        dropTarget ? 'is-drop' : ''
      }`}
      style={style}
    >
      {top ? (
        <div className="ek-pile-face ek-flip-in" key={`${top}-${table.discard.length}`}>
          <Card id={top} />
        </div>
      ) : (
        <div className="ek-pile-empty" aria-hidden />
      )}
    </div>
  )
}

/**
 * The two labels, in screen space.
 *
 * Told where to be by the bridge rather than living with the cards: text in
 * the world layer is laid out at a fraction of a pixel and magnified by the
 * camera, and arrives blurred.
 */
function PileTags({
  table,
  live,
  attach,
}: {
  table: TableState
  live: boolean
  attach: (el: HTMLDivElement | null) => void
}) {
  const top = table.discard[table.discard.length - 1]
  return (
    <div className="ek-tags" ref={attach} aria-hidden>
      <span className="ek-tag ek-tag-deck">
        {tr('ek.left', { count: table.deck_count })}
        {live && <em>{tr('ek.clickToDraw')}</em>}
      </span>
      <span className="ek-tag ek-tag-discard">
        {table.discard.length > 0 ? cardTitle(top) : tr('ek.discard')}
      </span>
    </div>
  )
}

/** His hand. Backs only, and there is nothing else here to show. */
function RauHand({
  count,
  held,
  thinking,
  attach,
}: {
  /** Backs to draw — fewer than `held` while the cards are still arriving. */
  count: number
  /** What he is actually holding, which is what a screen reader should hear. */
  held: number
  thinking: boolean
  attach: (el: HTMLDivElement | null) => void
}) {
  return (
    <div
      className={`ek-rau-hand ${thinking ? 'is-thinking' : ''}`}
      ref={attach}
      aria-label={tr('ek.rauHolding', { count: held })}
    >
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="ek-rau-card"
          style={{ '--i': i, '--n': count } as CSSProperties}
        >
          <CardBack />
        </div>
      ))}
    </div>
  )
}

/* ──────────────────────────────────────────────────────── the screen */

/**
 * The five seconds that make Nope worth holding.
 *
 * No dialog: his card sits glowing on the pile with the clock running, and if
 * you are holding a Nope it lifts itself out of your hand at the edge of the
 * fan with the countdown drawn around it. Slam it or watch it happen.
 */
function NopeRing({ table, onNope, onPass }: {
  table: TableState
  onNope: () => void
  onPass: () => void
}) {
  const pending = table.pending
  // The ring is written straight to the node, one property per frame, rather
  // than re-rendering this component sixty times a second for five seconds.
  const ring = useCountdownVar(pending?.deadline ?? null, NOPE_MS)
  if (!pending) return null

  const yours = pending.waiting_on === 'user'
  const played = pending.cards.map(cardTitle).join(' + ')
  const blocked = pending.nopes % 2 === 1
  const deep =
    pending.nopes > 1
      ? tr(blocked ? 'ek.nopesDeepWont' : 'ek.nopesDeepWill', { count: pending.nopes })
      : pending.nopes === 1
        ? tr(blocked ? 'ek.nopeOneWont' : 'ek.nopeOneWill')
        : ''

  return (
    <div className="ek-nope" role="status">
      <p className="ek-nope-line">
        {tr('ek.played', {
          who: pending.actor === 'user' ? tr('ek.you') : tr('ek.rau'),
          cards: played,
        })}
        <span className="ek-nope-deep">{deep}</span>
      </p>
      {yours && table.can_nope ? (
        <div className="ek-nope-slot">
          <button
            type="button"
            className="ek-nope-card"
            ref={ring as RefObject<HTMLButtonElement | null>}
            onClick={onNope}
            aria-label={tr('ek.playNope')}
            title={tr('card.nope')}
          >
            <span className="ek-nope-ring" aria-hidden />
            <span className="ek-nope-face">
              <Card id="nope" />
            </span>
          </button>
          <button type="button" className="ek-quiet" onClick={onPass}>
            {tr('ek.letItHappen')}
          </button>
        </div>
      ) : (
        <p className="ek-nope-wait">
          {yours ? tr('ek.noNope') : tr('ek.waitingRau')}
        </p>
      )}
    </div>
  )
}

function GameOverScene({ table, onAgain, onLeave }: {
  table: TableState
  onAgain: () => void
  onLeave: () => void
}) {
  const won = table.winner === 'user'
  return (
    <div
      className={`ek-over ${won ? 'is-win' : 'is-loss'}`}
      role="alertdialog"
      aria-label={tr('ek.gameOver')}
    >
      <div className="ek-over-card">
        <div className="ek-over-art">
          <Card id={won ? 'defuse' : 'exploding_kitten'} />
        </div>
        <h2>{won ? tr('ek.youWin') : tr('ek.youExploded')}</h2>
        <p>{table.over_reason}</p>
        {table.final_hands && (
          <p className="ek-over-hands">
            {tr('ek.holding', {
              cards: table.final_hands.rau.map(cardTitle).join(', ') || tr('ek.nothing'),
            })}
          </p>
        )}
        <div className="ek-over-actions">
          <button type="button" className="ek-btn ek-btn-primary" onClick={onAgain}>
            {tr('ek.dealAgain')}
          </button>
          <button type="button" className="ek-btn ek-btn-quiet" onClick={onLeave}>
            Leave the table
          </button>
        </div>
      </div>
    </div>
  )
}

/* ───────────────────────────────────────────────────────────── table */

export default memo(function GameTable() {
  const { t } = useLocale()
  const { table, busy, error } = useGame()
  const phase = usePhase()
  const gameId = table?.game_id ?? ''
  const tablePhase = table?.phase ?? ''
  const awaitingYou = table?.awaiting_you ?? false
  const handSignature = table?.hand.join(',') ?? ''
  const playerHandCount = table?.hand.length ?? 0
  const rauHandCount = table?.hand_counts.rau ?? 0
  const defuseIndex = table?.hand.indexOf('defuse') ?? -1
  const [hand, rawDispatch] = useReducer(handReducer, IDLE_HAND)
  /*
    The gesture cannot be read out of the render closure.

    A pointerdown and the pointerup that follows it can land in the same task,
    and then the handler for the second one is still looking at the state from
    before the first — so the click that should have raised a card sees an
    idle hand and does nothing at all. The reducer is pure, so stepping a ref
    alongside React costs nothing and makes the gesture independent of when a
    render happens to occur.
  */
  const handRef = useRef(hand)
  const dispatch = useCallback((event: HandEvent) => {
    handRef.current = handReducer(handRef.current, event)
    rawDispatch(event)
  }, [])
  /*
    How many cards have landed on each side. `Infinity` means "all of them",
    which is the answer for every phase except a deal in progress.

    The initial value has to be read from the phase rather than assumed,
    because this component mounts the moment the server confirms the deal —
    while he is still walking to the table, a good three seconds before the
    cards are dealt. Starting at `Infinity` meant the whole hand appeared at
    once during the walk-on and was then swept away and re-dealt properly,
    which is the deal happening twice, badly, the first time.
  */
  const dealPending = phase === 'summoning' || phase === 'dealing'
  const [dealtCount, setDealtCount] = useState(() => (dealPending ? 0 : Infinity))
  const [dealtRau, setDealtRau] = useState(() => (dealPending ? 0 : Infinity))
  /*
    Slots in your hand that a card is on its way to.

    A card you draw used to appear in the fan at full size the instant the
    server said you had it, and *then* a copy of it flew over to where it
    already was. Holding the slot empty until the flight lands — and opening
    the gap for it first — is what makes the card look like it goes in rather
    than like it was already there.
  */
  const [arriving, setArriving] = useState<number[]>([])
  const [named, setNamed] = useState<CardId | null>(null)
  const [insertAt, setInsertAt] = useState(0)
  const [hint, setHint] = useState('')

  const screenRef = useRef<HTMLDivElement | null>(null)
  const templateRef = useRef<HTMLDivElement | null>(null)
  const fanRef = useRef<HTMLDivElement | null>(null)
  const cardEls = useRef(new Map<number, HTMLElement>())
  const prevTable = useRef<TableState | null>(null)
  /** Home centre of the card being dragged, so the offset is from where it was. */
  const dragHome = useRef<Pt>({ x: 0, y: 0 })
  /** Tears down the window listeners for the gesture in progress, if any. */
  const endGesture = useRef<(() => void) | null>(null)

  /** The layer we handed the bridge, so the cleanup can name what it returns. */
  const ownedWorld = useRef<HTMLElement | null>(null)
  const attachWorld = useCallback((el: HTMLDivElement | null) => {
    if (el) ownedWorld.current = el
    gameBridge.attachWorld(el)
  }, [])
  /** His fan, kept as a ref too: flight sizing measures a card off it. */
  const rauHandRef = useRef<HTMLDivElement | null>(null)
  const attachRau = useCallback((el: HTMLDivElement | null) => {
    rauHandRef.current = el
    gameBridge.attachRauHand(el)
  }, [])
  const attachTags = useCallback((el: HTMLDivElement | null) => {
    gameBridge.attachTags(el)
  }, [])

  // Leaving the room must not leave him staring at a card that is gone.
  useEffect(
    () => () => {
      gameBridge.hoverPoint = null
      endGesture.current?.()
      // Only if the board has not already taken it — see `releaseWorld`.
      gameBridge.releaseWorld(ownedWorld.current)
      gameBridge.attachRauHand(null)
      gameBridge.attachTags(null)
    },
    [],
  )

  /* ── selection bookkeeping ──────────────────────────────────────── */

  // A hand that changed under a selection makes the selection meaningless.
  useEffect(() => {
    dispatch({ type: 'reset' })
    setNamed(null)
    setHint('')
  }, [handSignature, tablePhase, dispatch])

  // The server asking for something raises the card itself: being told to
  // defuse and then having to find the Defuse in your own fan is a puzzle
  // nobody wanted.
  useEffect(() => {
    if (!awaitingYou) return
    if (tablePhase === 'awaiting_defuse') {
      dispatch({
        type: 'raise',
        indices: defuseIndex >= 0 ? [defuseIndex] : [],
        picker: 'defuse',
      })
      setInsertAt(0)
    }
    // The hand signature is in here as well as in the reset above, and has to
    // be: the reset fires on any change to the hand, so without re-raising
    // afterwards a Defuse prompt would quietly disappear the moment anything
    // else about your cards moved.
  }, [tablePhase, awaitingYou, gameId, handSignature, defuseIndex, dispatch])

  /* ── where things are, in screen pixels ─────────────────────────── */

  const pointOf = useCallback((spot: FlightSpot): Pt => {
    const snap = gameBridge.current
    if (spot === 'deck') return gameBridge.spot('deck')
    if (spot === 'discard') return gameBridge.spot('discard')
    if (spot === 'rauHand') return snap?.rauHand ?? { x: 0, y: 0 }
    const fan = fanRef.current?.getBoundingClientRect()
    if (fan) return { x: fan.x + fan.width / 2, y: fan.y + fan.height / 2 }
    return { x: (snap?.w ?? 0) / 2, y: (snap?.h ?? 0) - 90 }
  }, [])

  /**
   * How big a card is at a given spot, relative to the card in flight.
   *
   * Measured rather than declared: the piles and his fan live under the
   * camera matrix, so their on-screen size depends on how far the camera has
   * pushed in, and yours is a `clamp()` against the viewport. Both are things
   * only the browser knows. Every fallback is deliberately a shrink — a card
   * that arrives slightly small settles into place, one that arrives large
   * pops.
   */
  const scaleOf = useCallback((spot: FlightSpot): number => {
    const flightW = templateRef.current?.getBoundingClientRect().width ?? 0
    if (flightW <= 0) return 1
    const snap = gameBridge.current
    if (spot === 'deck' || spot === 'discard') {
      const r = snap?.spots[spot]
      return r && r.w > 0 ? r.w / flightW : 0.7
    }
    if (spot === 'rauHand') {
      const his = rauHandRef.current?.querySelector('.ek-rau-card')
      const w = his?.getBoundingClientRect().width ?? 0
      if (w > 0) return w / flightW
      // He is between hands. His backs are a little smaller than the pile.
      const deck = snap?.spots.deck
      return deck && deck.w > 0 ? (deck.w * 0.8) / flightW : 0.6
    }
    return 1
  }, [])

  const overDiscard = useCallback((x: number, y: number) => {
    const r = gameBridge.current?.spots.discard
    if (!r) return false
    // Generous: dropping *near* the pile is dropping on it.
    const pad = 28
    return x >= r.x - pad && x <= r.x + r.w + pad && y >= r.y - pad && y <= r.y + r.h + pad
  }, [])

  /* ── the deal ───────────────────────────────────────────────────── */

  useEffect(() => {
    if (phase !== 'dealing' || !gameId) return
    let cancelled = false
    setDealtCount(0)
    setDealtRau(0)

    // Alternating, the way anyone deals: one to you, one to him, round again.
    const order: ('you' | 'him')[] = []
    for (let i = 0; i < Math.max(playerHandCount, rauHandCount); i++) {
      if (i < playerHandCount) order.push('you')
      if (i < rauHandCount) order.push('him')
    }
    const flicks = gameBridge.choreography?.startDeal(order.length) ?? []

    const finish = () => {
      if (cancelled) return
      setDealtCount(Infinity)
      setDealtRau(Infinity)
      phaseStore.dealt()
    }

    const layer = screenRef.current
    const template = templateRef.current
    if (!layer || !template || reducedMotion() || order.length === 0) {
      const t = setTimeout(finish, reducedMotion() ? 0 : 260)
      return () => {
        cancelled = true
        clearTimeout(t)
      }
    }

    // One frame late, so the fan has laid out and can be measured.
    const raf = requestAnimationFrame(() => {
      if (cancelled) return
      const deck = pointOf('deck')
      const his = pointOf('rauHand')
      // Everything measured before anything is cloned. `runFlight` puts a card
      // into the flight layer, which dirties layout, so a rect read taken
      // between two of them is a forced reflow — and a deal is a dozen flights
      // in one frame. The scales are the same for every card in the run.
      const deckScale = scaleOf('deck')
      const mineScale = scaleOf('playerHand')
      const hisScale = scaleOf('rauHand')
      let slot = 0
      let hisSlot = 0
      const plan = order.map((who, i) => {
        const delay = flicks[i] ?? i * DEAL_STAGGER_MS
        const mine = who === 'you'
        let to = his
        // Which card in that side's hand this one is, so it can be revealed
        // when — and only when — the card flying to it arrives.
        const landing = mine ? slot++ : hisSlot++
        if (mine) {
          const el = cardEls.current.get(landing)
          if (el) {
            const r = el.getBoundingClientRect()
            to = { x: r.x + r.width / 2, y: r.y + r.height / 2 }
          } else {
            to = pointOf('playerHand')
          }
        }
        return { delay, mine, landing, to }
      })
      const jobs = plan.map(({ delay, mine, landing, to }) =>
        runFlight(layer, template, deck, to, {
          delay,
          spin: mine ? 16 : -12,
          fromScale: deckScale,
          toScale: mine ? mineScale : hisScale,
        }).then(() => {
          if (cancelled) return
          const bump = mine ? setDealtCount : setDealtRau
          bump((n) => Math.max(n, landing + 1))
        }),
      )
      void Promise.all(jobs).then(finish)
    })

    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
    }
  }, [phase, gameId, playerHandCount, rauHandCount, pointOf, scaleOf])

  /* ── everything else that moves ─────────────────────────────────── */

  useEffect(() => {
    if (!table) return
    const prev = prevTable.current
    prevTable.current = table
    if (phase !== 'playing' || !prev || prev.game_id !== table.game_id) return

    const beats = diffBeats(prev, table)
    if (beats.length > 0) gameBridge.choreography?.observe(beats)

    const layer = screenRef.current
    const template = templateRef.current
    if (!layer || !template) return

    const requests = diffFlights(prev, table)
    const slots = arrivedSlots(prev.hand, table.hand)
    // Cards coming to you are flown into a specific slot; everything else —
    // his hand, the discard pile — is a place, not a position in a fan.
    const yours = requests.filter((r) => r.to === 'playerHand')
    const elsewhere = requests.filter((r) => r.to !== 'playerHand')

    // Measured in one pass, flown in the next: `runFlight` appends the card
    // into the flight layer, so a rect read taken between two of them forces a
    // reflow. Splitting the two costs nothing — the stagger is a `delay` on
    // each animation, not on when it is started.
    const elsewhereFlights = elsewhere.map((req, i) => ({
      from: pointOf(req.from),
      to: pointOf(req.to),
      opts: {
        delay: i * 80,
        spin: req.to === 'discard' ? 18 : -10,
        fromScale: scaleOf(req.from),
        toScale: scaleOf(req.to),
      },
    }))
    for (const f of elsewhereFlights) void runFlight(layer, template, f.from, f.to, f.opts)

    if (yours.length === 0) return
    if (slots.length === 0 || reducedMotion()) {
      const home = pointOf('playerHand')
      const direct = yours.map((req, i) => ({
        from: pointOf(req.from),
        opts: { delay: i * 80, spin: -10, fromScale: scaleOf(req.from), toScale: 1 },
      }))
      for (const f of direct) void runFlight(layer, template, f.from, home, f.opts)
      return
    }

    let cancelled = false
    setArriving(slots)
    // The gap opens first and the card is thrown into it, rather than both at
    // once: a card cannot slide into a space that is still being made, and
    // the slot cannot be measured until it is roughly the size it will end up.
    const timer = setTimeout(() => {
      if (cancelled) return
      // Same two passes as above, and it matters more here: this runs while
      // the gap the slots opened is still animating, so every rect read is
      // already paying for a layout it should only pay for once.
      const plan = yours.map((req, i) => {
        const slot = slots[i] ?? slots[slots.length - 1]
        const el = cardEls.current.get(slot)
        const rect = el?.getBoundingClientRect()
        return {
          from: pointOf(req.from),
          to: rect
            ? { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }
            : pointOf('playerHand'),
          opts: { delay: i * 80, spin: -10, fromScale: scaleOf(req.from), toScale: 1 },
        }
      })
      const jobs = plan.map((f) => runFlight(layer, template, f.from, f.to, f.opts))
      void Promise.all(jobs).then(() => {
        if (!cancelled) setArriving([])
      })
    }, GAP_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
      // Whatever was in the air belongs to a hand that no longer exists. The
      // slots are indices into it, so they cannot outlive it.
      setArriving([])
    }
  }, [table, phase, pointOf, scaleOf])

  /* ── moves ──────────────────────────────────────────────────────── */

  const commit = useCallback(async (move: Move) => {
    const ok = await gameStore.play(move)
    dispatch({ type: 'resolved', ok })
  }, [dispatch])

  const chosen = useMemo(() => {
    if (!table) return []
    return raisedIndices(hand)
      .map((i) => table.hand[i])
      .filter(Boolean)
  }, [table, hand])

  const action = useMemo(
    () => (table ? actionFor(table, chosen) : null),
    [table, chosen],
  )

  if (!table) return null

  const raised = raisedIndices(hand)
  const locked = handLocked(hand) || busy
  const yourMove = table.your_turn && table.phase === 'playing' && phase === 'playing'
  const giving = table.phase === 'awaiting_favor' && table.awaiting_you
  const salvaging = table.phase === 'awaiting_discard_pick' && table.awaiting_you
  const defusing = table.phase === 'awaiting_defuse' && table.awaiting_you
  const interactive = (yourMove || giving) && !locked

  const insertMax = table.insert_max ?? table.deck_count

  /* ── pointer handling on the fan ────────────────────────────────── */

  /*
    One gesture, tracked on the window.

    Not on the card, and not through `setPointerCapture`: a card being dragged
    to the pile is out from under the pointer almost immediately, and a
    gesture that only hears about moves landing on its own element loses the
    drag the moment it starts working. The window hears all of them.
  */
  const beginGesture = (index: number, at: Pt, home: DOMRect) => {
    endGesture.current?.()
    dragHome.current = { x: home.x + home.width / 2, y: home.y + home.height / 2 }
    dispatch({ type: 'press', index, at })

    const stop = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      endGesture.current = null
    }
    const onMove = (ev: PointerEvent) => {
      dispatch({
        type: 'move',
        at: { x: ev.clientX, y: ev.clientY },
        overDiscard: overDiscard(ev.clientX, ev.clientY),
      })
    }
    const onCancel = () => {
      stop()
      dispatch({ type: 'cancel' })
    }
    const onUp = (ev: PointerEvent) => {
      stop()
      finishGesture(ev.clientX, ev.clientY)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
    endGesture.current = stop
  }

  const finishGesture = (x: number, y: number) => {
    const current = handRef.current
    if (current.mode === 'pressed') {
      // Never travelled: the whole gesture was a click, so up it comes.
      if (giving) {
        dispatch({ type: 'release', overDiscard: false })
        dispatch({ type: 'raise', indices: [current.index], picker: 'favor' })
        return
      }
      dispatch({ type: 'release', overDiscard: false })
      return
    }
    if (current.mode !== 'dragging') return

    const over = overDiscard(x, y)
    const card = table.hand[current.index]
    if (!over || !card) {
      dispatch({ type: 'release', overDiscard: false })
      return
    }
    if (giving) {
      dispatch({ type: 'release', overDiscard: true })
      void commit({ move: 'give_favor', card })
      return
    }
    const dropped = actionFor(table, [card])
    if (!dropped) {
      dispatch({ type: 'release', overDiscard: false })
      setHint(
        cardMeta(card).kind === 'cat'
          ? t('ek.catAlone')
          : t('ek.notAlone', { card: cardMeta(card).title }),
      )
      return
    }
    if (dropped.move) {
      dispatch({ type: 'release', overDiscard: true })
      void commit(dropped.move)
      return
    }
    // Dropped, but the card wants to know something first: the choice opens
    // over the pile rather than the card being thrown back.
    dispatch({ type: 'release', overDiscard: true, needsPicker: dropped.picker ?? 'none' })
  }

  const onCardDown = (index: number) => (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (!interactive) return
    const current = handRef.current
    // Adding to an existing selection is a click, not the start of a drag:
    // building a pair by dragging both cards at once is not a gesture.
    if (current.mode === 'raised' && !current.indices.includes(index)) {
      dispatch({ type: 'raiseAdd', index })
      return
    }
    e.preventDefault()
    beginGesture(index, { x: e.clientX, y: e.clientY }, e.currentTarget.getBoundingClientRect())
  }

  const onCardEnter = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    gameBridge.hoverPoint = { x: r.x + r.width / 2, y: r.y + r.height / 2 }
  }
  const onCardLeave = () => {
    gameBridge.hoverPoint = null
  }

  const confirmRaised = () => {
    if (!action) return
    if (action.move) {
      dispatch({ type: 'confirm' })
      void commit(action.move)
      return
    }
    dispatch({ type: 'picker', picker: action.picker ?? 'none' })
  }

  const dragOffset =
    hand.mode === 'dragging'
      ? { x: hand.at.x - dragHome.current.x, y: hand.at.y - dragHome.current.y }
      : null

  const thinking = !table.your_turn && table.phase !== 'over'
  const lastLine = table.log[table.log.length - 1]

  return (
    <div className="ek-room" role="region" aria-label={t('ek.region')}>
      <CardDefs />

      {/* ── in the room ─────────────────────────────────────────── */}
      <div className="ek-world" ref={attachWorld} aria-hidden={false}>
        <DeckPile
          table={table}
          live={yourMove && !locked}
          onDraw={() => {
            dispatch({ type: 'reset' })
            void gameStore.play({ move: 'draw' })
          }}
        />
        <DiscardPile
          table={table}
          glowing={table.phase === 'nope_window'}
          dropTarget={hand.mode === 'dragging' && hand.overDiscard}
        />
        <RauHand
          count={Math.min(table.hand_counts.rau, dealtRau)}
          held={table.hand_counts.rau}
          thinking={thinking}
          attach={attachRau}
        />

        {table.known_top.length > 0 && (
          <div
            className="ek-known"
            style={worldStyle(
              KNOWN_TOP_SPOT.x,
              KNOWN_TOP_SPOT.y,
              GAME_CARD.w * table.known_top.length * 0.78,
              GAME_CARD.h * 0.62,
            )}
            aria-label={t('ek.knownTop')}
          >
            {table.known_top.map((id, i) => (
              <div className="ek-known-card" key={`${id}-${i}`}>
                <Card id={id} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── in your hands ───────────────────────────────────────── */}
      <div className="ek-screen" ref={screenRef}>
        {/* Cloned for every card in flight, so what flies is what lands. */}
        <div className="ek-flight-template" ref={templateRef} aria-hidden>
          <CardBack />
        </div>

        <PileTags table={table} live={yourMove && !locked} attach={attachTags} />

        <div className="ek-strip">
          <span className={`ek-turn ${thinking ? 'is-his' : ''}`}>
            {table.phase === 'over'
              ? t('ek.gameOver')
              : table.your_turn
                ? t('ek.yourTurn')
                : t('ek.thinking')}
          </span>
          {table.turns_to_take > 1 && table.phase !== 'over' && (
            <span className="ek-owed">{t('ek.turnsOwed', { count: table.turns_to_take })}</span>
          )}
          {lastLine && <span className="ek-log">{lastLine.text}</span>}
          <button
            type="button"
            className="ek-quiet ek-leave"
            onClick={() => void phaseStore.leave()}
          >
            {t('ek.leave')}
          </button>
        </div>

        {table.phase === 'nope_window' && (
          <NopeRing
            table={table}
            onNope={() => void gameStore.play({ move: 'nope' })}
            onPass={() => void gameStore.play({ move: 'pass_nope' })}
          />
        )}

        {salvaging && (
          <div className="ek-salvage" role="group" aria-label={t('ek.salvageLabel')}>
            <p>{t('ek.salvageCopy')}</p>
            <div className="ek-salvage-fan">
              {[...new Set(table.discard)]
                .filter((c) => c !== 'exploding_kitten')
                .map((id, i, all) => (
                  <button
                    key={id}
                    type="button"
                    className="ek-card"
                    style={{ '--i': i, '--n': all.length } as CSSProperties}
                    disabled={locked}
                    onClick={() => void gameStore.play({ move: 'take_from_discard', card: id })}
                    aria-label={cardMeta(id).title}
                  >
                    <Card id={id} />
                  </button>
                ))}
            </div>
          </div>
        )}

        {(error || hint) && (
          <p
            className="ek-error"
            role="alert"
            onClick={() => {
              gameStore.clearError()
              setHint('')
            }}
          >
            {error || hint}
          </p>
        )}

        {/* ── the raised card ──────────────────────────────────── */}
        {raised.length > 0 && chosen.length > 0 && (
          <div className="ek-raised" role="group" aria-label={t('ek.raisedLabel')}>
            <div className="ek-raised-cards">
              {chosen.map((id, i) => (
                <div className="ek-raised-card" key={`${id}-${i}`} style={{ '--i': i } as CSSProperties}>
                  <Card id={id} />
                </div>
              ))}
            </div>

            {hand.mode === 'raised' && hand.picker === 'demand' ? (
              <div className="ek-picker">
                <h3>{t('ek.nameTitle')}</h3>
                <p>{t('ek.nameCopy')}</p>
                <div className="ek-picker-grid">
                  {CARD_IDS.filter((c) => c !== 'exploding_kitten')
                    .map((id) => (
                      <button
                        key={id}
                        type="button"
                        className={`ek-chip ${named === id ? 'is-on' : ''}`}
                        onClick={() => setNamed(id)}
                      >
                        {cardMeta(id).title}
                      </button>
                    ))}
                </div>
                <div className="ek-raised-actions">
                  <button
                    type="button"
                    className="ek-btn ek-btn-primary"
                    disabled={!named || locked}
                    onClick={() => {
                      if (!named) return
                      dispatch({ type: 'confirm' })
                      void commit({ move: 'combo', cards: chosen, named_card: named })
                    }}
                  >
                    {named ? t('ek.demand', { card: cardMeta(named).title }) : t('ek.pickOne')}
                  </button>
                  <button type="button" className="ek-quiet" onClick={() => dispatch({ type: 'cancel' })}>
                    Back
                  </button>
                </div>
              </div>
            ) : hand.mode === 'raised' && hand.picker === 'defuse' ? (
              <div className="ek-picker">
                <h3>{t('ek.defusedTitle')}</h3>
                <p>{t('ek.defusedCopy', { count: insertMax })}</p>
                <div className="ek-slider">
                  <span>{t('ek.top')}</span>
                  <input
                    type="range"
                    min={0}
                    max={insertMax}
                    value={insertAt}
                    onChange={(e) => setInsertAt(Number(e.target.value))}
                    aria-label={t('ek.hideDepth')}
                  />
                  <span>{t('ek.bottom')}</span>
                </div>
                <p className="ek-slider-read">
                  {insertAt === 0
                    ? t('ek.rightOnTop')
                    : insertAt >= insertMax
                      ? t('ek.allTheWay')
                      : insertAt === 1
                        ? t('ek.oneCardDown')
                        : t('ek.cardsDown', { count: insertAt })}
                </p>
                <div className="ek-raised-actions">
                  <button
                    type="button"
                    className="ek-btn ek-btn-primary"
                    disabled={locked}
                    onClick={() => {
                      dispatch({ type: 'confirm' })
                      void commit({ move: 'insert_kitten', index: insertAt })
                    }}
                  >
                    {t('ek.putBack')}
                  </button>
                </div>
              </div>
            ) : hand.mode === 'raised' && hand.picker === 'favor' ? (
              <div className="ek-raised-actions">
                <p className="ek-raised-hint">{t('ek.favorAsk')}</p>
                <button
                  type="button"
                  className="ek-btn ek-btn-primary"
                  disabled={locked}
                  onClick={() => {
                    dispatch({ type: 'confirm' })
                    void commit({ move: 'give_favor', card: chosen[0] })
                  }}
                >
                  {t('ek.give', { card: cardMeta(chosen[0]).title })}
                </button>
                <button type="button" className="ek-quiet" onClick={() => dispatch({ type: 'cancel' })}>
                  Back
                </button>
              </div>
            ) : (
              <div className="ek-raised-actions">
                <p className="ek-raised-hint">
                  {action
                    ? action.hint
                    : chosen.length === 1
                      ? cardMeta(chosen[0]).effect
                      : t('ek.notASet')}
                </p>
                <button
                  type="button"
                  className="ek-btn ek-btn-primary"
                  disabled={!action || locked}
                  onClick={confirmRaised}
                >
                  {action ? action.label : t('ek.nothingToPlay')}
                </button>
                <button type="button" className="ek-quiet" onClick={() => dispatch({ type: 'cancel' })}>
                  Back
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── the fan you are holding ──────────────────────────── */}
        <div
          className={`ek-fan ${locked ? 'is-locked' : ''} ${giving ? 'is-giving' : ''} ${
            defusing ? 'is-defusing' : ''
          }`}
          ref={fanRef}
          role="group"
          aria-label={t('ek.handLabel')}
        >
          {table.hand.map((id, i) => {
            const isDragging = hand.mode === 'dragging' && hand.index === i
            const isRaised = raised.includes(i)
            const coming = arriving.includes(i)
            const landed = i < dealtCount && !coming
            const style: CSSProperties = {
              '--i': i,
              '--n': table.hand.length,
            } as CSSProperties
            if (isDragging && dragOffset) {
              style.transform = `translate(${dragOffset.x}px, ${dragOffset.y}px) rotate(3deg) scale(1.06)`
              style.zIndex = 30
            }
            return (
              <button
                key={`${id}-${i}`}
                type="button"
                ref={(el) => {
                  if (el) cardEls.current.set(i, el)
                  else cardEls.current.delete(i)
                }}
                className={`ek-card ${isRaised ? 'is-raised' : ''} ${
                  isDragging ? 'is-dragging' : ''
                } ${landed ? '' : 'is-undealt'} ${coming ? 'is-arriving' : ''}`}
                style={style}
                disabled={!interactive}
                onPointerDown={onCardDown(i)}
                onPointerEnter={onCardEnter}
                onPointerLeave={onCardLeave}
                title={`${cardMeta(id).title} · ${cardMeta(id).effect}`}
                aria-label={cardMeta(id).title}
                aria-pressed={isRaised}
              >
                <Card id={id} />
              </button>
            )
          })}
        </div>

        {table.phase === 'over' && (
          <GameOverScene
            table={table}
            onAgain={() => void phaseStore.redeal()}
            onLeave={() => void phaseStore.leave(table.winner === 'user' ? 'win' : 'loss')}
          />
        )}
      </div>
    </div>
  )
})
