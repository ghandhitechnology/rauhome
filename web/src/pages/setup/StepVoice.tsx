import { useState } from 'react'
import { api } from '../../api'
import type { StepProps } from './types'

export default function StepVoice({ draft, patch, state, catalog, reload, verify, setVerify }: StepProps) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)

  const el = (state?.providers || []).find((p) => p.id === 'elevenlabs')
  const composio = (state?.providers || []).find((p) => p.id === 'composio')
  const v = verify.elevenlabs || { status: 'idle' as const }

  async function connect() {
    const k = key.trim()
    if (!k) return
    setBusy(true)
    setVerify('elevenlabs', { status: 'checking', detail: 'Asking ElevenLabs…' })
    try {
      const res = await api.verifyAuth('elevenlabs', k)
      if (!res.ok) {
        setVerify('elevenlabs', { status: 'bad', detail: res.detail || 'Key rejected.' })
        return
      }
      await api.setAuth('elevenlabs', k)
      setVerify('elevenlabs', { status: 'ok', detail: res.detail || 'Connected.' })
      setKey('')
      patch({ voiceSkipped: false })
      await reload()
    } catch (e: any) {
      setVerify('elevenlabs', { status: 'bad', detail: e?.message || String(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">Step five — optional</p>
        <h2>Give Rau a voice</h2>
        <p className="step-lede">
          Without this Rau still talks, just in text. Skip it now and add it from Settings whenever
          you feel like hearing something back.
        </p>
      </header>

      <article className={`auth-card wide ${el?.configured ? 'ok' : ''}`}>
        <div className="auth-head static">
          <span className="auth-title">
            <span className="auth-name">ElevenLabs</span>
            <span className="auth-help">Text-to-speech for spoken replies.</span>
          </span>
          <span className={`pill ${el?.configured ? 'on' : 'off'}`}>
            <i className="pill-dot" />
            {el?.configured ? el.masked || 'connected' : 'not connected'}
          </span>
        </div>

        <div className="auth-body-inner">
          <div className="field">
            <label>ELEVENLABS_API_KEY</label>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={el?.configured ? 'paste a new key to replace' : 'paste API key (optional)'}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  connect()
                }
              }}
            />
          </div>

          {v.status !== 'idle' && (
            <p className={`verify-line ${v.status}`}>
              {v.status === 'checking' && <i className="spinner" />}
              {v.status === 'ok' && <i className="tick" />}
              {v.status === 'bad' && <i className="cross" />}
              {v.detail}
            </p>
          )}

          <div className="row">
            <button className="btn primary sm" disabled={busy || !key.trim()} onClick={connect}>
              {busy && <i className="spinner" />}
              {busy ? 'Checking…' : 'Check & save'}
            </button>
            <button
              className="btn sm ghost"
              onClick={() => window.open(el?.docs_url, '_blank', 'noopener,noreferrer')}
            >
              Get a key ↗
            </button>
          </div>

          {el?.configured && (
            <div className="voice-picks">
              <div className="field">
                <label>Voice</label>
                <select
                  value={draft.tts.voice_id}
                  onChange={(e) => patch({ tts: { ...draft.tts, voice_id: e.target.value } })}
                >
                  {(catalog?.voices || []).map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.label}
                      {voice.note ? ` — ${voice.note}` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>TTS model</label>
                <select
                  value={draft.tts.model}
                  onChange={(e) => patch({ tts: { ...draft.tts, model: e.target.value } })}
                >
                  {(catalog?.tts_models || []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                      {m.note ? ` — ${m.note}` : ''}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
      </article>

      {composio && (
        <p className="step-note subtle">
          Want Rau to act inside other apps? Connect{' '}
          <a href={composio.docs_url} target="_blank" rel="noopener noreferrer">
            Composio
          </a>{' '}
          later from Settings — it needs a browser authorization round-trip.
        </p>
      )}
    </div>
  )
}
