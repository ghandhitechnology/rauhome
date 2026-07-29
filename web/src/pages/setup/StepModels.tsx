import type { StepProps, SlotDraft } from './types'
import { useLocale } from '../../i18n'

type SlotKey = 'face' | 'subagent' | 'dream'

export default function StepModels({ draft, patch, state, catalog }: StepProps) {
  const { locale } = useLocale()
  const configured = new Set(state?.configured || [])
  const providerAuth = catalog?.provider_auth || {}

  // Only offer providers whose key is actually present.
  const usable = Object.keys(catalog?.providers || {}).filter((p) => {
    const authId = providerAuth[p]
    return authId && configured.has(authId)
  })

  function setSlot(slot: SlotKey, next: Partial<SlotDraft>) {
    patch({ slots: { ...draft.slots, [slot]: { ...draft.slots[slot], ...next } } })
  }

  function pickProvider(slot: SlotKey, provider: string) {
    const first = catalog?.providers?.[provider]?.models?.[0]?.id || ''
    setSlot(slot, { provider, model: first })
  }

  /** One click to a working config — the common case for a first run. */
  function autoAssign() {
    const best = usable.includes('openrouter') ? 'openrouter' : usable[0]
    if (!best) return
    const models = catalog?.providers?.[best]?.models || []
    const fast = models[0]?.id || ''
    const smart = models[1]?.id || fast
    patch({
      slots: {
        face: { provider: best, model: fast },
        subagent: { provider: best, model: smart },
        dream: { provider: best, model: smart },
      },
    })
  }

  const slotMeta = catalog?.slots || []

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">{locale === 'ko' ? '네 번째 단계' : 'Step four'}</p>
        <h2>{locale === 'ko' ? '역할을 나눠 주세요' : 'Split the work'}</h2>
        <p className="step-lede">
          {locale === 'ko'
            ? '대화, 하위 에이전트, 꿈에 사용할 모델을 정합니다. 모두 같아도 되지만 대화는 속도, 하위 에이전트는 깊이가 중요합니다.'
            : 'Three jobs, three model choices. They can all be the same model — but the face wants speed and the subagent wants patience.'}
        </p>
      </header>

      {usable.length === 0 ? (
        <div className="notice bad">
          {locale === 'ko' ? '연결된 제공자가 없습니다. 이전 단계에서 키를 하나 연결해 주세요.' : 'No connected provider yet. Go back a step and connect one key first.'}
        </div>
      ) : (
        <>
          <div className="row" style={{ marginBottom: '1.1rem' }}>
            <button className="btn sm" onClick={autoAssign}>
              {locale === 'ko' ? '알맞은 기본값 자동 배정' : 'Auto-assign sensible defaults'}
            </button>
          </div>

          <div className="slot-list">
            {(['face', 'subagent', 'dream'] as SlotKey[]).map((slot, i) => {
              const meta = slotMeta.find((s) => s.id === slot)
              const cur = draft.slots[slot]
              const models = catalog?.providers?.[cur.provider]?.models || []
              const isCustom = !!cur.model && !models.some((m) => m.id === cur.model)
              const ready = !!cur.provider && !!cur.model
              return (
                <article
                  key={slot}
                  className={`slot-card ${ready ? 'ready' : ''}`}
                  style={{ '--i': i } as React.CSSProperties}
                >
                  <div className="slot-head">
                    <div>
                      <h3>{meta?.label || slot}</h3>
                      <p className="slot-blurb">{meta?.blurb}</p>
                    </div>
                    <span className={`pill ${ready ? 'on' : 'off'}`}>
                      <i className="pill-dot" />
                      {ready ? 'set' : 'unset'}
                    </span>
                  </div>

                  <div className="slot-fields">
                    <div className="field">
                      <label>{locale === 'ko' ? '제공자' : 'Provider'}</label>
                      <select
                        value={cur.provider}
                        onChange={(e) => pickProvider(slot, e.target.value)}
                      >
                        <option value="">choose…</option>
                        {usable.map((p) => (
                          <option key={p} value={p}>
                            {catalog?.providers?.[p]?.label || p}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="field">
                      <label>{locale === 'ko' ? '모델' : 'Model'}</label>
                      <select
                        value={isCustom ? '__custom' : cur.model}
                        disabled={!cur.provider}
                        onChange={(e) =>
                          setSlot(slot, {
                            model: e.target.value === '__custom' ? '' : e.target.value,
                          })
                        }
                      >
                        <option value="">choose…</option>
                        {models.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                            {m.note ? ` — ${m.note}` : ''}
                          </option>
                        ))}
                        <option value="__custom">Custom model id…</option>
                      </select>
                    </div>
                  </div>

                  {(isCustom || (cur.provider && !cur.model)) && (
                    <div className="field" style={{ marginBottom: 0 }}>
                      <label>Custom model id</label>
                      <input
                        value={cur.model}
                        placeholder="exact id as the provider spells it"
                        onChange={(e) => setSlot(slot, { model: e.target.value })}
                      />
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
