import { beforeEach, describe, expect, it } from 'vitest'

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

  it('keeps the lighting at every tier, because flat light reads as broken', () => {
    for (const tier of ['low', 'balanced', 'high'] as const) {
      setTier(tier)
      expect(quality().volumetrics, tier).toBe(true)
    }
  })
})
