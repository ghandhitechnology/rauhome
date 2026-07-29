import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import type { Locale } from '../../i18n'

/**
 * The first thing anyone sees. Two positions, a thumb that overshoots into
 * place, and the whole screen re-translating underneath it — picking a
 * language should read as the interface answering back, not as a form field.
 *
 * The labels stay ENGLISH / KOREAN in both locales on purpose. A language
 * picker that renames its own options while you are looking for yours is the
 * one control that must not move under the reader.
 */

/** Trigram rows, hoist-to-fly: solid (true) or broken (false). */
const TRIGRAMS: { x: number; y: number; rot: number; rows: boolean[] }[] = [
  { x: 7.5, y: 5, rot: -56.31, rows: [true, true, true] }, // 건 ☰
  { x: 28.5, y: 5, rot: 56.31, rows: [false, true, false] }, // 감 ☵
  { x: 7.5, y: 19, rot: 56.31, rows: [true, false, true] }, // 리 ☲
  { x: 28.5, y: 19, rot: -56.31, rows: [false, false, false] }, // 곤 ☷
]

function FlagKO() {
  return (
    <svg viewBox="0 0 36 24" className="flag-svg" role="presentation">
      <rect width="36" height="24" rx="2.5" fill="#fdfdfd" />
      {/* The taegeuk sits on the flag's diagonal, not upright. */}
      <g transform="rotate(-33.69 18 12)">
        <circle cx="18" cy="12" r="6" fill="#0047a0" />
        <path d="M12 12A6 6 0 0 1 24 12A3 3 0 0 1 18 12A3 3 0 0 0 12 12Z" fill="#cd2e3a" />
      </g>
      <g fill="#0b0b0f">
        {TRIGRAMS.map((trigram) => (
          <g
            key={`${trigram.x}-${trigram.y}`}
            transform={`translate(${trigram.x} ${trigram.y}) rotate(${trigram.rot})`}
          >
            {trigram.rows.map((solid, row) =>
              solid ? (
                <rect key={row} x="-3.2" y={row * 1.75 - 2.3} width="6.4" height="1.1" />
              ) : (
                <g key={row}>
                  <rect x="-3.2" y={row * 1.75 - 2.3} width="2.75" height="1.1" />
                  <rect x="0.45" y={row * 1.75 - 2.3} width="2.75" height="1.1" />
                </g>
              ),
            )}
          </g>
        ))}
      </g>
    </svg>
  )
}

const STRIPE = 24 / 13

function FlagUS() {
  return (
    <svg viewBox="0 0 36 24" className="flag-svg" role="presentation">
      <clipPath id="flag-us-round">
        <rect width="36" height="24" rx="2.5" />
      </clipPath>
      <g clipPath="url(#flag-us-round)">
        <rect width="36" height="24" fill="#b31942" />
        {[1, 3, 5, 7, 9, 11].map((band) => (
          <rect key={band} y={band * STRIPE} width="36" height={STRIPE} fill="#fdfdfd" />
        ))}
        <rect width="14.4" height={STRIPE * 7} fill="#0a3161" />
        <g fill="#fdfdfd">
          {Array.from({ length: 5 }, (_, row) =>
            Array.from({ length: 6 }, (_, col) => (
              <circle key={`${row}-${col}`} cx={1.2 + col * 2.4} cy={1.3 + row * 2.6} r="0.46" />
            )),
          )}
        </g>
      </g>
    </svg>
  )
}

const CHOICES: { id: Locale; label: string; Flag: () => React.ReactElement }[] = [
  { id: 'en', label: 'ENGLISH', Flag: FlagUS },
  { id: 'ko', label: 'KOREAN', Flag: FlagKO },
]

export default function LanguageToggle({
  locale,
  onSelect,
  onConfirm,
  busy,
  confirmLabel,
  groupLabel,
}: {
  locale: Locale
  onSelect: (locale: Locale) => void
  onConfirm: () => void
  busy: boolean
  confirmLabel: string
  groupLabel: string
}) {
  // The squash is a reaction to being moved, so it must not fire on arrival.
  // A ref rather than state: nothing about the first paint should re-render.
  const moved = useRef(false)
  const buttons = useRef<(HTMLButtonElement | null)[]>([])

  function choose(next: Locale) {
    if (next !== locale) moved.current = true
    onSelect(next)
  }

  /*
    A radiogroup promises arrow-key traversal, so honour it rather than
    downgrade the role: the group is one tab stop, and Left/Right move the
    choice. Focus follows the selection, which is what makes it audible to a
    screen reader.
  */
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowDown'
        ? 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
          ? -1
          : 0
    if (!step || busy) return
    event.preventDefault()
    const index = CHOICES.findIndex((c) => c.id === locale)
    const target = (index + step + CHOICES.length) % CHOICES.length
    choose(CHOICES[target].id)
    buttons.current[target]?.focus()
  }

  return (
    <div className="language-picker">
      <div
        className={`language-toggle ${locale === 'ko' ? 'at-ko' : 'at-en'}`}
        role="radiogroup"
        aria-label={groupLabel}
        onKeyDown={onKeyDown}
      >
        <span className="language-thumb" aria-hidden>
          {/* Remounts on every change so the squash replays while the thumb slides. */}
          <span key={locale} className={`language-thumb-skin${moved.current ? ' bounce' : ''}`} />
        </span>
        {CHOICES.map(({ id, label, Flag }, index) => (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={locale === id}
            // Roving tab stop: the group is one stop, arrows move within it.
            tabIndex={locale === id ? 0 : -1}
            disabled={busy}
            ref={(el) => {
              buttons.current[index] = el
            }}
            className={`language-choice ${locale === id ? 'active' : ''}`}
            onClick={() => choose(id)}
          >
            <span className="language-flag">
              <Flag />
            </span>
            <span className="language-name">{label}</span>
          </button>
        ))}
      </div>
      <button type="button" className="btn primary language-confirm" disabled={busy} onClick={onConfirm}>
        {confirmLabel}
      </button>
    </div>
  )
}
