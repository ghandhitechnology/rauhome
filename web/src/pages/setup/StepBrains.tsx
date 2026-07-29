import { useState } from 'react'
import { api } from '../../api'
import AuthCard, { VerifyLine } from '../../components/AuthCard'
import { CHAT_AUTH_IDS, type StepProps } from './types'
import { useLocale } from '../../i18n'

const RECOMMENDED = 'openrouter'

export default function StepBrains({ state, catalog, reload, verify, setVerify }: StepProps) {
  const { t, tx } = useLocale()
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const byId = Object.fromEntries((state?.providers || []).map((p) => [p.id, p]))
  const providers = CHAT_AUTH_IDS.map((id) => byId[id]).filter(Boolean)
  const connected = providers.filter((p) => p.configured).length

  /** Prove the key works before writing it to .env — a bad key never gets saved. */
  async function checkAndSave(id: string) {
    const key = (drafts[id] || '').trim()
    if (!key) return
    setBusy(id)
    setVerify(id, { status: 'checking', detail: t('settings.calling') })
    try {
      const res = await api.verifyAuth(id, key)
      if (!res.ok) {
        setVerify(id, { status: 'bad', detail: res.detail || t('settings.rejected') })
        return
      }
      await api.setAuth(id, key)
      setVerify(id, { status: 'ok', detail: res.detail || t('settings.connectedOk') })
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
    setVerify(id, { status: 'checking', detail: t('settings.rechecking') })
    try {
      const res = await api.verifyAuth(id)
      setVerify(id, {
        status: res.ok ? 'ok' : 'bad',
        detail: res.detail || (res.ok ? t('settings.connectedOk') : t('settings.rejected')),
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
        <p className="eyebrow">{t('brains.eyebrow')}</p>
        <h2>{t('brains.title')}</h2>
        <p className="step-lede">
          {tx('brains.lede', { file: <span className="mono">.env</span> })}
        </p>
      </header>

      <div className={`tally ${connected ? 'ok' : ''}`}>
        <span className="tally-count">{connected}</span>
        <span>
          {connected === 0
            ? t('brains.noneYet')
            : connected > 1
              ? t('brains.connectedPlural')
              : t('brains.connected')}
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
              tag={p.id === RECOMMENDED ? t('brains.easiest') : undefined}
              open={isOpen}
              onToggle={() => setOpen(isOpen ? '' : p.id)}
            >
                  <div className="field">
                    <label>{p.env}</label>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={p.configured ? t('settings.pasteReplace') : t('settings.pasteKey')}
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
                      {busy === p.id ? t('settings.checking') : t('settings.checkSave')}
                    </button>
                    {p.configured && (
                      <button className="btn sm" disabled={busy === p.id} onClick={() => recheck(p.id)}>
                        {t('settings.recheck')}
                      </button>
                    )}
                    <button
                      className="btn sm ghost"
                      onClick={() => window.open(p.docs_url, '_blank', 'noopener,noreferrer')}
                    >
                      {t('settings.getKey')}
                    </button>
                    {p.configured && (
                      <button
                        className="btn sm danger"
                        disabled={busy === p.id}
                        onClick={() => disconnect(p.id)}
                      >
                        {t('settings.disconnect')}
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
