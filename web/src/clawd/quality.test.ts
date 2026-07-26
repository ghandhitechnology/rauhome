import { beforeEach, describe, expect, it } from 'vitest'

import roomSource from './room.ts?raw'
import classicSource from './roomClassic.ts?raw'
import sceneSource from './scene.ts?raw'
import textureSource from './texture.ts?raw'

import { clearTier, currentTier, quality, setTier, tierIsAutomatic } from './quality'

describe('the quality tiers', () => {
  beforeEach(() => clearTier())

  it('starts out judging the machine for itself', () => {
    expect(tierIsAutomatic()).toBe(true)
    expect(['low', 'balanced', 'high']).toContain(currentTier())
  })

  it('takes the user at their word over the machine', () => {
    setTier('low')
    expect(currentTier()).toBe('low')
    expect(tierIsAutomatic()).toBe(false)
    setTier('high')
    expect(currentTier()).toBe('high')
    clearTier()
    expect(tierIsAutomatic()).toBe(true)
  })

  it('spends strictly less at each step down', () => {
    setTier('high')
    const high = quality()
    setTier('balanced')
    const mid = quality()
    setTier('low')
    const low = quality()

    for (const count of ['motes', 'stars', 'clouds'] as const) {
      expect(high[count], count).toBeGreaterThanOrEqual(mid[count])
      expect(mid[count], count).toBeGreaterThanOrEqual(low[count])
    }
    // The costly per-pixel passes are the first thing a slow machine drops.
    expect(low.textures).toBe(false)
    expect(low.grain).toBe(false)
    expect(low.stains).toBe(false)
  })

  it('is only ever asked for a budget it actually spends', () => {
    // A field nothing reads is an API that lies: the comment promises a
    // behaviour and the tier appears to control something it does not.
    const fields = Object.keys(quality()).filter((f) => f !== 'tier')
    const source = [roomSource, classicSource, textureSource, sceneSource].join('\n')
    for (const field of fields) {
      // Read either straight off the call or off a local holding the budget,
      // so this notices a dead field without dictating the calling style.
      expect(source, `nothing reads the ${field} budget`).toMatch(
        new RegExp(`(quality\\(\\)|budget)\\.${field}\\b`),
      )
    }
  })
})
