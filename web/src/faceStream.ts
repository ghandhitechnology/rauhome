/**
 * Face reply stream — same `/ws` chat_* events Conversation uses, reduced to
 * a small state machine the room can paint without racing refresh()/voice.
 */

export type FaceStreamPhase = 'off' | 'wait' | 'live' | 'done'

export type FaceStream = {
  turnId: string
  text: string
  phase: FaceStreamPhase
}

export const IDLE_FACE_STREAM: FaceStream = {
  turnId: '',
  text: '',
  phase: 'off',
}

export type FaceStreamEvent = {
  kind: string
  turn_id?: unknown
  text?: unknown
}

/** Apply one hub chat_* event. Unrelated kinds leave state unchanged. */
export function reduceFaceStream(
  prev: FaceStream,
  event: FaceStreamEvent,
): FaceStream {
  const turnId = typeof event.turn_id === 'string' ? event.turn_id : ''
  const text = typeof event.text === 'string' ? event.text : ''

  switch (event.kind) {
    case 'chat_started':
      return { turnId, text: '', phase: 'wait' }
    case 'chat_delta': {
      if (prev.phase !== 'off' && prev.turnId && turnId && prev.turnId !== turnId) {
        return prev
      }
      return {
        turnId: turnId || prev.turnId,
        text,
        phase: text.trim() ? 'live' : 'wait',
      }
    }
    case 'chat_done': {
      if (prev.phase !== 'off' && prev.turnId && turnId && prev.turnId !== turnId) {
        return prev
      }
      return {
        turnId: turnId || prev.turnId,
        text,
        phase: text.trim() ? 'done' : 'off',
      }
    }
    case 'chat_error': {
      if (prev.phase === 'off') return prev
      if (turnId && prev.turnId && prev.turnId !== turnId) return prev
      return IDLE_FACE_STREAM
    }
    default:
      return prev
  }
}

/** True once the polled log has caught up with a finished stream. */
export function streamCaughtUp(stream: FaceStream, logText: string | null | undefined) {
  if (stream.phase !== 'done' || !stream.text.trim()) return false
  return String(logText || '').trim() === stream.text.trim()
}

/**
 * Word-by-word reveal for the character bubble: while the model is still
 * streaming, hold back the trailing incomplete word so the bubble jumps in
 * whole words rather than character trickle.
 */
export function revealCompleteWords(text: string, done: boolean): string {
  if (done || !text) return text
  try {
    const segmenter = new Intl.Segmenter(undefined, { granularity: 'word' })
    const parts = [...segmenter.segment(text)]
    let end = parts.length
    if (end > 0 && parts[end - 1].isWordLike) end -= 1
    return parts
      .slice(0, end)
      .map((part) => part.segment)
      .join('')
  } catch {
    // No Segmenter: drop the trailing run of non-space (incomplete word).
    return text.replace(/\S+$/, '')
  }
}

/** Text the Face bubble should show for the current stream phase. */
export function bubbleSpeechFromStream(stream: FaceStream): string | null {
  if (stream.phase === 'off' || stream.phase === 'wait') return null
  const done = stream.phase === 'done'
  const shown = revealCompleteWords(stream.text, done).trimEnd()
  if (!shown && !done) return null
  return done ? stream.text : shown
}
