import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import type { StepProps } from './types'
import { useLocale } from '../../i18n'

type TaskState = 'pending' | 'running' | 'done' | 'failed'
type Task = { id: string; label: string; state: TaskState; detail?: string }

const BASE_TASKS: Task[] = [
  { id: 'models', label: 'Assigning models to face, subagent and dream', state: 'pending' },
  { id: 'sources', label: 'Writing identity.md and backstory.md', state: 'pending' },
  { id: 'soul', label: 'Distilling soul.md with DeepSeek V4 Pro', state: 'pending' },
  { id: 'verify', label: 'Confirming Rau can boot', state: 'pending' },
]

/** Minimum time a step is shown, so the sequence stays readable when calls are instant. */
const BEAT = 420

export default function StepForge({
  draft,
  state,
  reload,
  onForged,
}: StepProps & { onForged: (soul: string) => void }) {
  const { locale } = useLocale()
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
          if (!res?.soul) throw new Error('The hub returned an empty soul.md.')
          await wait(120)
        })

        await run('verify', async () => {
          const s = await api.setupState()
          if (!s.identity_ready) throw new Error('soul.md was not written.')
          await reload()
        })

        await wait(360)
        onForged(res.soul || '')
      } catch (e: any) {
        setError(e?.message || String(e))
      }
    })()
  }, [attempt, draft, state, reload, onForged])

  return (
    <div className="step step-center">
      <header className="step-head">
        <p className="eyebrow">{locale === 'ko' ? '거의 다 됐어요' : 'Almost'}</p>
        <h2>{locale === 'ko' ? 'Rau를 깨우는 중' : 'Bringing Rau up'}</h2>
        <p className="step-lede">{locale === 'ko' ? '파일을 쓰고, 모델을 연결하고, Rau의 자아를 완성하고 있습니다.' : 'Writing files, wiring models, and compiling the operating self.'}</p>
      </header>

      <ol className="forge-list">
        {tasks.map((t, i) => (
          <li key={t.id} className={`forge-task ${t.state}`} style={{ '--i': i } as React.CSSProperties}>
            <span className="forge-icon">
              {t.state === 'running' && <i className="spinner" />}
              {t.state === 'done' && <i className="tick" />}
              {t.state === 'failed' && <i className="cross" />}
              {t.state === 'pending' && <i className="dot" />}
            </span>
            <span className="forge-label">
              {t.label}
              {t.detail && <em className="forge-detail">{t.detail}</em>}
            </span>
          </li>
        ))}
      </ol>

      {error && (
        <div className="notice bad" style={{ marginTop: '1.25rem' }}>
          <strong>{locale === 'ko' ? '작업을 마치지 못했습니다.' : 'That did not finish.'}</strong>
          <p style={{ margin: '0.35rem 0 0' }}>{error}</p>
          <div className="row" style={{ marginTop: '0.8rem' }}>
            <button
              className="btn sm"
              onClick={() => {
                setError('')
                setTasks(BASE_TASKS.map((t) => ({ ...t, state: 'pending' as TaskState })))
                setAttempt((a) => a + 1)
              }}
            >
              {locale === 'ko' ? '다시 시도' : 'Try again'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
