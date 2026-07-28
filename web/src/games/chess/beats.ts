/**
 * Turning two positions into things his body does.
 *
 * The server does not send "Rau just took your bishop" — it sends the board,
 * whole, sometimes with a move and a reply and a phase change collapsed into
 * one push. So the beats are read out of the difference between two of those,
 * here, in one pure function that can be tested without a canvas or a socket
 * anywhere near it.
 *
 * Being wrong here is cheap and being late is not: a missed beat is a moment
 * he sat still, a wrong one is him slumping over a piece he just won.
 *
 * The temptation this file has to refuse is the one the whole feature is built
 * around. The client is now holding the entire position, so it *could* work
 * out that he has just walked into a mate in two and have him react to it.
 * Every number describing how the game is going stops at the engine layer on
 * purpose, and a client-side evaluation would be a hole straight through that.
 * What is read here is only what a person watching across the table could see:
 * a piece came off, a king is in check, a hand hesitated over a square.
 */

import type { GameVerb } from '../../clawd/gameBridge'
import { material } from './board'
import type { TableState } from './useGame'

/**
 * How much has to come off him before it lands as a blow rather than a trade.
 *
 * A pawn is nothing. A knight is the moment his shoulders go, and three is the
 * cheapest thing worth that much, so the threshold is a piece.
 */
const BLUNDER_PAWNS = 3

/**
 * What changed between two views of the board, as things he does about it.
 *
 * Order matters — they are played in sequence, and `blunder` clears whatever
 * is queued behind it — so the beats come out in the order they happened, with
 * the reaction to your move ahead of the move he answers with.
 */
export function diffBeats(prev: TableState | null, next: TableState): GameVerb[] {
  const out: GameVerb[] = []
  if (!prev || prev.game_id !== next.game_id) return out

  // ── you took something off him ─────────────────────────────────────
  // Counted from the two positions rather than read off the SAN, because a
  // capture is a capture whether it was announced with an `x` or arrived as
  // en passant. And netted against what came off you in the same push, which
  // matters because a push can carry both halves of an exchange: a knight for
  // a knight is a trade, and a man who slumped at every trade would be
  // exhausting to sit opposite.
  const his = material(prev.fen, prev.rau_color) - material(next.fen, next.rau_color)
  const yours = material(prev.fen, prev.user_color) - material(next.fen, next.user_color)
  if (his - yours >= BLUNDER_PAWNS) out.push('blunder')

  // ── he moved ───────────────────────────────────────────────────────
  // Sides alternate from whoever was to move in the position we last saw, so
  // a push carrying both halves of an exchange still attributes each half to
  // the right player.
  const landed = next.moves.slice(prev.moves.length)
  let mover = prev.turn
  for (const san of landed) {
    if (mover === next.rau_color) {
      out.push(san.includes('x') ? 'capture' : 'move')
      // After the piece is down, not instead of it: the lean is him watching
      // what he has just done to you.
      if (san.includes('+') || san.includes('#')) out.push('check')
    }
    mover = mover === 'white' ? 'black' : 'white'
  }

  // ── he is thinking ─────────────────────────────────────────────────
  // Only when nothing of his landed in this push. A move that arrived has
  // already ended the pause it came out of, and playing the chin-rest after
  // the piece is down would have him considering a move he has made.
  if (landed.length === 0) {
    const was = prev.thinking?.hover ?? null
    const now = next.thinking?.hover ?? null
    if (next.phase === 'thinking' && prev.phase !== 'thinking') out.push('think')
    if (now && now !== was) out.push('hover')
    else if (was && !now && next.phase === 'thinking') out.push('pull')
  }

  // ── the end ────────────────────────────────────────────────────────
  // A draw gets nothing. Neither of the two endings is honest about it, and
  // the right body for a game that fizzled out is the one he already has.
  if (next.phase === 'over' && prev.phase !== 'over') {
    if (next.winner === 'rau') out.push('cheer')
    else if (next.winner === 'user') out.push('slump')
  }

  return out
}
