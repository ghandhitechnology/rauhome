/**
 * The table.
 *
 * Mounted over the room while a game is live, the way `PanelViewer` mounts over
 * it while a panel is open. There is no local game logic in here at all: the
 * component renders the seat view it is given and posts moves back. If it looks
 * like it is deciding something — which cards can combo, whether Nope is
 * available — it is only reading a flag the server already set.
 *
 * The one thing computed locally is the Nope countdown, from the deadline in the
 * payload. A bar driven by server ticks would stutter whenever the socket was
 * quiet, and stutter in a five-second window reads as the game being broken.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { CARD_ART, CardBack, CardDefs, CardFrame, type CardId } from './art'
import { CARD_META, cardTitle } from './meta'
import { gameStore, useCountdown, useGame, type TableState } from './useGame'
import './Kittens.css'

const NEVER_PLAYABLE_ALONE = new Set<CardId>(['exploding_kitten', 'defuse', 'nope'])

function Card({ id }: { id: CardId }) {
  const meta = CARD_META[id]
  const Face = CARD_ART[id]
  return (
    <CardFrame title={meta.title} accent={meta.accent} kind={meta.kind}>
      <Face />
    </CardFrame>
  )
}

/** A card in a hand or a pile, with the click target and the hover lift. */
function CardButton({
  id,
  selected,
  disabled,
  onClick,
  index,
  count = 1,
}: {
  id: CardId
  selected?: boolean
  disabled?: boolean
  onClick?: () => void
  index: number
  /** Hand size, so the fan can splay symmetrically around the middle card. */
  count?: number
}) {
  const meta = CARD_META[id]
  return (
    <button
      type="button"
      className={`ek-card ${selected ? 'is-selected' : ''}`}
      style={{ '--i': index, '--n': count } as React.CSSProperties}
      disabled={disabled}
      onClick={onClick}
      title={`${meta.title} — ${meta.effect}`}
      aria-pressed={selected}
      aria-label={meta.title}
    >
      <Card id={id} />
    </button>
  )
}

/** Rau's hand: backs only, and there is nothing else here to show. */
function OpponentHand({ count, thinking }: { count: number; thinking: boolean }) {
  return (
    <div className={`ek-hand ek-hand-opponent ${thinking ? 'is-thinking' : ''}`}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="ek-card ek-card-back" style={{ '--i': i } as React.CSSProperties}>
          <CardBack />
        </div>
      ))}
      {count === 0 && <p className="ek-empty">No cards.</p>}
    </div>
  )
}

function Pile({ table }: { table: TableState }) {
  const top = table.discard[table.discard.length - 1]
  return (
    <div className="ek-piles">
      <div className="ek-pile">
        <div className="ek-pile-stack" data-count={Math.min(table.deck_count, 6)}>
          <div className="ek-card ek-card-static">
            <CardBack />
          </div>
        </div>
        <span className="ek-pile-label">
          {table.deck_count} left
          <em>one of them is the kitten</em>
        </span>
      </div>
      <div className="ek-pile">
        <div className="ek-pile-stack">
          {top ? (
            <div className="ek-card ek-card-static ek-flip-in" key={`${top}-${table.discard.length}`}>
              <Card id={top} />
            </div>
          ) : (
            <div className="ek-pile-empty" aria-hidden />
          )}
        </div>
        <span className="ek-pile-label">
          discard
          <em>{table.discard.length} cards</em>
        </span>
      </div>
    </div>
  )
}

/** The five seconds that make Nope worth holding. */
function NopeWindow({ table }: { table: TableState }) {
  const pending = table.pending
  const left = useCountdown(pending?.deadline ?? null)
  if (!pending) return null

  const total = 5000
  const pct = Math.max(0, Math.min(100, (left / total) * 100))
  const mine = pending.actor === 'user'
  const waitingOnYou = pending.waiting_on === 'user'
  const played = pending.cards.map(cardTitle).join(' + ')

  return (
    <div className={`ek-nope-window ${waitingOnYou ? 'is-yours' : ''}`} role="status">
      <div className="ek-nope-bar" style={{ width: `${pct}%` }} aria-hidden />
      <div className="ek-nope-body">
        <p>
          <strong>{mine ? 'You' : 'Rau'}</strong> played {played}
          {pending.nopes > 0 && (
            <span className="ek-nope-count">
              {' '}
              · {pending.nopes} Nope{pending.nopes > 1 ? 's' : ''} deep, so it{' '}
              {pending.nopes % 2 ? 'will not' : 'will'} happen
            </span>
          )}
        </p>
        {waitingOnYou ? (
          <div className="ek-nope-actions">
            <button
              type="button"
              className="ek-btn ek-btn-nope"
              disabled={!table.can_nope}
              onClick={() => gameStore.play({ move: 'nope' })}
            >
              {table.can_nope ? 'NOPE' : 'No Nope in hand'}
            </button>
            <button
              type="button"
              className="ek-btn ek-btn-quiet"
              onClick={() => gameStore.play({ move: 'pass_nope' })}
            >
              Let it happen
            </button>
          </div>
        ) : (
          <p className="ek-nope-waiting">Waiting on Rau…</p>
        )}
      </div>
    </div>
  )
}

