import { useEffect, useState } from 'react'
import { api } from '../api'
import PageSkeleton from '../components/PageSkeleton'
import './Identity.css'

export default function Identity() {
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
          `Saved sources, but distill fell back to a lean compile${
            res.error ? ` (${res.error})` : ''
          }.${res.backup ? ` Previous soul → ${res.backup}` : ''}`,
        )
      } else {
        const via = res.model ? ` via ${res.model}` : ' via DeepSeek V4 Pro'
        setMsg(
          res.backup
            ? `Hard-steered${via}. Previous soul backed up to ${res.backup}`
            : `Hard-steered${via}.`,
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
            <h2>Sources</h2>
            <p className="muted panel-sub">
              These are the files you own. Hard steer saves them, then DeepSeek V4 Pro distills
              them into soul.md — not a paste. Previous soul gets a timestamped backup.
            </p>
          </div>
          {dirty && <span className="pill bad">unsaved</span>}
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
            {busy ? 'Distilling with V4 Pro…' : 'Hard steer'}
          </button>
        </div>

        {msg && <p className={`msg-line ${err ? 'bad' : ''}`}>{msg}</p>}
      </section>

      <section className="panel soul-panel">
        <div className="panel-head">
          <div>
            <h2>Living soul.md</h2>
            <p className="muted panel-sub">
              What every agent loads — a compressed self, not the raw sources. Nightly dreams may
              rewrite this on their own.
            </p>
          </div>
          <span className="pill on">
            <i className="pill-dot" />
            {soul ? `${soul.split('\n').length} lines` : 'empty'}
          </span>
        </div>
        <pre className="doc soul-view">{soul || '—'}</pre>
      </section>
    </div>
  )
}
