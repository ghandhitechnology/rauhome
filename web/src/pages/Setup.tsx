import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from '../router'
import { api, type Catalog, type SetupState } from '../api'
import { useLocale, type Locale } from '../i18n'
import ClawdAvatar from '../components/ClawdAvatar'
import StepOrigin from './setup/StepOrigin'
import StepIdentity from './setup/StepIdentity'
import StepBrains from './setup/StepBrains'
import StepModels from './setup/StepModels'
import StepVoice from './setup/StepVoice'
import StepForge from './setup/StepForge'
import {
  CHAT_AUTH_IDS,
  EMPTY_DRAFT,
  type Draft,
  type StepId,
  type StepProps,
  type VerifyState,
} from './setup/types'
import '../components/AuthCard.css'
import './Setup.css'

const DRAFT_KEY = 'rau.setup.draft.v2'
export const PRE_TUTORIAL_KEY = 'rau.tutorial.pre.v1'

/** Rail entries — 'welcome', 'forge' and 'done' are deliberately not on the rail. */
function loadDraft(): Draft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return EMPTY_DRAFT
    const parsed = JSON.parse(raw)
    return {
      ...EMPTY_DRAFT,
      ...parsed,
      slots: { ...EMPTY_DRAFT.slots, ...(parsed.slots || {}) },
      tts: { ...EMPTY_DRAFT.tts, ...(parsed.tts || {}) },
      stt: { ...EMPTY_DRAFT.stt, ...(parsed.stt || {}) },
    }
  } catch {
    return EMPTY_DRAFT
  }
}

type Prelude = 'language' | 'story' | 'setup'

function preludeFromStorage(hasLocale: boolean): Prelude {
  if (!hasLocale) return 'language'
  try {
    return localStorage.getItem(PRE_TUTORIAL_KEY) === 'completed' ? 'setup' : 'story'
  } catch {
    return 'story'
  }
}

