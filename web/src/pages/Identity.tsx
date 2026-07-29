import { useEffect, useState } from 'react'
import { api } from '../api'
import { useLocale } from '../i18n'
import PageSkeleton from '../components/PageSkeleton'
import './Identity.css'

export default function Identity() {
  const { t } = useLocale()
  const [identity, setIdentity] = useState('')
  const [backstory, setBackstory] = useState('')
  const [soul, setSoul] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    api
      .identity()
      .then((d) => {
        setIdentity(d.identity || '')
        setBackstory(d.backstory || '')
        setSoul(d.soul || '')
        setLoaded(true)
      })
      .catch((e) => {
        setErr(true)
        setMsg(e.message || String(e))
        setLoaded(true)
      })
  }, [])

  async function steer() {
    setBusy(true)
    setErr(false)
    setMsg('')
    try {
      const res = await api.steer(identity, backstory)
      setSoul(res.soul || '')
      setDirty(false)
      if (res.fallback) {
        setMsg(
          t('identity.fallback', {
            detail: res.error ? ` (${res.error})` : '',
            backup: res.backup ? t('identity.fallbackBackup', { path: res.backup }) : '',
          }),
        )
      } else {
        const via = res.model ? t('identity.via', { model: res.model }) : ''
        setMsg(
          res.backup
            ? t('identity.steeredBackup', { via, path: res.backup })
            : t('identity.steered', { via }),
        )
      }
    } catch (e: any) {
      setErr(true)
      setMsg(e.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) {
    return <PageSkeleton pathname="/identity" />
  }

  return (
    <div className="identity grid-2">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t('identity.sources')}</h2>
            <p className="muted panel-sub">{t('identity.sourcesSub')}</p>
          </div>
          {dirty && <span className="pill bad">{t('identity.unsaved')}</span>}
        </div>

        <div className="field">
          <label>identity.md</label>
          <textarea
            rows={8}
            value={identity}
            onChange={(e) => {
              setIdentity(e.target.value)
              setDirty(true)
            }}
          />
        </div>

        <div className="field">
          <label>backstory.md</label>
          <textarea
            rows={16}
            value={backstory}
            onChange={(e) => {
              setBackstory(e.target.value)
              setDirty(true)
            }}
          />
        </div>

        <div className="row end">
          <button
            className="btn primary"
            disabled={busy || !identity.trim() || !backstory.trim()}
            onClick={steer}
          >
            {busy && <i className="spinner" />}
            {busy ? t('identity.distilling') : t('identity.hardSteer')}
          </button>
        </div>

        {msg && <p className={`msg-line ${err ? 'bad' : ''}`}>{msg}</p>}
      </section>

      <section className="panel soul-panel">
        <div className="panel-head">
          <div>
            <h2>{t('identity.soul')}</h2>
            <p className="muted panel-sub">{t('identity.soulSub')}</p>
          </div>
          <span className="pill on">
            <i className="pill-dot" />
            {soul ? t('identity.lines', { count: soul.split('\n').length }) : t('identity.empty')}
          </span>
        </div>
        <pre className="doc soul-view">{soul || '—'}</pre>
      </section>
    </div>
  )
}
