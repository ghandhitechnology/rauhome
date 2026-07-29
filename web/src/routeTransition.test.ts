import { describe, expect, it } from 'vitest'
import {
  centerOf,
  rippleRadius,
  roomTransitionBetween,
} from './routeTransition'

const launcher = {
  left: 820,
  top: 40,
  width: 260,
  height: 130,
}

describe('room route transition geometry', () => {
  it('uses the launcher center for history-driven room entry', () => {
    expect(roomTransitionBetween('/', '/face', launcher)).toEqual({
      kind: 'room-open',
      origin: { x: 950, y: 105 },
    })
  })

  it('reverses only for the direct room-to-talk path', () => {
    expect(roomTransitionBetween('/face', '/')).toEqual({ kind: 'room-close' })
    expect(roomTransitionBetween('/face/', '/')).toEqual({ kind: 'room-close' })
    expect(roomTransitionBetween('/face', '/settings')).toBeUndefined()
    expect(roomTransitionBetween('/', '/dashboard', launcher)).toBeUndefined()
  })

  it('covers the farthest viewport corner from the chosen origin', () => {
    const origin = centerOf(launcher)
    expect(rippleRadius(origin, 1280, 720)).toBeCloseTo(
      Math.hypot(950, 615),
    )
  })
})
