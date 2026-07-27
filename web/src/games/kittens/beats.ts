/**
 * Turning table state into things his body does.
 *
 * The server does not send "Rau just drew a card" — it sends the whole table,
 * redacted, sometimes with several changes collapsed into one push. So the
 * beats are read out of the difference between two of those, here, in one
 * pure function that can be tested without a canvas or a socket anywhere near
 * it.
 *
 * Being wrong here is cheap and being late is not: a missed beat is a moment
 * he sat still, a wrong one is him celebrating your win.
 */

import type { GameVerb } from '../../clawd/gameBridge'
import type { TableState } from './useGame'

/**
 * What changed between two views of the table, as things he does about it.
 *
 * Order matters — they are played in sequence — so the beats come out in the
 * order they would have happened.
 */
export function diffBeats(prev: TableState | null, next: TableState): GameVerb[] {
  const out: GameVerb[] = []
  if (!prev || prev.game_id !== next.game_id) return out

  // ── he drew ────────────────────────────────────────────────────────
  // Both halves are required: his hand also grows on a Favor, and that is a
  // different gesture entirely.
  if (next.hand_counts.rau > prev.hand_counts.rau && next.deck_count < prev.deck_count) {
    out.push('draw')
  }

  // ── he played ──────────────────────────────────────────────────────
  // The discard grew and it was his turn when it did. Attack gets its own
  // beat because he should look pleased with himself about that one
  // specifically.
  if (next.discard.length > prev.discard.length && prev.current === 'rau') {
    const played = next.discard.slice(prev.discard.length)
    out.push(played.includes('attack') ? 'attack' : 'play')
  }

  // ── he Noped ───────────────────────────────────────────────────────
  // The count went up while the table was waiting on him to answer.
  const prevNopes = prev.pending?.nopes ?? 0
  const nextNopes = next.pending?.nopes ?? 0
  if (nextNopes > prevNopes && prev.pending?.waiting_on === 'rau') {
    out.push('nope')
  }

  // ── the kitten ─────────────────────────────────────────────────────
  const hisDefuse = (t: TableState) =>
    t.phase === 'awaiting_defuse' && t.awaiting_seat === 'rau'
  if (hisDefuse(next) && !hisDefuse(prev)) {
    out.push('kitten')
  } else if (hisDefuse(prev) && !hisDefuse(next) && !next.winner) {
    // He was holding one and is not out, so it worked.
    out.push('defuse')
  }

  // ── the end ────────────────────────────────────────────────────────
  if (next.winner && !prev.winner) {
    out.push(next.winner === 'rau' ? 'cheer' : 'slump')
  }

  return out
}
