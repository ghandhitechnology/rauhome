import type { StepProps } from './types'
import { useLocale } from '../../i18n'

export default function StepOrigin({ draft, patch, go }: StepProps) {
  const { t, tx } = useLocale()
  const options = [
    {
      id: 'fresh' as const,
      title: t('origin.fresh.title'),
      tagline: t('origin.fresh.tagline'),
      body: t('origin.fresh.body'),
      points: [t('origin.fresh.point.1'), t('origin.fresh.point.2'), t('origin.fresh.point.3')],
    },
    {
      id: 'guided' as const,
      title: t('origin.guided.title'),
      tagline: t('origin.guided.tagline'),
      body: t('origin.guided.body'),
      points: [t('origin.guided.point.1'), t('origin.guided.point.2'), t('origin.guided.point.3')],
    },
  ]

  function choose(id: 'fresh' | 'guided') {
    patch({ origin: id })
    // Give the selection animation a beat before moving on.
    window.setTimeout(() => go(id === 'fresh' ? 'brains' : 'identity'), 260)
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">{t('origin.eyebrow')}</p>
        <h2>{t('origin.title')}</h2>
        <p className="step-lede">
          {tx('origin.lede', { file: <span className="mono">soul.md</span> })}
        </p>
      </header>

      <div className="origin-grid">
        {options.map((o, i) => (
          <button
            key={o.id}
            className={`origin-card ${draft.origin === o.id ? 'chosen' : ''}`}
            style={{ '--i': i } as React.CSSProperties}
            onClick={() => choose(o.id)}
          >
            <span className="origin-tag">{o.tagline}</span>
            <span className="origin-title">{o.title}</span>
            <span className="origin-body">{o.body}</span>
            <ul className="origin-points">
              {o.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
            <span className="origin-go">{t('origin.choose')}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
