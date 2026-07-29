import { useState } from 'react'
import { api } from '../../api'
import AuthCard, { VerifyLine } from '../../components/AuthCard'
import { CHAT_AUTH_IDS, type StepProps } from './types'
import { useLocale } from '../../i18n'

const RECOMMENDED = 'openrouter'

export default function StepBrains({ state, catalog, reload, verify, setVerify }: StepProps) {
  const { locale } = useLocale()
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const providers = (state?.providers || []).filter((p) => CHAT_AUTH_IDS.includes(p.id))
  const connected = providers.filter((p) => p.configured).length

  /** Prove the key works before writing it to .env — a bad key never gets saved. */
  async function checkAndSave(id: string) {
    const key = (drafts[id] || '').trim()
    if (!key) return
    setBusy(id)
    setVerify(id, { status: 'checking', detail: 'Calling the provider…' })
    try {
      const res = await api.verifyAuth(id, key)
      if (!res.ok) {
        setVerify(id, { status: 'bad', detail: res.detail || 'Key rejected.' })
        return
      }
      await api.setAuth(id, key)
      setVerify(id, { status: 'ok', detail: res.detail || 'Connected.' })
      setDrafts((d) => ({ ...d, [id]: '' }))
      setOpen(null)
      await reload()
    } catch (e: any) {
      setVerify(id, { status: 'bad', detail: e?.message || String(e) })
    } finally {
      setBusy('')
    }
  }

  async function recheck(id: string) {
    setBusy(id)
    setVerify(id, { status: 'checking', detail: 'Re-checking saved key…' })
    try {
      const res = await api.verifyAuth(id)
      setVerify(id, {
        status: res.ok ? 'ok' : 'bad',
        detail: res.detail || (res.ok ? 'Connected.' : 'Key rejected.'),
      })
    } catch (e: any) {
      setVerify(id, { status: 'bad', detail: e?.message || String(e) })
    } finally {
      setBusy('')
    }
  }

  async function disconnect(id: string) {
    setBusy(id)
    try {
      await api.clearAuth(id)
      setVerify(id, { status: 'idle' })
      await reload()
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">{locale === 'ko' ? '세 번째 단계' : 'Step three'}</p>
        <h2>{locale === 'ko' ? 'Rau에게 생각할 두뇌를 주세요' : 'Give Rau something to think with'}</h2>
        <p className="step-lede">
          {locale === 'ko' ? (
            <>키는 저장 전에 실제 제공자에서 확인하고 이 컴퓨터의 <span className="mono">.env</span>에만 보관합니다. 제공자 하나면 충분합니다.</>
          ) : (
            <>Keys are checked against the live provider before anything is written, then stored in{' '}<span className="mono">.env</span> on this machine only. One provider is enough to finish.</>
          )}
        </p>
      </header>

      <div className={`tally ${connected ? 'ok' : ''}`}>
        <span className="tally-count">{connected}</span>
        <span>
          {connected === 0
            ? 'no providers connected yet — connect at least one'
            : `provider${connected > 1 ? 's' : ''} connected`}
        </span>
      </div>

      <div className="auth-list">
        {providers.map((p, i) => {
          const v = verify[p.id] || { status: 'idle' as const }
          const isOpen = open === p.id || (!p.configured && open === null && i === 0)
          const meta = catalog?.providers?.[p.id]
          return (
            <AuthCard
              key={p.id}
              label={p.label}
              help={meta?.blurb || p.help}
              configured={p.configured}
              masked={p.masked}
              bad={v.status === 'bad'}
              index={i}
              tag={p.id === RECOMMENDED ? 'easiest start' : undefined}
              open={isOpen}
              onToggle={() => setOpen(isOpen ? '' : p.id)}
            >
                  <div className="field">
                    <label>{p.env}</label>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={p.configured ? 'paste a new key to replace' : 'paste API key'}
                      value={drafts[p.id] || ''}
                      onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          checkAndSave(p.id)
                        }
                      }}
                    />
                  </div>

                  <VerifyLine status={v.status} detail={v.detail} />

                  <div className="row">
                    <button
                      className="btn primary sm"
                      disabled={busy === p.id || !(drafts[p.id] || '').trim()}
                      onClick={() => checkAndSave(p.id)}
                    >
                      {busy === p.id && <i className="spinner" />}
                      {busy === p.id ? (locale === 'ko' ? '확인 중…' : 'Checking…') : (locale === 'ko' ? '확인하고 저장' : 'Check & save')}
                    </button>
                    {p.configured && (
                      <button className="btn sm" disabled={busy === p.id} onClick={() => recheck(p.id)}>
                        {locale === 'ko' ? '다시 확인' : 'Re-check'}
                      </button>
                    )}
                    <button
                      className="btn sm ghost"
                      onClick={() => window.open(p.docs_url, '_blank', 'noopener,noreferrer')}
                    >
                      {locale === 'ko' ? '키 받기 ↗' : 'Get a key ↗'}
                    </button>
                    {p.configured && (
                      <button
                        className="btn sm danger"
                        disabled={busy === p.id}
                        onClick={() => disconnect(p.id)}
                      >
                        {locale === 'ko' ? '연결 해제' : 'Disconnect'}
                      </button>
                    )}
                  </div>
            </AuthCard>
          )
        })}
      </div>
    </div>
  )
}
