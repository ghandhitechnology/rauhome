import { describe, expect, it } from 'vitest'

import {
  FULL_RATE,
  IDLE_AFTER_MS,
  IDLE_RATE,
  isIdle,
  noteActivity,
  pacingFor,
  setIdleForTests,
} from './activity'

describe('activity pacing', () => {
  it('starts awake and runs at the display rate', () => {
    noteActivity()
    expect(isIdle()).toBe(false)
    expect(pacingFor({ table: false, profile: 'balanced' })).toBe(FULL_RATE)
    expect(pacingFor({ table: false, profile: 'performance' })).toBe(FULL_RATE)
  })

  it('drops to the quiet rate only after five idle minutes', () => {
    setIdleForTests(IDLE_AFTER_MS - 1000)
    expect(isIdle()).toBe(false)
    expect(pacingFor({ table: false, profile: 'balanced' })).toBe(FULL_RATE)

    setIdleForTests(IDLE_AFTER_MS + 1000)
    expect(isIdle()).toBe(true)
    expect(pacingFor({ table: false, profile: 'balanced' })).toBe(IDLE_RATE)
  })

  it('wakes the moment anything notes activity', () => {
    setIdleForTests(IDLE_AFTER_MS * 2)
    expect(isIdle()).toBe(true)
    noteActivity()
    expect(isIdle()).toBe(false)
    expect(pacingFor({ table: false, profile: 'balanced' })).toBe(FULL_RATE)
  })

  it('always gives the card table the display rate, even idle', () => {
    setIdleForTests(IDLE_AFTER_MS * 2)
    expect(pacingFor({ table: true, profile: 'balanced' })).toBe(FULL_RATE)
  })

  it('honours an explicit eco profile even mid-conversation', () => {
    noteActivity()
    expect(pacingFor({ table: false, profile: 'eco' })).toBe(IDLE_RATE)
    // …but never overrules a game in hand.
    expect(pacingFor({ table: true, profile: 'eco' })).toBe(FULL_RATE)
  })
})
