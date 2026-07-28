import { useEffect, useState } from 'react'
import { api, type TtsVoice, type VoicePreset } from '../../api'
import AuthCard, { VerifyLine } from '../../components/AuthCard'
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
  const [keys, setKeys] = useState({ elevenlabs: '', cartesia: '', deepgram: '' })
  const [busy, setBusy] = useState('')
  const [voices, setVoices] = useState<TtsVoice[]>([])

  const providers = state?.providers || []
  const el = providers.find((p) => p.id === 'elevenlabs')
  const cartesia = providers.find((p) => p.id === 'cartesia')
  const dg = providers.find((p) => p.id === 'deepgram')
  const selectedAuth = draft.tts.provider === 'cartesia' ? cartesia : el

  useEffect(() => {
    if (!selectedAuth?.configured) {
      setVoices([])
      return
    }
    api
      .ttsVoices(draft.tts.provider)
      .then((result) => setVoices(result.voices || []))
      .catch(() => setVoices([]))
  }, [draft.tts.provider, selectedAuth?.configured])

  async function connect(id: 'elevenlabs' | 'cartesia' | 'deepgram') {
    const key = keys[id].trim()
    if (!key) return
    setBusy(id)
    const label = id === 'elevenlabs' ? 'ElevenLabs' : id === 'cartesia' ? 'Cartesia' : 'Deepgram'
    setVerify(id, { status: 'checking', detail: `Asking ${label}…` })
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
        provider: 'elevenlabs',
        model: draft.tts.provider === 'elevenlabs' ? draft.tts.model : 'eleven_flash_v2_5',
        preset: preset.id,
        voice_id: preset.voice_id,
        effect: preset.effect,
        voice_settings: { ...preset.settings },
      },
    })
  }

  async function preview() {
    if (!selectedAuth?.configured) return
    setBusy('preview')
    try {
      const blob = await api.previewVoice(draft.tts)
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
      audio.addEventListener('error', () => URL.revokeObjectURL(url), { once: true })
      await audio.play()
    } catch (error: any) {
      setVerify(draft.tts.provider, { status: 'bad', detail: error?.message || String(error) })
    } finally {
      setBusy('')
    }
  }

  function authCard(id: 'elevenlabs' | 'cartesia' | 'deepgram', label: string, provider: any, help: string) {
    const check = verify[id] || { status: 'idle' as const }
    return (
      <AuthCard
        wide
        label={label}
        help={help}
        configured={provider?.configured}
        masked={provider?.masked}
      >
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
          <VerifyLine status={check.status} detail={check.detail} />
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
      </AuthCard>
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
          Choose ElevenLabs or Cartesia Sonic 3.5 for speech. Deepgram hears in real time.
          Speaking and hearing keys are independent.
        </p>
      </header>

      {authCard('elevenlabs', 'ElevenLabs', el, 'Text-to-speech and optional Scribe speech-to-text.')}
      {authCard('cartesia', 'Cartesia', cartesia, 'Low-latency Sonic 3.5 text-to-speech.')}

      {(el?.configured || cartesia?.configured) && (
        <section className="voice-setup-card">
          <h3>Choose a speaking service and voice</h3>
          <div className="voice-picks">
            <div className="field">
              <label>Speech provider</label>
              <select
                value={draft.tts.provider}
                onChange={(event) => {
                  const provider = event.target.value as 'elevenlabs' | 'cartesia'
                  const model = catalog?.tts_providers?.[provider]?.models?.[0]?.id || ''
                  patch({
                    tts: {
                      ...draft.tts,
                      provider,
                      model,
                      preset: 'custom',
                      voice_id: '',
                      effect: 'none',
                    },
                  })
                }}
              >
                {Object.entries(catalog?.tts_providers || {}).map(([id, meta]) => (
                  <option key={id} value={id}>
                    {meta.label}
                    {providers.some((p) => p.id === meta.auth && p.configured) ? '' : ' (no key)'}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {draft.tts.provider === 'elevenlabs' && (
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
          )}
          <div className="voice-picks">
            <div className="field">
              <label>{draft.tts.provider === 'cartesia' ? 'Cartesia voices' : 'Your account voices'}</label>
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
                <option value="">choose a voice…</option>
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
                {(catalog?.tts_providers?.[draft.tts.provider]?.models || []).map((model) => (
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
          <p className="step-note subtle">
            {catalog?.tts_providers?.[draft.tts.provider]?.blurb}
          </p>
          <button
            className="btn sm"
            disabled={busy === 'preview' || !selectedAuth?.configured || !draft.tts.voice_id}
            onClick={preview}
          >
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
