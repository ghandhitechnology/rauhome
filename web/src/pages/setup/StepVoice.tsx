import { useEffect, useState } from 'react'
import { api, type ElevenVoice, type VoicePreset } from '../../api'
import type { StepProps } from './types'

export default function StepVoice({
  draft,
  patch,
  state,
  catalog,
  reload,
  verify,
  setVerify,
}: StepProps) {
  const [keys, setKeys] = useState({ elevenlabs: '', deepgram: '' })
  const [busy, setBusy] = useState('')
  const [voices, setVoices] = useState<ElevenVoice[]>([])

  const providers = state?.providers || []
  const el = providers.find((p) => p.id === 'elevenlabs')
  const dg = providers.find((p) => p.id === 'deepgram')

  useEffect(() => {
    if (!el?.configured) {
      setVoices([])
      return
    }
    api
      .elevenVoices()
      .then((result) => setVoices(result.voices || []))
      .catch(() => setVoices([]))
  }, [el?.configured])

  async function connect(id: 'elevenlabs' | 'deepgram') {
    const key = keys[id].trim()
    if (!key) return
    setBusy(id)
    setVerify(id, { status: 'checking', detail: `Asking ${id === 'elevenlabs' ? 'ElevenLabs' : 'Deepgram'}…` })
    try {
      const result = await api.verifyAuth(id, key)
      if (!result.ok) {
        setVerify(id, { status: 'bad', detail: result.detail || 'Key rejected.' })
        return
      }
      await api.setAuth(id, key)
      setVerify(id, { status: 'ok', detail: result.detail || 'Connected.' })
      setKeys((current) => ({ ...current, [id]: '' }))
      patch({ voiceSkipped: false })
      await reload()
    } catch (error: any) {
      setVerify(id, { status: 'bad', detail: error?.message || String(error) })
    } finally {
      setBusy('')
    }
  }

  function choosePreset(preset: VoicePreset) {
    patch({
      tts: {
        ...draft.tts,
        preset: preset.id,
        voice_id: preset.voice_id,
        effect: preset.effect,
        voice_settings: { ...preset.settings },
      },
    })
  }

  async function preview() {
    if (!el?.configured) return
    setBusy('preview')
    try {
      const blob = await api.previewVoice(draft.tts)
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
      audio.addEventListener('error', () => URL.revokeObjectURL(url), { once: true })
      await audio.play()
    } catch (error: any) {
      setVerify('elevenlabs', { status: 'bad', detail: error?.message || String(error) })
    } finally {
      setBusy('')
    }
  }

  function authCard(id: 'elevenlabs' | 'deepgram', label: string, provider: any, help: string) {
    const check = verify[id] || { status: 'idle' as const }
    return (
      <article className={`auth-card wide ${provider?.configured ? 'ok' : ''}`}>
        <div className="auth-head static">
          <span className="auth-title">
            <span className="auth-name">{label}</span>
            <span className="auth-help">{help}</span>
          </span>
          <span className={`pill ${provider?.configured ? 'on' : 'off'}`}>
            <i className="pill-dot" />
            {provider?.configured ? provider.masked || 'connected' : 'not connected'}
          </span>
        </div>
        <div className="auth-body-inner">
          <div className="field">
            <label>{provider?.env || `${id.toUpperCase()}_API_KEY`}</label>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={provider?.configured ? 'paste a new key to replace' : 'paste your API key'}
              value={keys[id]}
              onChange={(event) => setKeys((current) => ({ ...current, [id]: event.target.value }))}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  void connect(id)
                }
              }}
            />
          </div>
          {check.status !== 'idle' && (
            <p className={`verify-line ${check.status}`}>
              {check.status === 'checking' && <i className="spinner" />}
              {check.status === 'ok' && <i className="tick" />}
              {check.status === 'bad' && <i className="cross" />}
              {check.detail}
            </p>
          )}
          <div className="row">
            <button
              className="btn primary sm"
              disabled={busy === id || !keys[id].trim()}
              onClick={() => connect(id)}
            >
              {busy === id && <i className="spinner" />}
              {busy === id ? 'Checking…' : 'Check & save'}
            </button>
            <button
              className="btn sm ghost"
              onClick={() => window.open(provider?.docs_url, '_blank', 'noopener,noreferrer')}
            >
              Get a key ↗
            </button>
          </div>
        </div>
      </article>
    )
  }

  const sttMeta = catalog?.stt_providers?.[draft.stt.provider]
  const sttModels = sttMeta?.models || []

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">Step five — voice</p>
        <h2>Give Rau a voice and ears</h2>
        <p className="step-lede">
          ElevenLabs speaks. Deepgram hears in real time. You can use either key independently,
          and automatic hearing always falls back to another connected backend.
        </p>
      </header>

      {authCard('elevenlabs', 'ElevenLabs', el, 'Text-to-speech and optional Scribe speech-to-text.')}

      {el?.configured && (
        <section className="voice-setup-card">
          <h3>Choose a personality</h3>
          <div className="voice-preset-grid">
            {(catalog?.voice_presets || []).map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`voice-preset ${draft.tts.preset === preset.id ? 'selected' : ''}`}
                onClick={() => choosePreset(preset)}
              >
                <strong>{preset.label}</strong>
                <span>{preset.note}</span>
                <em>{preset.voice_name}</em>
              </button>
            ))}
          </div>
          <div className="voice-picks">
            <div className="field">
              <label>Your account voices</label>
              <select
                value={voices.some((voice) => voice.id === draft.tts.voice_id) ? draft.tts.voice_id : ''}
                onChange={(event) =>
                  patch({
                    tts: {
                      ...draft.tts,
                      preset: 'custom',
                      voice_id: event.target.value,
                      effect: 'none',
                    },
                  })
                }
              >
                <option value="">choose a custom or saved voice…</option>
                {voices.map((voice) => (
                  <option key={voice.id} value={voice.id}>
                    {voice.label}
                    {voice.labels?.age ? ` · ${voice.labels.age}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Custom voice ID</label>
              <input
                value={draft.tts.voice_id}
                spellCheck={false}
                onChange={(event) =>
                  patch({
                    tts: {
                      ...draft.tts,
                      preset: 'custom',
                      voice_id: event.target.value.trim(),
                    },
                  })
                }
              />
            </div>
            <div className="field">
              <label>TTS model</label>
              <select
                value={draft.tts.model}
                onChange={(event) => patch({ tts: { ...draft.tts, model: event.target.value } })}
              >
                {(catalog?.tts_models || []).map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label} — {model.note}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Voice effect</label>
              <select
                value={draft.tts.effect}
                onChange={(event) => patch({ tts: { ...draft.tts, effect: event.target.value } })}
              >
                {(catalog?.voice_effects || []).map((effect) => (
                  <option key={effect.id} value={effect.id}>
                    {effect.label} — {effect.note}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn sm" disabled={busy === 'preview'} onClick={preview}>
            {busy === 'preview' && <i className="spinner" />}
            {busy === 'preview' ? 'Generating…' : 'Preview this voice'}
          </button>
        </section>
      )}

      {authCard('deepgram', 'Deepgram', dg, 'Low-latency streaming speech-to-text with live partials.')}

      <section className="voice-setup-card">
        <h3>Hearing</h3>
        <div className="voice-picks">
          <div className="field">
            <label>STT provider</label>
            <select
              value={draft.stt.provider}
              onChange={(event) => {
                const provider = event.target.value
                patch({
                  stt: {
                    ...draft.stt,
                    provider,
                    model: catalog?.stt_providers?.[provider]?.models?.[0]?.id || '',
                  },
                })
              }}
            >
              {Object.entries(catalog?.stt_providers || {}).map(([id, meta]) => (
                <option key={id} value={id}>
                  {meta.label}
                  {meta.auth && !providers.some((p) => p.id === meta.auth && p.configured)
                    ? ' (no key)'
                    : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>STT model</label>
            <select
              disabled={draft.stt.provider === 'auto'}
              value={draft.stt.model}
              onChange={(event) => patch({ stt: { ...draft.stt, model: event.target.value } })}
            >
              <option value="">
                {draft.stt.provider === 'auto' ? 'chosen automatically' : 'choose…'}
              </option>
              {sttModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label} — {model.note}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Recognition language</label>
            <select
              value={draft.stt.language}
              onChange={(event) => patch({ stt: { ...draft.stt, language: event.target.value } })}
            >
              <option value="">Provider default</option>
              <option value="en">English</option>
              <option value="ko">Korean</option>
              <option value="ja">Japanese</option>
              <option value="zh">Chinese</option>
              <option value="es">Spanish</option>
              <option value="multi">Multilingual / code-switching</option>
            </select>
          </div>
        </div>
        <p className="step-note subtle">{sttMeta?.blurb}</p>
      </section>
    </div>
  )
}
