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
  const pct = Math.min(100, (value.trim().length / min) * 100)
  const done = value.trim().length >= min
  return (
    <div className="meter-row">
      <div className="meter">
        <i style={{ width: `${pct}%` }} className={done ? 'done' : ''} />
      </div>
      <span className={`meter-label ${done ? 'done' : ''}`}>
        {done ? `${words(value)} words` : `${label} — ${Math.max(0, min - value.trim().length)} to go`}
      </span>
    </div>
  )
}

export default function StepIdentity({ draft, patch, state }: StepProps) {
  const { locale } = useLocale()
  const [loaded, setLoaded] = useState('')
  const examples = state?.examples || {}
  const existing = state?.identity

  function loadExamples() {
    patch({
      identity: examples.identity || draft.identity,
      backstory: examples.backstory || draft.backstory,
    })
    setLoaded('Examples loaded — edit them into your own.')
  }

  function loadExisting() {
    // Pull whatever is already on disk so a re-run does not start from nothing.
    patch({
      identity: existing?.identity_text || draft.identity,
      backstory: existing?.backstory_text || draft.backstory,
    })
    setLoaded('Loaded the files currently on disk.')
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">{locale === 'ko' ? '두 번째 단계' : 'Step two'}</p>
        <h2>{locale === 'ko' ? '자아를 적어 주세요' : 'Write the self'}</h2>
        <p className="step-lede">
          {locale === 'ko' ? (
            <><span className="mono">identity.md</span>는 Rau가 드러내는 짧은 자아이고, <span className="mono">backstory.md</span>는 그 뒤의 긴 이야기입니다. 둘은 자동으로 soul.md에 정리됩니다.</>
          ) : (
            <><span className="mono">identity.md</span> is the short public self Rau speaks from.{' '}<span className="mono">backstory.md</span> is the long private lore behind it. DeepSeek V4 Pro distills both into soul.md — you never paste them in by hand.</>
          )}
        </p>
      </header>

      <div className="row" style={{ marginBottom: '1.1rem' }}>
        {(examples.identity || examples.backstory) && (
          <button className="btn sm" onClick={loadExamples}>
            {locale === 'ko' ? '예시 이야기 불러오기' : 'Load example lore'}
          </button>
        )}
        {existing?.has_identity && (
          <button className="btn sm ghost" onClick={loadExisting}>
            {locale === 'ko' ? '디스크의 내용 불러오기' : 'Load what is on disk'}
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
            {locale === 'ko' ? '비우기' : 'Clear'}
          </button>
        )}
      </div>

      {loaded && <p className="step-note">{loaded}</p>}

      <div className="field">
        <label>{locale === 'ko' ? 'identity.md — Rau가 드러내는 모습' : 'identity.md — who Rau is, out loud'}</label>
        <textarea
          rows={7}
          value={draft.identity}
          onChange={(e) => patch({ identity: e.target.value })}
          placeholder={'# Rau\n\nI am Rau. I live on this machine with you…'}
        />
        <Meter value={draft.identity} min={MIN_IDENTITY} label="a little more" />
      </div>

      <div className="field">
        <label>{locale === 'ko' ? 'backstory.md — Rau가 어디에서 왔는지' : 'backstory.md — where Rau came from'}</label>
        <textarea
          rows={12}
          value={draft.backstory}
          onChange={(e) => patch({ backstory: e.target.value })}
          placeholder={'# Backstory\n\nThe long version. History, people, places, grudges, hopes…'}
        />
        <Meter value={draft.backstory} min={MIN_BACKSTORY} label="keep going" />
      </div>
    </div>
  )
}
