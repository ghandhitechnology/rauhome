import { describe, expect, it } from 'vitest'
import { activityFor, activityFromEvent } from './activity'
import type { ActivitySpan } from './api'

describe('activity plane', () => {
  it('normalizes websocket activity without confusing the event kind and span kind', () => {
    const span = activityFromEvent({
      kind: 'activity_started',
      activity_kind: 'reasoning',
      id: 'span',
      seq: 4,
      revision: 1,
      status: 'running',
      source: 'anthropic',
      label: 'Reasoning',
      summary: 'Checking the result',
      details: {},
      turn_id: 'turn',
      ts: 10,
    })
    expect(span?.kind).toBe('reasoning')
    expect(span?.turn_id).toBe('turn')
  })

  it('keeps foreground turn activity separate from unrelated scheduled work', () => {
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
    const spans: ActivitySpan[] = [
      { ...base, id: 'foreground', turn_id: 'turn-1', job_id: 'job-1' },
      { ...base, id: 'scheduled', seq: 2, job_id: 'schedule-job' },
    ]
    expect(activityFor(spans, { turnId: 'turn-1' }).map((item) => item.id)).toEqual([
      'foreground',
    ])
    expect(activityFor(spans, { global: true })).toHaveLength(2)
  })
})
