import { useState } from 'react'
import type { StepProps } from './types'
import { useLocale } from '../../i18n'

const MIN_IDENTITY = 40
const MIN_BACKSTORY = 80

function words(s: string) {
  const t = s.trim()
  return t ? t.split(/\s+/).length : 0
}

/** Small progress meter so the length requirement never feels arbitrary. */
function Meter({ value, min, label }: { value: string; min: number; label: string }) {
  const { t } = useLocale()
  const pct = Math.min(100, (value.trim().length / min) * 100)
  const done = value.trim().length >= min
  return (
    <div className="meter-row">
      <div className="meter">
        <i style={{ width: `${pct}%` }} className={done ? 'done' : ''} />
      </div>
      <span className={`meter-label ${done ? 'done' : ''}`}>
        {done
          ? t('identityStep.words', { count: words(value) })
          : t('identityStep.toGo', { label, count: Math.max(0, min - value.trim().length) })}
      </span>
    </div>
  )
}

export default function StepIdentity({ draft, patch, state }: StepProps) {
  const { t, tx } = useLocale()
  const [loaded, setLoaded] = useState('')
  const examples = state?.examples || {}
  const existing = state?.identity

  function loadExamples() {
    patch({
      identity: examples.identity || draft.identity,
      backstory: examples.backstory || draft.backstory,
    })
    setLoaded(t('identityStep.loadedExamples'))
  }

  function loadExisting() {
    // Pull whatever is already on disk so a re-run does not start from nothing.
    patch({
      identity: existing?.identity_text || draft.identity,
      backstory: existing?.backstory_text || draft.backstory,
    })
    setLoaded(t('identityStep.loadedDisk'))
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">{t('identityStep.eyebrow')}</p>
        <h2>{t('identityStep.title')}</h2>
        <p className="step-lede">
          {tx('identityStep.lede', {
            identity: <span className="mono">identity.md</span>,
            backstory: <span className="mono">backstory.md</span>,
          })}
        </p>
      </header>

      <div className="row" style={{ marginBottom: '1.1rem' }}>
        {(examples.identity || examples.backstory) && (
          <button className="btn sm" onClick={loadExamples}>
            {t('identityStep.loadExamples')}
          </button>
        )}
        {existing?.has_identity && (
          <button className="btn sm ghost" onClick={loadExisting}>
            {t('identityStep.loadDisk')}
          </button>
        )}
        {(draft.identity || draft.backstory) && (
          <button
            className="btn sm ghost"
            onClick={() => {
              patch({ identity: '', backstory: '' })
              setLoaded('')
            }}
          >
            {t('identityStep.clear')}
          </button>
        )}
      </div>

      {loaded && <p className="step-note">{loaded}</p>}

      <div className="field">
        <label>{t('identityStep.identityLabel')}</label>
        <textarea
          rows={7}
          value={draft.identity}
          onChange={(e) => patch({ identity: e.target.value })}
          placeholder={t('identityStep.identityPlaceholder')}
        />
        <Meter value={draft.identity} min={MIN_IDENTITY} label={t('identityStep.aLittleMore')} />
      </div>

      <div className="field">
        <label>{t('identityStep.backstoryLabel')}</label>
        <textarea
          rows={12}
          value={draft.backstory}
          onChange={(e) => patch({ backstory: e.target.value })}
          placeholder={t('identityStep.backstoryPlaceholder')}
        />
        <Meter value={draft.backstory} min={MIN_BACKSTORY} label={t('identityStep.keepGoing')} />
      </div>
    </div>
  )
}
