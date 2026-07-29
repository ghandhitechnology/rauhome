import type { StepProps } from './types'
import { useLocale } from '../../i18n'

export default function StepOrigin({ draft, patch, go }: StepProps) {
  const { locale } = useLocale()
  const options = locale === 'ko'
    ? [
        {
          id: 'fresh' as const,
          title: '새로운 시작',
          tagline: '첫날',
          body: '부드러운 씨앗 하나에서 시작합니다. 함께 보내는 시간 속에서 Rau의 성격이 자연스럽게 자라납니다.',
          points: ['미리 글을 쓸 필요 없음', '사용하며 성격이 형성됨', '나중에 강하게 조정 가능'],
        },
        {
          id: 'guided' as const,
          title: '직접 이끌기',
          tagline: '이야기 가져오기',
          body: 'identity.md와 backstory.md를 작성하면 모델이 모든 에이전트가 읽는 살아 있는 soul.md로 정리합니다.',
          points: ['완전한 창작 통제', '시작용 예시 제공', '수정할 때마다 다시 정리'],
        },
      ]
    : [
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
  function choose(id: 'fresh' | 'guided') {
    patch({ origin: id })
    // Give the selection animation a beat before moving on.
    window.setTimeout(() => go(id === 'fresh' ? 'brains' : 'identity'), 260)
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">{locale === 'ko' ? '첫 번째 단계' : 'Step one'}</p>
        <h2>{locale === 'ko' ? 'Rau는 어디에서 시작할까요?' : 'Where does Rau start?'}</h2>
        <p className="step-lede">
          {locale === 'ko' ? (
            <>모든 에이전트가 말하기 전에 읽는 <span className="mono">soul.md</span>의 시작점을 정합니다. 어느 쪽도 영구적이지 않습니다.</>
          ) : (
            <>This decides what goes into <span className="mono">soul.md</span> — the file every agent reads before it says a word. Neither path is permanent.</>
          )}
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
            <span className="origin-go">{locale === 'ko' ? '선택 →' : 'Choose →'}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
