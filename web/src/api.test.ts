import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

/** A fetch that always fails with the given body. */
function failing(body: string, status = 500) {
  return vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(body, { status, statusText: 'Server Error' }))
}

afterEach(() => vi.restoreAllMocks())

describe('api error surfaces', () => {
  it('uses the lightweight health route for conversation state', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({
        ok: true,
        timestamp: 1,
        listening: false,
        face_busy: false,
        hard_task: null,
        confirm: null,
        scheduler: { running: false },
      }),
    )
    await expect(api.health()).resolves.toMatchObject({ ok: true, timestamp: 1 })
    expect(fetch).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ headers: expect.any(Object) }),
    )
  })

  it('unwraps a JSON detail instead of throwing raw response text', async () => {
    failing(JSON.stringify({ detail: 'Permission mode is managed elsewhere' }))
    await expect(api.getPermissions()).rejects.toThrow(
      'Permission mode is managed elsewhere',
    )
  })

  it('unwraps a JSON error field', async () => {
    failing(JSON.stringify({ error: 'no such job' }), 404)
    await expect(api.job('missing')).rejects.toThrow('no such job')
  })

  it('keeps a plain-text error as it is', async () => {
    failing('boom')
    await expect(api.status()).rejects.toThrow('boom')
  })

  it('falls back to the status text on an empty body', async () => {
    failing('')
    await expect(api.status()).rejects.toThrow('Server Error')
  })
})