/** Where the defused kitten goes back. The only genuinely secret choice you make. */
function DefusePrompt({ table }: { table: TableState }) {
  const max = table.insert_max ?? table.deck_count
  const [index, setIndex] = useState(0)
  useEffect(() => setIndex(0), [table.game_id, max])
  return (
    <div className="ek-prompt ek-prompt-defuse">
      <h3>Defused. Now hide it.</h3>
      <p>
        Slide it back into the {max}-card deck. He does not get to see where it went —
        and neither will you, in a few turns.
      </p>
      <div className="ek-slider-row">
        <span>top</span>
        <input
          type="range"
          min={0}
          max={max}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
          aria-label="How deep to hide the Exploding Kitten"
        />
        <span>bottom</span>
      </div>
      <p className="ek-slider-value">
        {index === 0
          ? 'Right on top. He draws next.'
          : index >= max
            ? 'All the way at the bottom.'
            : `${index} card${index === 1 ? '' : 's'} down.`}
      </p>
      <button
        type="button"
        className="ek-btn ek-btn-primary"
        onClick={() => gameStore.play({ move: 'insert_kitten', index })}
      >
        Put it back
      </button>
    </div>
  )
}

function FavorPrompt({ table }: { table: TableState }) {
  return (
    <div className="ek-prompt">
      <h3>He asked for a favor.</h3>
      <p>Pick the one you can live without.</p>
      <div className="ek-prompt-cards">
        {table.hand.map((id, i) => (
          <CardButton
            key={`${id}-${i}`}
            id={id}
            index={i}
            onClick={() => gameStore.play({ move: 'give_favor', card: id })}
          />
        ))}
      </div>
    </div>
  )
}

function SalvagePrompt({ table }: { table: TableState }) {
  const options = [...new Set(table.discard)].filter((c) => c !== 'exploding_kitten')
  return (
    <div className="ek-prompt">
      <h3>Five different cards. Take anything.</h3>
      <div className="ek-prompt-cards">
        {options.map((id, i) => (
          <CardButton
            key={id}
            id={id}
            index={i}
            onClick={() => gameStore.play({ move: 'take_from_discard', card: id })}
          />
        ))}
      </div>
    </div>
  )
}

/** Naming a card for a three-of-a-kind. You are guessing; that is the game. */
function DemandPicker({
  cards,
  onCancel,
}: {
  cards: CardId[]
  onCancel: () => void
}) {
  const choices = Object.keys(CARD_META).filter((c) => c !== 'exploding_kitten') as CardId[]
  return (
    <div className="ek-prompt ek-prompt-demand">
      <h3>Name the card you want.</h3>
      <p>If he is holding one, it is yours. If not, you wasted three cards.</p>
      <div className="ek-demand-grid">
        {choices.map((id) => (
          <button
            key={id}
            type="button"
            className="ek-demand-chip"
            onClick={() => gameStore.play({ move: 'combo', cards, named_card: id })}
          >
            {CARD_META[id].title}
          </button>
        ))}
      </div>
      <button type="button" className="ek-btn ek-btn-quiet" onClick={onCancel}>
        Back
      </button>
    </div>
  )
}

function GameOver({ table }: { table: TableState }) {
  const won = table.winner === 'user'
  return (
    <div className={`ek-over ${won ? 'is-win' : 'is-loss'}`} role="alertdialog" aria-label="Game over">
      <div className="ek-over-card">
        <div className="ek-over-art">
          <Card id={won ? 'defuse' : 'exploding_kitten'} />
        </div>
        <h2>{won ? 'You win.' : 'You exploded.'}</h2>
        <p>{table.over_reason}</p>
        {table.final_hands && (
          <p className="ek-over-hands">
            He was holding: {table.final_hands.rau.map(cardTitle).join(', ') || 'nothing'}.
          </p>
        )}
        <div className="ek-over-actions">
          <button type="button" className="ek-btn ek-btn-primary" onClick={() => void gameStore.deal().catch(() => {})}>
            Deal again
          </button>
          <button type="button" className="ek-btn ek-btn-quiet" onClick={() => void gameStore.leave()}>
            Leave the table
          </button>
        </div>
      </div>
    </div>
  )
}

