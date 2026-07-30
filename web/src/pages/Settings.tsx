import { useEffect, useState } from 'react'
import { Link } from '../router'
import { useLocale } from '../i18n'
import { useTutorial } from '../tutorial'
import {
  api,
  type AuthProvider,
  type BrowseStatus,
  type Catalog,
  type TtsVoice,
  type VoicePreset,
  type VoiceStatus,
} from '../api'
import PageSkeleton from '../components/PageSkeleton'
import AuthCard, { VerifyLine } from '../components/AuthCard'
import './Settings.css'

/** Chat slots — the three that share a provider/model picker. */
type SlotKey = 'face' | 'subagent' | 'dream'
/** Every slot in models.json, including the ones with bespoke editors. */
type ConfigSlot = SlotKey | 'tts' | 'stt'
const SLOTS: SlotKey[] = ['face', 'subagent', 'dream']

type Check = { status: 'idle' | 'checking' | 'ok' | 'bad'; detail?: string }

export default function Settings() {
  const { locale, setLocale, t, tx } = useLocale()
  const tutorial = useTutorial()
  const [models, setModels] = useState<any>(null)
  const [browseStatus, setBrowseStatus] = useState<BrowseStatus | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [auth, setAuth] = useState<AuthProvider[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [checks, setChecks] = useState<Record<string, Check>>({})
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [dirty, setDirty] = useState(false)
  const [accountVoices, setAccountVoices] = useState<TtsVoice[]>([])
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null)
  const [voiceLoadError, setVoiceLoadError] = useState('')

  const [loadError, setLoadError] = useState('')

  async function reload() {
    setLoadError('')
    const [m, a, c, v, b] = await Promise.all([
      api.models(),
      api.auth(locale),
      api.catalog(locale),
      api.voiceStatus(),
      api.browseStatus().catch(() => null),
    ])
    setModels(m)
    setAuth(a.providers || [])
    setCatalog(c)
    setVoiceStatus(v)
    setBrowseStatus(b)
    const ttsProvider = m.tts?.provider || 'elevenlabs'
    if ((a.providers || []).some((p: AuthProvider) => p.id === ttsProvider && p.configured)) {
      void loadAccountVoices(ttsProvider)
    } else {
      setAccountVoices([])
    }
  }

  async function loadAccountVoices(provider = models?.tts?.provider || 'elevenlabs') {
    setVoiceLoadError('')
    try {
      const result = await api.ttsVoices(provider)
      setAccountVoices(result.voices || [])
    } catch (e: any) {
      setVoiceLoadError(e?.message || String(e))
    }
  }

  // Re-run on a language change as well as on mount: the provider blurbs and
  // slot guidance are the hub's copy, so switching language has to go back for
  // them or half this page stays in the language you just left.
  useEffect(() => {
    reload().catch((e) => {
      const text = e.message || String(e)
      setMsg(text)
      setLoadError(text)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload is stable enough; locale is the real trigger
  }, [locale])

  function flash(text: string) {
    setMsg(text)
    window.setTimeout(() => setMsg((cur) => (cur === text ? '' : cur)), 6000)
  }

  if (!models || !catalog) {
    if (!loadError) return <PageSkeleton pathname="/settings" />
    return (
      <div className="settings grid-2">
        <section className="panel">
          <h2>{t('settings.loadFailed')}</h2>
          <p className="muted">{loadError}</p>
          <p className="muted">
            {tx('settings.loadHint', {
              command: <span className="mono">bash launch.sh --hub</span>,
            })}
          </p>
          <button className="btn primary" onClick={() => reload().catch((e) => setLoadError(e.message || String(e)))}>
            {t('settings.retry')}
          </button>
        </section>
      </div>
    )
  }

  const configured = new Set(auth.filter((p) => p.configured).map((p) => p.id))
  const usable = Object.keys(catalog.providers).filter((p) => {
    const authId = catalog.provider_auth[p]
    return authId && configured.has(authId)
  })

  function updateSlot(slot: ConfigSlot, key: string, value: string | number) {
    setDirty(true)
    setModels((prev: any) => ({ ...prev, [slot]: { ...prev[slot], [key]: value } }))
  }

  function pickProvider(slot: SlotKey, provider: string) {
    const first = catalog?.providers?.[provider]?.models?.[0]?.id || ''
    setDirty(true)
    setModels((prev: any) => ({ ...prev, [slot]: { ...prev[slot], provider, model: first } }))
  }

  async function saveModels() {
    setBusy('models')
    try {
      const saved = await api.putModels({
        face: models.face,
        subagent: models.subagent,
        dream: models.dream,
        tts: models.tts,
        stt: models.stt,
        browse: models.browse,
      })
      setModels(saved)
      // Server clamps effort to the new provider/model capabilities.
      try {
        const ef = await api.effort()
        if (ef && typeof ef === 'object') {
          setModels((prev: any) => ({
            ...prev,
            face: { ...prev.face, effort: ef.face ?? prev.face?.effort },
            subagent: { ...prev.subagent, effort: ef.subagent ?? prev.subagent?.effort },
            dream: { ...prev.dream, effort: ef.dream ?? prev.dream?.effort },
          }))
        }
      } catch {
        /* effort refresh is best-effort */
      }
      setVoiceStatus(await api.voiceStatus())
      setDirty(false)
      flash(t('settings.savedModels'))
    } catch (e: any) {
      flash(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function checkAndSave(id: string) {
    const key = (drafts[id] || '').trim()
    if (!key) return
    setBusy(id)
    setChecks((c) => ({ ...c, [id]: { status: 'checking', detail: t('settings.calling') } }))
    try {
      const res = await api.verifyAuth(id, key)
      if (!res.ok) {
        setChecks((c) => ({ ...c, [id]: { status: 'bad', detail: res.detail || t('settings.rejected') } }))
        return
      }
      const saved = await api.setAuth(id, key)
      setAuth(saved.providers || [])
      setDrafts((d) => ({ ...d, [id]: '' }))
      setChecks((c) => ({ ...c, [id]: { status: 'ok', detail: res.detail || t('settings.connectedOk') } }))
      if (id === models?.tts?.provider) void loadAccountVoices(id)
      if (id === 'elevenlabs' || id === 'cartesia' || id === 'deepgram' || id === 'codex') {
        api.voiceStatus().then(setVoiceStatus).catch(() => {})
        api.browseStatus().then(setBrowseStatus).catch(() => {})
      }
    } catch (e: any) {
      setChecks((c) => ({ ...c, [id]: { status: 'bad', detail: e?.message || String(e) } }))
    } finally {
      setBusy('')
    }
  }

  async function recheck(id: string) {
    setBusy(id)
    setChecks((c) => ({ ...c, [id]: { status: 'checking', detail: t('settings.rechecking') } }))
    try {
      const res = await api.verifyAuth(id)
      setChecks((c) => ({
        ...c,
        [id]: {
          status: res.ok ? 'ok' : 'bad',
          detail: res.detail || (res.ok ? t('settings.connectedOk') : t('settings.rejectedShort')),
        },
      }))
    } catch (e: any) {
      setChecks((c) => ({ ...c, [id]: { status: 'bad', detail: e?.message || String(e) } }))
    } finally {
      setBusy('')
    }
  }

  async function clearKey(id: string) {
    setBusy(id)
    try {
      const res = await api.clearAuth(id)
      setAuth(res.providers || [])
      setChecks((c) => ({ ...c, [id]: { status: 'idle' } }))
      if (id === models?.tts?.provider) setAccountVoices([])
      if (id === 'elevenlabs' || id === 'cartesia' || id === 'deepgram' || id === 'codex') {
        api.voiceStatus().then(setVoiceStatus).catch(() => {})
        api.browseStatus().then(setBrowseStatus).catch(() => {})
      }
      flash(t('settings.disconnected', { provider: id }))
    } catch (e: any) {
      flash(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  function openUrl(url?: string) {
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }

  function choosePreset(preset: VoicePreset) {
    setDirty(true)
    setModels((prev: any) => ({
      ...prev,
      tts: {
        ...prev.tts,
        provider: 'elevenlabs',
        model:
          prev.tts?.provider === 'elevenlabs'
            ? prev.tts?.model
            : catalog?.tts_providers?.elevenlabs?.models?.[0]?.id || 'eleven_flash_v2_5',
        preset: preset.id,
        voice_id: preset.voice_id,
        effect: preset.effect,
        voice_settings: { ...preset.settings },
      },
    }))
  }

  function chooseAccountVoice(voiceId: string) {
    setDirty(true)
    setModels((prev: any) => ({
      ...prev,
      tts: {
        ...prev.tts,
        preset: 'custom',
        voice_id: voiceId,
        effect: 'none',
      },
    }))
  }

  function chooseTtsProvider(provider: string) {
    const firstModel = catalog?.tts_providers?.[provider]?.models?.[0]?.id || ''
    setDirty(true)
    setAccountVoices([])
    setVoiceLoadError('')
    setModels((prev: any) => ({
      ...prev,
      tts: {
        ...prev.tts,
        provider,
        model: firstModel,
        voice_id: '',
        preset: 'custom',
        effect: 'none',
      },
    }))
    if (configured.has(provider)) void loadAccountVoices(provider)
  }

  async function previewVoice() {
    const tts = models.tts || {}
    if (!tts.voice_id) {
      flash(t('settings.pickVoiceFirst'))
      return
    }
    setBusy('voice-preview')
    try {
      const blob = await api.previewVoice({
        provider: tts.provider || 'elevenlabs',
        voice_id: tts.voice_id,
        model: tts.model,
        effect: tts.effect || 'none',
        voice_settings: tts.voice_settings,
      })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
      audio.addEventListener('error', () => URL.revokeObjectURL(url), { once: true })
      await audio.play()
      flash(t('settings.playingVoice'))
    } catch (e: any) {
      flash(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function openComposio() {
    setBusy('composio-connect')
    try {
      const res = await api.composioConnect()
      if (res.needs_key) {
        flash(res.hint || t('settings.composioNeedsKey'))
        openUrl(res.open_url || res.app_url)
        return
      }
      openUrl(res.open_url || res.connect_url)
      flash(t('settings.composioOpened'))
    } catch (e: any) {
      flash(e.message || String(e))
      openUrl('https://connect.composio.dev')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="settings grid-2">
      <section className="panel settings-experience">
        <div className="panel-head">
          <div>
            <h2>{t('settings.experience')}</h2>
            <p className="muted panel-sub">{t('settings.languageHelp')}</p>
          </div>
        </div>
        <div className="experience-row">
          <div>
            <strong>{t('settings.language')}</strong>
            <p>{t('settings.languageHelp')}</p>
          </div>
          <div className="locale-seg" role="radiogroup" aria-label={t('settings.language')}>
            <button
              type="button"
              role="radio"
              aria-checked={locale === 'en'}
              className={locale === 'en' ? 'active' : ''}
              onClick={() =>
                void setLocale('en')
                  .then(() => flash(t('settings.saved')))
                  .catch((error) => flash(error?.message || String(error)))
              }
            >
              {t('language.english')}
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={locale === 'ko'}
              className={locale === 'ko' ? 'active' : ''}
              onClick={() =>
                void setLocale('ko')
                  .then(() => flash(t('settings.saved')))
                  .catch((error) => flash(error?.message || String(error)))
              }
            >
              {t('language.korean')}
            </button>
          </div>
        </div>
        <div className="experience-row">
          <div>
            <strong>{t('settings.replay')}</strong>
            <p>{t('settings.replayHelp')}</p>
          </div>
          <button type="button" className="btn" onClick={tutorial.start}>
            {t('settings.replay')}
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t('settings.models')}</h2>
            <p className="muted panel-sub">{t('settings.modelsSub')}</p>
          </div>
          {dirty && <span className="pill bad">{t('settings.unsaved')}</span>}
        </div>

        {usable.length === 0 && (
          <div className="notice bad" style={{ marginBottom: '1rem' }}>
            {tx('settings.noKeys', {
              link: <Link to="/setup">{t('settings.runSetupAgain')}</Link>,
            })}
          </div>
        )}

        {SLOTS.map((slot, i) => {
          const meta = catalog.slots.find((s) => s.id === slot)
          const cur = models[slot] || {}
          const list = catalog.providers[cur.provider]?.models || []
          const isCustom = !!cur.model && !list.some((m) => m.id === cur.model)
          return (
            <div key={slot} className="slot" style={{ '--i': i } as React.CSSProperties}>
              <div className="slot-title">
                <h3>{meta?.label || slot}</h3>
                <span className="slot-note">{meta?.blurb}</span>
              </div>

              <div className="slot-fields">
                <div className="field">
                  <label>{t('settings.provider')}</label>
                  <select value={cur.provider || ''} onChange={(e) => pickProvider(slot, e.target.value)}>
                    <option value="">{t('settings.choose')}</option>
                    {Object.keys(catalog.providers).map((p) => (
                      <option key={p} value={p}>
                        {catalog.providers[p].label}
                        {usable.includes(p) ? '' : t('settings.noKey')}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>{t('settings.model')}</label>
                  <select
                    value={isCustom ? '__custom' : cur.model || ''}
                    onChange={(e) =>
                      updateSlot(slot, 'model', e.target.value === '__custom' ? '' : e.target.value)
                    }
                  >
                    <option value="">{t('settings.choose')}</option>
                    {list.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                        {m.note ? `${t('common.optionSep')}${m.note}` : ''}
                      </option>
                    ))}
                    <option value="__custom">{t('settings.customModel')}</option>
                  </select>
                </div>
              </div>

              {(isCustom || !cur.model) && (
                <div className="field">
                  <label>{t('settings.customModelLabel')}</label>
                  <input
                    value={cur.model || ''}
                    placeholder={t('settings.customModelPlaceholder')}
                    onChange={(e) => updateSlot(slot, 'model', e.target.value)}
                  />
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>{t('settings.maxTokens')}</label>
                  <input
                    type="number"
                    min={16}
                    value={cur.max_tokens ?? ''}
                    onChange={(e) => updateSlot(slot, 'max_tokens', Number(e.target.value))}
                  />
                </div>
                <div className="field">
                  <label>{t('settings.temperature')}</label>
                  <input
                    type="number"
                    step="0.1"
                    min={0}
                    max={2}
                    value={cur.temperature ?? ''}
                    onChange={(e) => updateSlot(slot, 'temperature', Number(e.target.value))}
                  />
                </div>
              </div>
            </div>
          )
        })}

        <div className="slot voice-config">
          <div className="slot-title">
            <h3>{t('settings.voice')}</h3>
            <span className="slot-note">{t('settings.voiceSub')}</span>
          </div>

          {!configured.has(models.tts?.provider || 'elevenlabs') && (
            <div className="notice bad voice-connect-note">
              {t('settings.voiceNotConnected', {
                provider:
                  catalog.tts_providers?.[models.tts?.provider || 'elevenlabs']?.label ||
                  t('settings.voiceProviderFallback'),
              })}
            </div>
          )}

          <div className="slot-fields">
            <div className="field">
              <label>{t('settings.speechProvider')}</label>
              <select
                value={models.tts?.provider || 'elevenlabs'}
                onChange={(e) => chooseTtsProvider(e.target.value)}
              >
                {Object.entries(catalog.tts_providers || {}).map(([id, meta]) => (
                  <option key={id} value={id}>
                    {meta.label}
                    {configured.has(meta.auth) ? '' : t('settings.noKey')}
                  </option>
                ))}
              </select>
              <span className="field-hint">
                {catalog.tts_providers?.[models.tts?.provider || 'elevenlabs']?.blurb}
              </span>
            </div>
          </div>

          {(models.tts?.provider || 'elevenlabs') === 'elevenlabs' && (
            <div className="voice-preset-grid">
              {(catalog.voice_presets || []).map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  className={`voice-preset ${models.tts?.preset === preset.id ? 'selected' : ''}`}
                  onClick={() => choosePreset(preset)}
                >
                  <strong>{preset.label}</strong>
                  <span>{preset.note}</span>
                  <em>{preset.voice_name}</em>
                </button>
              ))}
            </div>
          )}

          <div className="slot-fields voice-advanced">
            <div className="field">
              <label>
                {(models.tts?.provider || 'elevenlabs') === 'cartesia'
                  ? t('settings.cartesiaVoices')
                  : t('settings.elevenVoices')}
              </label>
              <select
                value={
                  accountVoices.some((v) => v.id === models.tts?.voice_id)
                    ? models.tts.voice_id
                    : ''
                }
                disabled={!configured.has(models.tts?.provider || 'elevenlabs') || !accountVoices.length}
                onChange={(e) => chooseAccountVoice(e.target.value)}
              >
                <option value="">
                  {configured.has(models.tts?.provider || 'elevenlabs')
                    ? accountVoices.length
                      ? t('settings.chooseAccountVoice')
                      : t('settings.loadingVoices')
                    : t('settings.connectFirst')}
                </option>
                {accountVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                    {v.labels?.age ? ` · ${v.labels.age}` : ''}
                    {v.labels?.gender ? ` · ${v.labels.gender}` : ''}
                  </option>
                ))}
              </select>
              {voiceLoadError && <span className="field-hint bad">{voiceLoadError}</span>}
            </div>
            <div className="field">
              <label>{t('settings.customVoiceId')}</label>
              <input
                value={models.tts?.voice_id || ''}
                placeholder={t('settings.customVoicePlaceholder', {
                  provider: models.tts?.provider === 'cartesia' ? 'Cartesia' : 'ElevenLabs',
                })}
                spellCheck={false}
                onChange={(e) => chooseAccountVoice(e.target.value.trim())}
              />
            </div>
          </div>

          <div className="slot-fields">
            <div className="field">
              <label>{t('settings.ttsModel')}</label>
              <select
                value={models.tts?.model || ''}
                onChange={(e) => updateSlot('tts', 'model', e.target.value)}
              >
                {(catalog.tts_providers?.[models.tts?.provider || 'elevenlabs']?.models || []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.note ? `${t('common.optionSep')}${m.note}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>{t('settings.voiceEffect')}</label>
              <select
                value={models.tts?.effect || 'none'}
                onChange={(e) => updateSlot('tts', 'effect', e.target.value)}
              >
                {(catalog.voice_effects || []).map((effect) => (
                  <option key={effect.id} value={effect.id}>
                    {effect.label}{t('common.optionSep')}{effect.note}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="row">
            <button
              className="btn sm"
              disabled={
                !configured.has(models.tts?.provider || 'elevenlabs') ||
                !models.tts?.voice_id ||
                busy === 'voice-preview'
              }
              onClick={previewVoice}
            >
              {busy === 'voice-preview' && <i className="spinner" />}
              {busy === 'voice-preview' ? t('settings.generating') : t('settings.previewVoice')}
            </button>
            <button
              className="btn sm ghost"
              disabled={!configured.has(models.tts?.provider || 'elevenlabs')}
              onClick={() => loadAccountVoices(models.tts?.provider || 'elevenlabs')}
            >
              {t('settings.refreshVoices')}
            </button>
          </div>
        </div>

        {(() => {
          const stt = models.stt || {}
          const sttMeta = catalog.stt_providers?.[stt.provider] || null
          const sttModels = sttMeta?.models || []
          const selectedSttModel = sttModels.find((m) => m.id === stt.model)
          const sttPartials =
            typeof selectedSttModel?.partials === 'boolean'
              ? selectedSttModel.partials
              : Boolean(sttMeta?.partials)
          // A backend whose key is missing silently degrades to local whisper
          // at request time — say so here rather than letting it surprise them.
          const sttUsable =
            !sttMeta?.auth || configured.has(sttMeta.auth)
          return (
            <div className="slot">
              <div className="slot-title">
                <h3>{t('settings.hearing')}</h3>
                <span className="slot-note">
                  {t('settings.hearingSub')}
                  {stt.provider === 'auto' && voiceStatus
                    ? t('settings.hearingResolves', { label: voiceStatus.stt.label })
                    : ''}
                  {stt.provider !== 'auto' && sttPartials
                    ? t('settings.hearingPartials')
                    : stt.provider !== 'auto'
                      ? t('settings.hearingNoPartials')
                      : ''}
                </span>
              </div>

              {!sttUsable && (
                <div className="notice bad" style={{ marginBottom: '0.8rem' }}>
                  {t('settings.hearingNoKey', { label: sttMeta?.label || '' })}
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>{t('settings.provider')}</label>
                  <select
                    value={stt.provider || 'auto'}
                    onChange={(e) => {
                      const p = e.target.value
                      const first = catalog.stt_providers?.[p]?.models?.[0]?.id || ''
                      setDirty(true)
                      setModels((prev: any) => ({
                        ...prev,
                        stt: { ...prev.stt, provider: p, model: first },
                      }))
                    }}
                  >
                    {Object.entries(catalog.stt_providers || {}).map(([id, meta]) => (
                      <option key={id} value={id}>
                        {meta.label}
                        {!meta.auth || configured.has(meta.auth) ? '' : t('settings.noKey')}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>{t('settings.model')}</label>
                  <select
                    value={stt.model || ''}
                    disabled={stt.provider === 'auto'}
                    onChange={(e) => updateSlot('stt', 'model', e.target.value)}
                  >
                    <option value="">
                      {stt.provider === 'auto' ? t('settings.autoChosen') : t('settings.choose')}
                    </option>
                    {sttModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                        {m.note ? `${t('common.optionSep')}${m.note}` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label>{t('settings.recognitionLanguage')}</label>
                <select
                  value={stt.language || ''}
                  onChange={(e) => updateSlot('stt', 'language', e.target.value)}
                >
                  <option value="">{t('settings.languageDefault')}</option>
                  <option value="en">{t('settings.langEn')}</option>
                  <option value="ko">{t('settings.langKo')}</option>
                  <option value="ja">{t('settings.langJa')}</option>
                  <option value="zh">{t('settings.langZh')}</option>
                  <option value="es">{t('settings.langEs')}</option>
                  <option value="multi">{t('settings.langMulti')}</option>
                </select>
                <span className="field-hint">
                  {tx('settings.deepgramHint', { code: <span className="mono">ko</span> })}
                </span>
              </div>
            </div>
          )
        })()}

        {(() => {
          const browse = models.browse || {}
          const chosen = browse.provider || 'auto'
          const browseMeta = catalog.browse_providers?.[chosen] || null
          // "Connected" here means the key exists; `auto` needs any one of them.
          const usable =
            chosen === 'auto'
              ? Object.entries(catalog.browse_providers || {}).some(
                  ([id, meta]) => id !== 'auto' && meta.auth && configured.has(meta.auth),
                )
              : !browseMeta?.auth || configured.has(browseMeta.auth)
          return (
            <div className="slot">
              <div className="slot-title">
                <h3>{t('settings.browse')}</h3>
                <span className="slot-note">
                  {t('settings.browseSub')}
                  {browseStatus?.ready && chosen === 'auto'
                    ? t('settings.browseResolves', { provider: browseStatus.provider })
                    : ''}
                </span>
              </div>

              {!usable && (
                <div className="notice bad" style={{ marginBottom: '0.8rem' }}>
                  {chosen === 'auto'
                    ? t('settings.browseNoKeyAuto')
                    : t('settings.browseNoKey', { label: browseMeta?.label || '' })}
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>{t('settings.backend')}</label>
                  <select
                    value={chosen}
                    onChange={(e) => {
                      setDirty(true)
                      setModels((prev: any) => ({
                        ...prev,
                        browse: { ...prev.browse, provider: e.target.value },
                      }))
                    }}
                  >
                    {Object.entries(catalog.browse_providers || {}).map(([id, meta]) => (
                      <option key={id} value={id}>
                        {meta.label}
                        {id !== 'auto' && meta.auth && !configured.has(meta.auth)
                          ? t('settings.noKey')
                          : ''}
                      </option>
                    ))}
                  </select>
                  <span className="field-hint">{browseMeta?.blurb}</span>
                </div>
              </div>

              {browseMeta && !browseMeta.can_search && (
                <span className="field-hint">
                  {t('settings.browseNoSearch')}
                </span>
              )}
            </div>
          )
        })()}

        <div className="row end sticky-save">
          <button className="btn primary" disabled={busy === 'models'} onClick={saveModels}>
            {busy === 'models' && <i className="spinner" />}
            {busy === 'models' ? t('settings.saving') : t('settings.saveModels')}
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t('settings.connections')}</h2>
            <p className="muted panel-sub">
              {tx('settings.connectionsSub', { file: <span className="mono">.env</span> })}
            </p>
          </div>
        </div>

        <div className="auth-list">
          {auth.map((p, i) => {
            const c = checks[p.id] || { status: 'idle' as const }
            return (
              <AuthCard
                id={`connection-${p.id}`}
                key={p.id}
                label={p.label}
                help={p.help}
                configured={p.configured}
                masked={p.masked}
                bad={c.status === 'bad'}
                index={i}
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
                        if (e.key === 'Enter') checkAndSave(p.id)
                      }}
                    />
                  </div>

                  <VerifyLine status={c.status} detail={c.detail} />

                  <div className="row">
                    <button
                      className="btn primary sm"
                      disabled={busy === p.id || !(drafts[p.id] || '').trim()}
                      onClick={() => checkAndSave(p.id)}
                    >
                      {busy === p.id && <i className="spinner" />}
                      {busy === p.id
                        ? t('settings.checking')
                        : p.configured
                          ? t('settings.replaceKey')
                          : t('settings.checkSave')}
                    </button>
                    {p.configured && (
                      <button className="btn sm" disabled={busy === p.id} onClick={() => recheck(p.id)}>
                        {t('settings.recheck')}
                      </button>
                    )}
                    <button className="btn sm ghost" onClick={() => openUrl(p.docs_url)}>
                      {t('settings.getKey')}
                    </button>
                    {p.id === 'composio' && (
                      <button
                        className="btn sm"
                        disabled={busy === 'composio-connect'}
                        onClick={openComposio}
                      >
                        {busy === 'composio-connect' ? t('settings.opening') : t('settings.appConnect')}
                      </button>
                    )}
                    {p.id === 'kimi_code' && p.connect_url && (
                      <button className="btn sm ghost" onClick={() => openUrl(p.connect_url)}>
                        Kimi Code ↗
                      </button>
                    )}
                    {p.id === 'zai_code' && p.connect_url && (
                      <button className="btn sm ghost" onClick={() => openUrl(p.connect_url)}>
                        Z.AI ↗
                      </button>
                    )}
                    {p.configured && (
                      <button
                        className="btn sm danger"
                        disabled={busy === p.id}
                        onClick={() => clearKey(p.id)}
                      >
                        {t('settings.disconnect')}
                      </button>
                    )}
                  </div>
              </AuthCard>
            )
          })}
        </div>

        <h3 className="section-title">{t('settings.maintenance')}</h3>
        <div className="row">
          <button
            className="btn"
            disabled={busy === 'dream'}
            onClick={() => {
              setBusy('dream')
              api
                .dream()
                .then(() => flash(t('settings.dreamDone')))
                .catch((e) => flash(e.message || String(e)))
                .finally(() => setBusy(''))
            }}
          >
            {busy === 'dream' && <i className="spinner" />}
            {busy === 'dream' ? t('settings.dreaming') : t('settings.runDream')}
          </button>
          <Link to="/setup" className="btn">
            {t('settings.rerunSetup')}
          </Link>
        </div>

        {msg && <p className="msg-line">{msg}</p>}
      </section>
    </div>
  )
}
