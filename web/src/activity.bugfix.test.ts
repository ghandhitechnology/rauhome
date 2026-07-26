import { describe, expect, it } from 'vitest'
import { trimActivitySpans } from './activity'
import type { ActivitySpan } from './api'

const base = {
  id: 'a',
  seq: 1,
  revision: 1,
  kind: 'execution',
  source: 'test',
  status: 'running',
  label: 'Working',
  summary: '',
  details: {},
  started: 1,
  updated: 1,
} satisfies ActivitySpan

function storeOf(seqs: number[]): Map<string, ActivitySpan> {
  const store = new Map<string, ActivitySpan>()
  for (const seq of seqs) store.set(`s${seq}`, { ...base, id: `s${seq}`, seq })
  return store
}

describe('activity store eviction', () => {
  it('drops the oldest spans by seq once the store grows past the cap', () => {
    const store = storeOf([1, 2, 3, 4, 5, 6, 7, 8])
    expect(trimActivitySpans(store, 6)).toBe(true)
    expect([...store.keys()]).toEqual(['s3', 's4', 's5', 's6', 's7', 's8'])
  })

  it('is a no-op at or below the cap', () => {
    const store = storeOf([1, 2])
    expect(trimActivitySpans(store, 2)).toBe(false)
    expect([...store.keys()]).toEqual(['s1', 's2'])
  })

  it('evicts by seq rather than insertion order, so late-arriving old spans go first', () => {
    // A hydrated span with an old seq can land after newer live ones.
    const store = storeOf([5, 6, 7, 8])
    store.set('s2', { ...base, id: 's2', seq: 2 })
    expect(trimActivitySpans(store, 4)).toBe(true)
    expect([...store.keys()]).toEqual(['s5', 's6', 's7', 's8'])
  })
})
