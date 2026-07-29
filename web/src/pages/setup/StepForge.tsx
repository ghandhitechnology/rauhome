import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { StepProps } from './types'
import { useLocale } from '../../i18n'

type TaskState = 'pending' | 'running' | 'done' | 'failed'
type Task = { id: (typeof TASK_IDS)[number]; state: TaskState; detail?: string }

const TASK_IDS = ['models', 'sources', 'soul', 'verify'] as const

const BASE_TASKS: Task[] = TASK_IDS.map((id) => ({ id, state: 'pending' }))

/** Minimum time a step is shown, so the sequence stays readable when calls are instant. */
const BEAT = 420

export default function StepForge({
  draft,
  state,
  reload,
  onForged,
}: StepProps & { onForged: (soul: string) => void }) {
  const { t } = useLocale()
  const [tasks, setTasks] = useState<Task[]>(BASE_TASKS)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const ranFor = useRef(-1)

  useEffect(() => {
    // Deps change on every reload; only run once per attempt.
    if (ranFor.current === attempt) return
    ranFor.current = attempt

    const set = (id: string, patch: Partial<Task>) =>
      setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))
    const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

    async function run<T>(id: string, fn: () => Promise<T>): Promise<T> {
      set(id, { state: 'running' })
      const t0 = performance.now()
      try {
        const result = await fn()
        const elapsed = performance.now() - t0
        if (elapsed < BEAT) await wait(BEAT - elapsed)
        set(id, { state: 'done' })
        return result
      } catch (e: any) {
        set(id, { state: 'failed', detail: e?.message || String(e) })
        throw e
      }
    }

    ;(async () => {
      try {
        await run('models', async () => {
          const payload: Record<string, unknown> = {}
          for (const slot of ['face', 'subagent', 'dream'] as const) {
            const s = draft.slots[slot]
            if (s.provider && s.model) payload[slot] = { provider: s.provider, model: s.model }
          }
          if (state?.configured?.includes(draft.tts.provider)) payload.tts = draft.tts
          payload.stt = draft.stt
          if (Object.keys(payload).length) await api.putModels(payload)
        })

        const res = await run('sources', async () =>
          draft.origin === 'guided'
            ? api.hard(draft.identity, draft.backstory)
            : api.fresh(),
        )

        await run('soul', async () => {
          if (!res?.soul) throw new Error(t('forge.emptySoul'))
          await wait(120)
        })

        await run('verify', async () => {
          const s = await api.setupState()
          if (!s.identity_ready) throw new Error(t('forge.noSoul'))
          await reload()
        })

        await wait(360)
        onForged(res.soul || '')
      } catch (e: any) {
        setError(e?.message || String(e))
      }
    })()
  }, [attempt, draft, state, reload, onForged, t])

  return (
    <div className="step step-center">
      <header className="step-head">
        <p className="eyebrow">{t('forge.eyebrow')}</p>
        <h2>{t('forge.title')}</h2>
        <p className="step-lede">{t('forge.lede')}</p>
      </header>

      <ol className="forge-list">
        {tasks.map((task, i) => (
          <li
            key={task.id}
            className={`forge-task ${task.state}`}
            style={{ '--i': i } as React.CSSProperties}
          >
            <span className="forge-icon">
              {task.state === 'running' && <i className="spinner" />}
              {task.state === 'done' && <i className="tick" />}
              {task.state === 'failed' && <i className="cross" />}
              {task.state === 'pending' && <i className="dot" />}
            </span>
            <span className="forge-label">
              {t(`forge.${task.id}`)}
              {task.detail && <em className="forge-detail">{task.detail}</em>}
            </span>
          </li>
        ))}
      </ol>

      {error && (
        <div className="notice bad" style={{ marginTop: '1.25rem' }}>
          <strong>{t('forge.failed')}</strong>
          <p style={{ margin: '0.35rem 0 0' }}>{error}</p>
          <div className="row" style={{ marginTop: '0.8rem' }}>
            <button
              className="btn sm"
              onClick={() => {
                setError('')
                setTasks(BASE_TASKS.map((task) => ({ ...task, state: 'pending' as TaskState })))
                setAttempt((a) => a + 1)
              }}
            >
              {t('forge.retry')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
