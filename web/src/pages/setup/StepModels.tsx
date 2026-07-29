import type { StepProps, SlotDraft } from './types'
import { useLocale } from '../../i18n'

type SlotKey = 'face' | 'subagent' | 'dream'

export default function StepModels({ draft, patch, state, catalog }: StepProps) {
  const { t } = useLocale()
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
        <p className="eyebrow">{t('models.eyebrow')}</p>
        <h2>{t('models.title')}</h2>
        <p className="step-lede">{t('models.lede')}</p>
      </header>

      {usable.length === 0 ? (
        <div className="notice bad">
          {t('models.noProvider')}
        </div>
      ) : (
        <>
          <div className="row" style={{ marginBottom: '1.1rem' }}>
            <button className="btn sm" onClick={autoAssign}>
              {t('models.autoAssign')}
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
                      {ready ? t('models.set') : t('models.unset')}
                    </span>
                  </div>

                  <div className="slot-fields">
                    <div className="field">
                      <label>{t('settings.provider')}</label>
                      <select
                        value={cur.provider}
                        onChange={(e) => pickProvider(slot, e.target.value)}
                      >
                        <option value="">{t('settings.choose')}</option>
                        {usable.map((p) => (
                          <option key={p} value={p}>
                            {catalog?.providers?.[p]?.label || p}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="field">
                      <label>{t('settings.model')}</label>
                      <select
                        value={isCustom ? '__custom' : cur.model}
                        disabled={!cur.provider}
                        onChange={(e) =>
                          setSlot(slot, {
                            model: e.target.value === '__custom' ? '' : e.target.value,
                          })
                        }
                      >
                        <option value="">{t('settings.choose')}</option>
                        {models.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                            {m.note ? `${t('common.optionSep')}${m.note}` : ''}
                          </option>
                        ))}
                        <option value="__custom">{t('settings.customModel')}</option>
                      </select>
                    </div>
                  </div>

                  {(isCustom || (cur.provider && !cur.model)) && (
                    <div className="field" style={{ marginBottom: 0 }}>
                      <label>{t('settings.customModelLabel')}</label>
                      <input
                        value={cur.model}
                        placeholder={t('settings.customModelPlaceholder')}
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
