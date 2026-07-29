import type { CSSProperties, ReactNode } from 'react'
import { useLocale } from '../i18n'
import './AuthCard.css'

/**
 * Provider connection card.
 *
 * The head — title, blurb, connected/not-connected pill, the staggered
 * entrance driven by `--i` — was written out three separate times: in
 * `Settings`, in `setup/StepBrains`, and in `setup/StepVoice`. The stylesheet
 * had already been pulled out of `Setup.css` once because Settings never
 * imported it and rendered every card unstyled; leaving three copies of the
 * markup pointed at one stylesheet just set up the same drift again.
 *
 * The body stays a `children` slot because it genuinely differs per caller —
 * Settings offers a remove button, StepBrains collapses, StepVoice adds a
 * voice picker. Only the shell is shared, which is exactly the part that was
 * being copied.
 */

export type VerifyStatus = 'idle' | 'checking' | 'ok' | 'bad'

type AuthCardProps = {
  label: string
  /** One-line explanation under the provider name. */
  help?: string
  /** Whether a key is already saved for this provider. */
  configured?: boolean
  /** Masked form of the saved key, e.g. `sk-…4f2a`. */
  masked?: string
  /** Tints the card when the last verification failed. */
  bad?: boolean
  /** Position in the list; drives the staggered entrance. */
  index?: number
  /** Small emphasis tag beside the name, e.g. "easiest start". */
  tag?: ReactNode
  /** Wider body layout, used by the voice step. */
  wide?: boolean
  /** DOM id, so Settings can deep-link to `#connection-<id>`. */
  id?: string
  /**
   * Collapsible cards render the head as a button. Omit `onToggle` for a
   * static head — a plain `<div>`, since a header that does nothing should not
   * be reachable by keyboard as though it did.
   */
  open?: boolean
  onToggle?: () => void
  children: ReactNode
}

export default function AuthCard({
  label,
  help,
  configured = false,
  masked,
  bad = false,
  index = 0,
  tag,
  wide = false,
  id,
  open,
  onToggle,
  children,
}: AuthCardProps) {
  const { t } = useLocale()
  const head = (
    <>
      <span className="auth-title">
        <span className="auth-name">
          {label}
          {tag ? <em className="tag">{tag}</em> : null}
        </span>
        {help ? <span className="auth-help">{help}</span> : null}
      </span>
      <span className={`pill ${configured ? 'on' : 'off'}`}>
        <i className="pill-dot" />
        {configured ? masked || t('auth.connected') : t('auth.notConnected')}
      </span>
    </>
  )

  const body = <div className="auth-body-inner">{children}</div>

  return (
    <article
      id={id}
      className={`auth-card ${configured ? 'ok' : ''} ${bad ? 'bad' : ''} ${wide ? 'wide' : ''}`}
      style={{ '--i': index } as CSSProperties}
    >
      {onToggle ? (
        <button className="auth-head" onClick={onToggle} aria-expanded={!!open}>
          {head}
        </button>
      ) : (
        <div className="auth-head static">{head}</div>
      )}

      {onToggle ? <div className={`auth-body ${open ? 'open' : ''}`}>{body}</div> : body}
    </article>
  )
}

/**
 * The result line under a key field. All three call sites rendered the same
 * spinner/tick/cross triple by hand.
 */
export function VerifyLine({ status, detail }: { status: VerifyStatus; detail?: string }) {
  if (status === 'idle') return null
  return (
    <p className={`verify-line ${status}`} role="status">
      {status === 'checking' && <i className="spinner" />}
      {status === 'ok' && <i className="tick" />}
      {status === 'bad' && <i className="cross" />}
      {detail}
    </p>
  )
}
