import type { StepProps } from './types'

const OPTIONS = [
  {
    id: 'fresh' as const,
    title: 'Fresh state',
    tagline: 'Day zero',
    body: 'A soft seed and nothing else. Rau starts blank and grows a personality out of the days you actually spend together.',
    points: ['Zero writing up front', 'Personality emerges from use', 'You can hard-steer later'],
  },
  {
    id: 'guided' as const,
    title: 'Guided startup',
    tagline: 'Bring lore',
    body: 'You write identity.md and backstory.md. DeepSeek V4 Pro distills them into a living soul.md that every agent loads.',
    points: ['Full authorial control', 'Examples to start from', 'LLM distill on every hard steer'],
  },
]

export default function StepOrigin({ draft, patch, go }: StepProps) {
  function choose(id: 'fresh' | 'guided') {
    patch({ origin: id })
    // Give the selection animation a beat before moving on.
    window.setTimeout(() => go(id === 'fresh' ? 'brains' : 'identity'), 260)
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">Step one</p>
        <h2>Where does Rau start?</h2>
        <p className="step-lede">
          This decides what goes into <span className="mono">soul.md</span> — the file every agent
          reads before it says a word. Neither path is permanent.
        </p>
      </header>

      <div className="origin-grid">
        {OPTIONS.map((o, i) => (
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
            <span className="origin-go">Choose →</span>
          </button>
        ))}
      </div>
    </div>
  )
}
