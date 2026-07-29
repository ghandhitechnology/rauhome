/// <reference types="node" />
import { readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { TOUR_STEPS } from './tutorial'

afterEach(() => vi.restoreAllMocks())

describe('bilingual onboarding', () => {
  it('persists the selected reply language through the public API', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(Response.json({ ok: true, language: 'ko' }))

    await expect(api.putLanguage('ko')).resolves.toMatchObject({ language: 'ko' })
    expect(fetch).toHaveBeenCalledWith(
      '/api/preferences/language',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ language: 'ko' }),
      }),
    )
  })

  it('keeps the guided path at seven steps in Room → Work → Talk order', () => {
    expect(TOUR_STEPS).toHaveLength(7)
    expect(TOUR_STEPS.map((step) => step.route)).toEqual([
      '/face',
      '/face',
      '/face',
      '/dashboard',
      '/dashboard',
      '/',
      '/',
    ])
    expect(TOUR_STEPS.filter((step) => step.action === 'target')).toHaveLength(4)
  })

  it('ships optimized colored-pencil art and archival sources for all three pages', () => {
    for (const name of ['dreaming', 'deep-work', 'presence']) {
      const webp = resolve('public/onboarding', `${name}-colored-pencil.webp`)
      const png = resolve('public/onboarding/source', `${name}-colored-pencil.png`)
      expect(readFileSync(webp, { encoding: null }).subarray(0, 4).toString()).toBe('RIFF')
      expect(readFileSync(png, { encoding: null }).subarray(1, 4).toString()).toBe('PNG')
      expect(statSync(webp).size).toBeLessThan(statSync(png).size)
    }
  })
})
