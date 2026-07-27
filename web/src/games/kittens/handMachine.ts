/**
 * What the hand you are holding is currently doing.
 *
 * Two ways to play a card share one gesture, and the whole reason this is a
 * reducer rather than a scatter of `useState` is that they have to be told
 * apart from the same pointer stream. Press and move past a few pixels and
 * you are dragging the card to the pile; press and let go without moving and
 * you are raising it to read it. Neither is a mode you enter deliberately —
 * you just do one or the other and the card understands.
 *
 * Nothing here decides what is *legal*. The server already did; the raised
 * card only reads back flags it was handed.
 */

export type Pt = { x: number; y: number }

/** A choice that has to be made on the raised card before it can be played. */
export type Picker = 'none' | 'demand' | 'defuse' | 'favor'

export type HandState =
  | { mode: 'idle' }
  /** Pointer is down but has not travelled far enough to be a drag yet. */
  | { mode: 'pressed'; index: number; origin: Pt }
  | { mode: 'dragging'; index: number; at: Pt; overDiscard: boolean }
  /** Held up, big enough to read, with any follow-up choice on the card. */
  | { mode: 'raised'; indices: number[]; picker: Picker }
  /** A move is in flight. The fan is locked until the server answers. */
  | { mode: 'confirming'; indices: number[]; picker: Picker }

export type HandEvent =
  | { type: 'press'; index: number; at: Pt }
  | { type: 'move'; at: Pt; overDiscard: boolean }
  | {
      type: 'release'
      /** Whether the pointer came up over the discard pile. */
      overDiscard: boolean
      /** A choice this card needs before it can resolve, if any. */
      needsPicker?: Picker
    }
  /** Raise a card without a gesture — the server is asking for one. */
  | { type: 'raise'; indices: number[]; picker?: Picker }
  /** Add or remove a card from the raised set, building a pair or a run. */
  | { type: 'raiseAdd'; index: number }
  | { type: 'picker'; picker: Picker }
  | { type: 'confirm' }
  | { type: 'cancel' }
  | { type: 'resolved'; ok: boolean }
  /** The hand changed underneath us, so whatever was selected is meaningless. */
  | { type: 'reset' }

export const IDLE_HAND: HandState = { mode: 'idle' }

/**
 * How far the pointer must travel before a press becomes a drag.
 *
 * Small enough that dragging feels immediate, large enough that a click with
 * a shaky hand or a trackpad is still a click.
 */
export const DRAG_THRESHOLD = 8

function distance(a: Pt, b: Pt): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

export function handReducer(state: HandState, event: HandEvent): HandState {
  switch (event.type) {
    case 'reset':
      return IDLE_HAND

    case 'press':
      // A press while something is already raised is handled by `raiseAdd`;
      // starting a fresh press abandons the old selection.
      if (state.mode === 'confirming') return state
      return { mode: 'pressed', index: event.index, origin: event.at }

    case 'move':
      if (state.mode === 'pressed') {
        if (distance(state.origin, event.at) < DRAG_THRESHOLD) return state
        return {
          mode: 'dragging',
          index: state.index,
          at: event.at,
          overDiscard: event.overDiscard,
        }
      }
      if (state.mode === 'dragging') {
        if (state.at.x === event.at.x && state.at.y === event.at.y && state.overDiscard === event.overDiscard) {
          return state
        }
        return { ...state, at: event.at, overDiscard: event.overDiscard }
      }
      return state

    case 'release':
      // Below the threshold the whole gesture was a click: raise it to read.
      if (state.mode === 'pressed') {
        return { mode: 'raised', indices: [state.index], picker: 'none' }
      }
      if (state.mode === 'dragging') {
        if (!event.overDiscard) return IDLE_HAND
        const picker = event.needsPicker ?? 'none'
        // Dropped, but the card wants to know something first — the choice
        // opens over the pile rather than throwing the card back.
        if (picker !== 'none') {
          return { mode: 'raised', indices: [state.index], picker }
        }
        return { mode: 'confirming', indices: [state.index], picker: 'none' }
      }
      return state

    case 'raise':
      if (state.mode === 'confirming') return state
      return { mode: 'raised', indices: [...event.indices], picker: event.picker ?? 'none' }

    case 'raiseAdd': {
      if (state.mode !== 'raised') return state
      const has = state.indices.includes(event.index)
      const indices = has
        ? state.indices.filter((i) => i !== event.index)
        : [...state.indices, event.index]
      if (indices.length === 0) return IDLE_HAND
      // Changing the set invalidates a choice made about the old one.
      return { mode: 'raised', indices, picker: 'none' }
    }

    case 'picker':
      if (state.mode !== 'raised') return state
      return { ...state, picker: event.picker }

    case 'confirm':
      if (state.mode !== 'raised') return state
      return { mode: 'confirming', indices: state.indices, picker: state.picker }

    case 'cancel':
      if (state.mode === 'confirming') return state
      return IDLE_HAND

    case 'resolved':
      if (state.mode !== 'confirming') return state
      // A refusal goes back to the raised card holding the same cards, so the
      // server's reason lands next to the thing it is about.
      return event.ok ? IDLE_HAND : { mode: 'raised', indices: state.indices, picker: state.picker }

    default:
      return state
  }
}

/** Cards currently held up, in hand order. Empty unless something is raised. */
export function raisedIndices(state: HandState): number[] {
  if (state.mode === 'raised' || state.mode === 'confirming') return state.indices
  return []
}

/** Whether the fan should refuse input this frame. */
export function handLocked(state: HandState): boolean {
  return state.mode === 'confirming'
}