export default function Setup({
  onReady,
  onFinished,
}: {
  onReady: () => void
  onFinished: () => void
}) {
  const nav = useNavigate()
  const { locale, hasChosenLocale, setLocale, t } = useLocale()
  const [prelude, setPrelude] = useState<Prelude>(() => preludeFromStorage(hasChosenLocale))
  const [storyPage, setStoryPage] = useState(0)
  const [languageBusy, setLanguageBusy] = useState(false)
  const [step, setStep] = useState<StepId>('welcome')
  const [dir, setDir] = useState<1 | -1>(1)
  const [draft, setDraft] = useState<Draft>(loadDraft)
  const [state, setState] = useState<SetupState | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [verify, setVerifyMap] = useState<Record<string, VerifyState>>({})
  const [soul, setSoul] = useState('')
  const [loadError, setLoadError] = useState('')
  const rail = [
    { id: 'origin' as StepId, label: t('setup.origin') },
    { id: 'identity' as StepId, label: t('setup.self') },
    { id: 'brains' as StepId, label: t('setup.brains') },
    { id: 'models' as StepId, label: t('setup.roles') },
    { id: 'voice' as StepId, label: t('setup.voice') },
  ]

  useEffect(() => {
    if (prelude === 'language' && hasChosenLocale) setPrelude('story')
  }, [hasChosenLocale, prelude])

  const reload = useCallback(async () => {
    const s = await api.setupState()
    setState(s)
  }, [])

  useEffect(() => {
    Promise.all([api.setupState(), api.catalog()])
      .then(([s, c]) => {
        setState(s)
        setCatalog(c)
        // Seed empty slot choices from whatever the hub already has on disk.
        setDraft((d) => {
          const next = { ...d, slots: { ...d.slots } }
          for (const slot of ['face', 'subagent', 'dream'] as const) {
            if (!next.slots[slot].provider && s.models?.[slot]?.provider) {
              next.slots[slot] = {
                provider: s.models[slot].provider,
                model: s.models[slot].model || '',
              }
            }
          }
          if (s.models?.tts) {
            next.tts = {
              ...next.tts,
              provider: s.models.tts.provider || next.tts.provider,
              voice_id: s.models.tts.voice_id || next.tts.voice_id,
              model: s.models.tts.model || next.tts.model,
              preset: s.models.tts.preset || next.tts.preset,
              effect: s.models.tts.effect || next.tts.effect,
              voice_settings: s.models.tts.voice_settings || next.tts.voice_settings,
            }
          }
          if (s.models?.stt) {
            next.stt = {
              ...next.stt,
              provider: s.models.stt.provider || next.stt.provider,
              model: s.models.stt.model ?? next.stt.model,
              language: s.models.stt.language ?? next.stt.language,
            }
          }
          return next
        })
      })
      .catch((e) => setLoadError(e?.message || String(e)))
  }, [])

  useEffect(() => {
    // Storage can be unavailable (private windows, blocked contexts); the
    // wizard still works, the draft just does not survive a reload.
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
    } catch {
      /* keep the draft in memory only */
    }
  }, [draft])

  const patch = useCallback((p: Partial<Draft>) => setDraft((d) => ({ ...d, ...p })), [])
  const setVerify = useCallback(
    (id: string, v: VerifyState) => setVerifyMap((m) => ({ ...m, [id]: v })),
    [],
  )

  /** Steps in play — the identity step drops out entirely on the fresh path. */
  const order = useMemo<StepId[]>(() => {
    const base: StepId[] = ['welcome', 'origin', 'identity', 'brains', 'models', 'voice', 'forge', 'done']
    return draft.origin === 'fresh' ? base.filter((s) => s !== 'identity') : base
  }, [draft.origin])

  const go = useCallback(
    (to: StepId) => {
      setDir(order.indexOf(to) >= order.indexOf(step) ? 1 : -1)
      setStep(to)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    },
    [order, step],
  )

  const idx = order.indexOf(step)
  const next = order[idx + 1]
  const prev = order[idx - 1]

  const chatConnected = (state?.providers || []).some(
    (p) => p.configured && CHAT_AUTH_IDS.includes(p.id),
  )
  const slotsReady = (['face', 'subagent', 'dream'] as const).every(
    (s) => draft.slots[s].provider && draft.slots[s].model.trim(),
  )

  /** Why "Continue" is disabled, or empty when it is not. */
  const blocker = useMemo(() => {
    if (step === 'origin' && !draft.origin) return 'Pick a starting point.'
    if (step === 'identity') {
      if (draft.identity.trim().length < 40) return 'identity.md needs a little more.'
      if (draft.backstory.trim().length < 80) return 'backstory.md needs a little more.'
    }
    if (step === 'brains' && !chatConnected) return 'Connect at least one provider to continue.'
    if (step === 'models' && !slotsReady) return 'Every role needs a provider and a model.'
    return ''
  }, [step, draft, chatConnected, slotsReady])

  const stepProps: StepProps = { draft, patch, state, catalog, reload, verify, setVerify, go }

  // Enter advances, Escape goes back — but never while typing in a textarea.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName
      if (e.key === 'Enter' && tag !== 'TEXTAREA' && tag !== 'INPUT' && !blocker && next) {
        if (step !== 'forge' && step !== 'done') go(next)
      }
      if (e.key === 'Escape' && prev && step !== 'forge') go(prev)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [blocker, next, prev, step, go])

  function finish() {
    onFinished()
    localStorage.removeItem(DRAFT_KEY)
  }

  async function chooseLanguage(next: Locale) {
    setLanguageBusy(true)
    setDraft((current) => ({
      ...current,
      stt: { ...current.stt, language: next },
    }))
    try {
      await setLocale(next)
    } catch {
      // The local choice is already active; the next successful settings save
      // will make the backend durable too.
    } finally {
      setLanguageBusy(false)
      setPrelude('story')
    }
  }

  function finishStory() {
    try {
      localStorage.setItem(PRE_TUTORIAL_KEY, 'completed')
    } catch {
      /* the setup can proceed without durable tutorial state */
    }
    setPrelude('setup')
  }

  // The rail drops the identity step on the fresh path, so progress counts the
  // steps actually in play rather than the full list.
  const visibleRail = rail.filter((r) => order.includes(r.id))
  const railIdx = visibleRail.findIndex((r) => r.id === step)
  const showChrome = step !== 'welcome'

  if (prelude === 'language') {
    return (
      <div className="setup-prelude language-gate">
        <div className="language-mark" aria-hidden>
          <i />
          <span>Rau</span>
        </div>
        <p className="eyebrow">Hello · 안녕하세요</p>
        <h1>{t('language.title')}</h1>
        <p className="prelude-lede">{t('language.lede')}</p>
        <div className="language-options">
          <button
            type="button"
            disabled={languageBusy}
            onClick={() => void chooseLanguage('en')}
          >
            <strong>{t('language.english')}</strong>
            <span>{t('language.englishNote')}</span>
          </button>
          <button
            type="button"
            disabled={languageBusy}
            onClick={() => void chooseLanguage('ko')}
          >
            <strong>{t('language.korean')}</strong>
            <span>{t('language.koreanNote')}</span>
          </button>
        </div>
      </div>
    )
  }

  if (prelude === 'story') {
    const pages = [
      {
        image: '/onboarding/dreaming-colored-pencil.webp',
        eyebrow: t('intro.eyebrow.1'),
        title: t('intro.title.1'),
        body: t('intro.body.1'),
      },
      {
        image: '/onboarding/deep-work-colored-pencil.webp',
        eyebrow: t('intro.eyebrow.2'),
        title: t('intro.title.2'),
        body: t('intro.body.2'),
      },
      {
        image: '/onboarding/presence-colored-pencil.webp',
        eyebrow: t('intro.eyebrow.3'),
        title: t('intro.title.3'),
        body: t('intro.body.3'),
      },
    ]
    const page = pages[storyPage]
    return (
      <div className="setup-prelude intro-story">
        <button type="button" className="intro-skip" onClick={finishStory}>
          {t('intro.skip')}
        </button>
        <div key={`${locale}-${storyPage}`} className="intro-stage">
          <figure className="intro-art">
            <img src={page.image} alt="" />
          </figure>
          <div className="intro-copy">
            <p className="eyebrow">{page.eyebrow}</p>
            <h1>{page.title}</h1>
            <p>{page.body}</p>
          </div>
        </div>
        <footer className="intro-controls">
          <button
            type="button"
            className="btn ghost"
            disabled={storyPage === 0}
            onClick={() => setStoryPage((value) => Math.max(0, value - 1))}
          >
            ← {t('intro.back')}
          </button>
          <div className="intro-dots" role="group" aria-label="Introduction progress">
            {pages.map((_, index) => (
              <button
                type="button"
                key={index}
                className={index === storyPage ? 'active' : ''}
                aria-label={`${index + 1}`}
                onClick={() => setStoryPage(index)}
              />
            ))}
          </div>
          <button
            type="button"
            className="btn primary"
            onClick={() => {
              if (storyPage === pages.length - 1) finishStory()
              else setStoryPage((value) => value + 1)
            }}
          >
            {storyPage === pages.length - 1 ? t('intro.begin') : `${t('intro.continue')} →`}
          </button>
        </footer>
      </div>
    )
  }

  return (
    <div className="setup">
      {showChrome && (
        <nav className="rail" aria-label={t('setup.progress')}>
          {visibleRail.map((r) => {
            const rIdx = order.indexOf(r.id)
            const done = rIdx < idx
            const active = r.id === step
            return (
              <button
                key={r.id}
                className={`rail-step ${active ? 'active' : ''} ${done ? 'done' : ''}`}
                disabled={rIdx > idx}
                onClick={() => go(r.id)}
              >
                <span className="rail-mark">{done ? <i className="tick" /> : <i className="dot" />}</span>
                <span className="rail-label">{r.label}</span>
              </button>
            )
          })}
        </nav>
      )}

      <div className="setup-viewport">
        {loadError && (
          <div className="notice bad" style={{ marginBottom: '1.25rem' }}>
            Could not reach the hub: {loadError}
          </div>
        )}

        <div key={step} className={`step-frame ${dir === 1 ? 'fwd' : 'back'}`}>
          {step === 'welcome' && (
            <div className="step step-center welcome">
              <div className="welcome-eyes">
                <ClawdAvatar emotion="curious" />
              </div>
              <p className="eyebrow">{t('setup.welcomeEyebrow')}</p>
              <h1 className="welcome-title">{t('setup.welcomeTitle')}</h1>
              <p className="welcome-lede">
                {t('setup.welcomeBody')}
              </p>
              <div className="row" style={{ justifyContent: 'center', marginTop: '1.5rem' }}>
                <button className="btn primary" onClick={() => go('origin')}>
                  {t('setup.begin')}
                </button>
                {state?.complete && (
                  <button className="btn ghost" onClick={() => nav('/')}>
                    {t('setup.already')}
                  </button>
                )}
              </div>
              {state?.identity_ready && (
                <p className="step-note subtle" style={{ marginTop: '1.5rem' }}>
                  There is already a soul.md on disk. Running setup again replaces it — a timestamped
                  backup is kept either way.
                </p>
              )}
            </div>
          )}

          {step === 'origin' && <StepOrigin {...stepProps} />}
          {step === 'identity' && <StepIdentity {...stepProps} />}
          {step === 'brains' && <StepBrains {...stepProps} />}
          {step === 'models' && <StepModels {...stepProps} />}
          {step === 'voice' && <StepVoice {...stepProps} />}
          {step === 'forge' && (
            <StepForge
              {...stepProps}
              onForged={(s) => {
                setSoul(s)
                onReady()
                go('done')
              }}
            />
          )}

          {step === 'done' && (
            <div className="step">
              <header className="step-head">
                <p className="eyebrow">{t('setup.awake')}</p>
                <h2>{t('setup.doneTitle')}</h2>
                <p className="step-lede">
                  This is the compiled <span className="mono">soul.md</span>. Nightly dreams may
                  rewrite it; editing the source files from the Identity page hard-steers it back.
                </p>
              </header>
              <pre className="doc soul-doc">{soul || '—'}</pre>
              <div className="row end" style={{ marginTop: '1.25rem' }}>
                <button className="btn primary" onClick={finish}>
                  {t('setup.startTalking')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {showChrome && step !== 'forge' && step !== 'done' && (
        <footer className="setup-foot">
          <div className="foot-left">
            {prev && (
              <button className="btn ghost" onClick={() => go(prev)}>
                {t('setup.back')}
              </button>
            )}
          </div>
          <div className="foot-right">
            {blocker && <span className="blocker">{blocker}</span>}
            {step === 'voice' && !state?.voice_ready && (
              <button
                className="btn ghost"
                onClick={() => {
                  patch({ voiceSkipped: true })
                  go('forge')
                }}
              >
                {t('setup.skipVoice')}
              </button>
            )}
            {next && (
              <button className="btn primary" disabled={!!blocker} onClick={() => go(next)}>
                {next === 'forge' ? t('setup.bringUp') : t('setup.continue')}
              </button>
            )}
          </div>
        </footer>
      )}

      {showChrome && railIdx >= 0 && (
        <div className="setup-progress" aria-hidden>
          <i style={{ width: `${((railIdx + 1) / visibleRail.length) * 100}%` }} />
        </div>
      )}
    </div>
  )
}