export default function GameTable() {
  const { table, busy, error } = useGame()
  const [selected, setSelected] = useState<number[]>([])
  const [demanding, setDemanding] = useState<CardId[] | null>(null)

  useEffect(() => {
    void gameStore.refresh()
  }, [])

  // A hand that changed under a selection makes the selection meaningless.
  useEffect(() => {
    setSelected([])
    setDemanding(null)
  }, [table?.hand.join(','), table?.phase])

  const toggle = useCallback((index: number) => {
    setSelected((prev) =>
      prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index],
    )
  }, [])

  const chosen = useMemo(
    () => (table ? selected.map((i) => table.hand[i]).filter(Boolean) : []),
    [table, selected],
  )

  const actions = useMemo(() => {
    if (!table || !table.your_turn || chosen.length === 0) return []
    const out: { label: string; hint: string; run: () => void }[] = []
    const allSame = chosen.every((c) => c === chosen[0])
    if (chosen.length === 1 && !NEVER_PLAYABLE_ALONE.has(chosen[0]) && CARD_META[chosen[0]].kind !== 'cat') {
      out.push({
        label: `Play ${CARD_META[chosen[0]].title}`,
        hint: CARD_META[chosen[0]].effect,
        run: () => void gameStore.play({ move: 'play', card: chosen[0] }),
      })
    }
    if (chosen.length === 2 && allSame) {
      out.push({
        label: 'Steal one at random',
        hint: 'Two of a kind. You do not get to choose which.',
        run: () => void gameStore.play({ move: 'combo', cards: chosen }),
      })
    }
    if (chosen.length === 3 && allSame) {
      out.push({
        label: 'Demand a card',
        hint: 'Three of a kind. Name it and take it, if he has it.',
        run: () => setDemanding(chosen),
      })
    }
    if (chosen.length === 5 && new Set(chosen).size === 5 && table.discard.length > 0) {
      out.push({
        label: 'Raid the discard pile',
        hint: 'Five different cards. Take anything off the pile.',
        run: () => void gameStore.play({ move: 'combo', cards: chosen }),
      })
    }
    return out
  }, [table, chosen])

  if (!table) return null

  const phase = table.phase
  const showHandActions = table.your_turn && phase === 'playing'

  return (
    <div className="ek-table" role="region" aria-label="Exploding Kittens">
      <CardDefs />

      <header className="ek-head">
        <div className="ek-turn">
          {phase === 'over' ? (
            <strong>Game over</strong>
          ) : table.your_turn ? (
            <strong>Your turn</strong>
          ) : (
            <strong className="ek-turn-his">Rau is thinking…</strong>
          )}
          {table.turns_to_take > 1 && phase !== 'over' && (
            <span className="ek-owed">{table.turns_to_take} turns owed</span>
          )}
        </div>
        <button
          type="button"
          className="ek-btn ek-btn-quiet ek-leave"
          onClick={() => void gameStore.leave()}
        >
          Leave
        </button>
      </header>

      <OpponentHand count={table.hand_counts.rau} thinking={!table.your_turn && phase !== 'over'} />

      <div className="ek-middle">
        <Pile table={table} />
        {table.known_top.length > 0 && (
          <div className="ek-future" aria-label="What you saw on top of the deck">
            <span className="ek-future-label">You saw:</span>
            {table.known_top.map((id, i) => (
              <div className="ek-card ek-card-mini" key={`${id}-${i}`}>
                <Card id={id} />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="ek-feed" aria-live="polite">
        {table.log.slice(-3).map((entry, i) => (
          <p key={`${entry.at}-${i}`} className={`ek-feed-line seat-${entry.seat}`}>
            {entry.text}
          </p>
        ))}
      </div>

      {phase === 'nope_window' && <NopeWindow table={table} />}
      {phase === 'awaiting_defuse' && table.awaiting_you && <DefusePrompt table={table} />}
      {phase === 'awaiting_favor' && table.awaiting_you && <FavorPrompt table={table} />}
      {phase === 'awaiting_discard_pick' && table.awaiting_you && <SalvagePrompt table={table} />}
      {demanding && <DemandPicker cards={demanding} onCancel={() => setDemanding(null)} />}

      {error && (
        <p className="ek-error" role="alert" onClick={() => gameStore.clearError()}>
          {error}
        </p>
      )}

      <div className="ek-hand ek-hand-mine" role="group" aria-label="Your hand">
        {table.hand.map((id, i) => (
          <CardButton
            key={`${id}-${i}`}
            id={id}
            index={i}
            count={table.hand.length}
            selected={selected.includes(i)}
            disabled={busy || !showHandActions}
            onClick={() => toggle(i)}
          />
        ))}
      </div>

      <footer className="ek-actions">
        {showHandActions && actions.length === 0 && selected.length > 0 && (
          <p className="ek-hint">
            {selected.length === 1
              ? 'That card does nothing on its own. Match it with another.'
              : 'Not a set. Two or three matching, or five all different.'}
          </p>
        )}
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            className="ek-btn ek-btn-primary"
            disabled={busy}
            onClick={action.run}
            title={action.hint}
          >
            {action.label}
          </button>
        ))}
        {showHandActions && (
          <button
            type="button"
            className="ek-btn ek-btn-draw"
            disabled={busy}
            onClick={() => void gameStore.play({ move: 'draw' })}
          >
            Draw &amp; end turn
          </button>
        )}
      </footer>

      {phase === 'over' && <GameOver table={table} />}
    </div>
  )
}
