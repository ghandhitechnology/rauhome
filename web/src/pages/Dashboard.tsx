import { useEffect, useState } from 'react'
import { Link } from '../router'
import ClawdAvatar from '../components/ClawdAvatar'
import PageSkeleton from '../components/PageSkeleton'
import { api, type Job } from '../api'
import { useLocale, type TranslationKey } from '../i18n'
import { live as liveChannel } from '../live'
import './Dashboard.css'

const EFFORTS = ['low', 'medium', 'high', 'max'] as const
type EffortLevel = (typeof EFFORTS)[number]

const HARD_STATES = [
  'idle',
  'running',
  'awaiting_confirm',
  'done',
  'cancelled',
  'failed',
] as const

/** The hub's own vocabulary, said in the reader's language. */
function hardStateLabel(state: string, t: (key: TranslationKey) => string): string {
  return (HARD_STATES as readonly string[]).includes(state)
    ? t(`hard.${state as (typeof HARD_STATES)[number]}`)
    : state
}

type EffortSlotView = {
  supported: boolean
  allowed: string[]
  effort: string
}

type EffortState = {
  face: string
  subagent: string
  dream: string
  slots: Record<'face' | 'subagent' | 'dream', EffortSlotView>
}

const EMPTY_SLOT: EffortSlotView = {
  supported: true,
  allowed: [...EFFORTS],
  effort: 'medium',
}

function parseEffort(raw: any): EffortState {
  const slots = {
    face: (raw?.slots?.face as EffortSlotView) || {
      ...EMPTY_SLOT,
      effort: raw?.face || 'medium',
    },
    subagent: (raw?.slots?.subagent as EffortSlotView) || {
      ...EMPTY_SLOT,
      effort: raw?.subagent || 'high',
    },
    dream: (raw?.slots?.dream as EffortSlotView) || {
      ...EMPTY_SLOT,
      effort: raw?.dream || 'medium',
    },
  }
  return {
    face: slots.face.effort || raw?.face || 'medium',
    subagent: slots.subagent.effort || raw?.subagent || 'high',
    dream: slots.dream.effort || raw?.dream || 'medium',
    slots,
  }
}

export default function Dashboard() {
  const { t } = useLocale()
  const [status, setStatus] = useState<any>(null)
  const [emotion, setEmotion] = useState('idle')
  const [goal, setGoal] = useState('')
  const [skills, setSkills] = useState<any[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [effort, setEffort] = useState<EffortState>(() => parseEffort(null))
  const [live, setLive] = useState(false)
  const [busyEffort, setBusyEffort] = useState('')
  const [effortError, setEffortError] = useState('')
  const [resourceProfile, setResourceProfile] = useState<'eco' | 'balanced' | 'performance'>('balanced')

  async function refresh() {
    try {
      const [s, e, sk, jb, ef] = await Promise.all([
        api.status(),
        api.emotion(),
        api.skills().catch(() => ({ skills: [] })),
        api.jobs().catch(() => ({ jobs: [], max_parallel: 1 })),
        api.effort().catch(() => null),
      ])
      setStatus(s)
      setEmotion((e.emotion || 'idle').toLowerCase())
      setSkills(sk.skills || [])
      setJobs(jb.jobs || [])
      if (ef) {
        setEffort(parseEffort(ef))
      } else if (s.effort) {
        setEffort(parseEffort(s.effort))
      }
      setResourceProfile(s.resource_profile?.name || 'balanced')
    } catch {
      /* hub down */
    }
  }

  useEffect(() => {
    refresh()
    // WebSocket events are the normal update path. The slow fallback only
    // probes while disconnected, avoiding repeated provider/memory scans.
    const id = setInterval(() => {
      if (!liveChannel.isConnected()) void refresh()
    }, 15_000)
    // One socket per page, shared with the body controller — two would give
    // the dashboard and the avatar beside it two views of the same turn.
    const offStatus = liveChannel.onStatus(setLive)
    const offEvents = liveChannel.subscribe((data) => {
      if (data.kind === 'ping' || data.kind === 'hello') {
        if (data.status) setStatus(data.status)
      }
      if (data.kind === 'hard_task' || data.kind === 'confirm_request') refresh()
    })
    return () => {
      clearInterval(id)
      offStatus()
      offEvents()
    }
  }, [])

  async function setSlotEffort(slot: 'face' | 'subagent' | 'dream' | 'all', level: string) {
    setBusyEffort(slot)
    setEffortError('')
    try {
      const body = slot === 'all' ? { all: level } : { [slot]: level }
      const res = await api.putEffort(body)
      setEffort(parseEffort(res))
    } catch (err) {
      setEffortError(err instanceof Error ? err.message : t('dashboard.effortFailed'))
    } finally {
      setBusyEffort('')
    }
  }

  async function startGoal() {
    const text = goal.trim()
    if (!text) return
    try {
      await api.startHardTask(text)
      setGoal('')
      refresh()
    } catch {
      /* hub down — keep the goal text so it can be retried */
    }
  }

  const confirm = status?.confirm
  const hard = status?.hard_task || {}
  const hardState = hard.state || 'idle'
  const activeJobs = jobs.filter((j) => j.state === 'running' || j.state === 'awaiting_confirm')
  const activeGoal = status?.goal

  const stats = [
    { label: t('stat.voice'), value: status?.voice_pipeline ? t('stat.up') : t('stat.off'), on: !!status?.voice_pipeline },
    { label: t('stat.face'), value: status?.face_busy ? t('stat.busy') : t('stat.free'), on: !!status?.face_busy },
    {
      label: t('stat.mcp'),
      value: status?.mcp?.servers?.composio?.configured ? 'composio' : '—',
      on: !!status?.mcp?.servers?.composio?.configured,
    },
    { label: t('stat.diary'), value: String(status?.memory?.today_entries ?? 0), on: (status?.memory?.today_entries ?? 0) > 0 },
    { label: t('stat.identity'), value: status?.identity_ready ? t('stat.ready') : t('stat.setup'), on: !!status?.identity_ready },
    { label: t('stat.skills'), value: String(status?.skills_count ?? skills.length), on: (status?.skills_count ?? skills.length) > 0 },
  ]

  if (!status) {
    return <PageSkeleton pathname="/dashboard" />
  }

  return (
    <div className="dash grid-2">
      <section className="panel">
        <div className="dash-head">
          <h2>{t('dashboard.presence')}</h2>
          <div className="row">
            <span className={`pill ${live ? 'on' : 'off'}`}>
              <i className="pill-dot" />
              {live ? t('dashboard.live') : t('dashboard.polling')}
            </span>
            <span className={`pill ${status?.listening ? 'on' : 'off'}`}>
              <i className="pill-dot" />
              {status?.listening ? t('dashboard.listening') : t('dashboard.quiet')}
            </span>
          </div>
        </div>

        <p className="dash-sub">
          {t('dashboard.systemsRoom')} <Link to="/">{t('dashboard.backToTalk')}</Link>
        </p>

        <ClawdAvatar emotion={emotion} />
        <p className="line">{status?.text || '—'}</p>

        <div className="row">
          <button
            className="btn"
            onClick={() => api.control(status?.listening ? 'stop' : 'start').then(refresh).catch(() => {})}
          >
            {status?.listening ? t('dashboard.pauseListening') : t('dashboard.startListening')}
          </button>
          <button className="btn" onClick={() => api.control('test').catch(() => {})}>
            {t('dashboard.testVoice')}
          </button>
          <button className="btn danger" onClick={() => api.control('shutdown').catch(() => {})}>
            {t('dashboard.shutdownFace')}
          </button>
        </div>

        <h3 className="section-title">{t('dashboard.modelEffort')}</h3>
        <p className="muted" style={{ marginTop: 0 }}>{t('dashboard.powerProfile')}</p>
        <div className="effort-seg" style={{ marginBottom: '1rem' }}>
          {(['eco', 'balanced', 'performance'] as const).map((profile) => (
            <button
              key={profile}
              className={`effort-btn ${resourceProfile === profile ? 'active' : ''}`}
              onClick={() => {
                api.putResourceProfile(profile).then((result) => {
                  setResourceProfile(result.name)
                  document.documentElement.dataset.resourceProfile = result.name
                }).catch(() => {})
              }}
            >
              {t(`profile.${profile}`)}
            </button>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 0 }}>{t('dashboard.effortHelp')}</p>
        {effortError ? (
          <p className="muted" style={{ color: 'var(--danger)', marginTop: 0 }}>
            {effortError}
          </p>
        ) : null}
        {(['face', 'subagent', 'dream'] as const).map((slot) => {
          const view = effort.slots[slot]
          const allowed = view?.supported ? view.allowed || [] : []
          return (
            <div key={slot} className="effort-row">
              <span className="effort-label">{t(`slot.${slot}`)}</span>
              {!view?.supported || allowed.length === 0 ? (
                <span className="muted" style={{ fontSize: '0.85rem' }}>
                  {t('dashboard.noReasoning')}
                </span>
              ) : (
                <div className="effort-seg">
                  {allowed.map((level) => (
                    <button
                      key={level}
                      className={`effort-btn ${effort[slot] === level ? 'active' : ''}`}
                      disabled={busyEffort === slot || busyEffort === 'all'}
                      onClick={() => setSlotEffort(slot, level)}
                    >
                      {t(`effort.${level as EffortLevel}`)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        <div className="row" style={{ marginTop: '0.75rem' }}>
          {EFFORTS.map((level) => {
            const anyAccepts = (['face', 'subagent', 'dream'] as const).some((slot) => {
              const view = effort.slots[slot]
              return view?.supported && (view.allowed || []).includes(level)
            })
            return (
              <button
                key={level}
                className="btn sm"
                disabled={busyEffort !== '' || !anyAccepts}
                onClick={() => setSlotEffort('all', level)}
                title={
                  anyAccepts
                    ? t('dashboard.allToTitle', { level: t(`effort.${level}`) })
                    : t('dashboard.allToNone', { level: t(`effort.${level}`) })
                }
              >
                {t('dashboard.allTo', { level: t(`effort.${level}`) })}
              </button>
            )
          })}
        </div>

        {confirm && (
          <div className="confirm-box">
            <h3>{t('dashboard.confirm')}</h3>
            <p>{confirm.summary}</p>
            <div className="row end">
              <button className="btn danger sm" onClick={() => api.confirm(false, confirm.id).then(refresh).catch(() => {})}>
                {t('talk.deny')}
              </button>
              <button className="btn primary sm" onClick={() => api.confirm(true, confirm.id).then(refresh).catch(() => {})}>
                {t('talk.allow')}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="panel" data-tour="deep-work">
        <div className="dash-head">
          <h2>{t('dashboard.deepWork')}</h2>
          <span className={`pill ${hardState === 'running' ? 'on' : 'off'}`}>
            <i className="pill-dot" />
            {hardStateLabel(hardState, t)}
          </span>
        </div>

        {activeGoal?.text && (
          <div className="goal-box">
            <div className="dash-head" style={{ marginBottom: '0.35rem' }}>
              <h3 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 400 }}>
                {t('dashboard.activeGoal')}
              </h3>
              <button className="btn sm danger" onClick={() => api.clearGoal().then(refresh).catch(() => {})}>
                {t('dashboard.clear')}
              </button>
            </div>
            <p style={{ margin: 0 }}>{activeGoal.text}</p>
          </div>
        )}

        {hard.goal && <p className="hard-goal">{hard.goal}</p>}
        {hard.progress && <p className="hard-progress">{hard.progress}</p>}
        {hard.result && hardState === 'done' && <pre className="doc hard-result">{hard.result}</pre>}

        <div className="field">
          <label>{t('dashboard.newGoal')}</label>
          <input
            data-tour="deep-work-goal"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') startGoal()
            }}
            placeholder={t('dashboard.goalPlaceholder')}
          />
        </div>

        <div className="row">
          <button className="btn primary" disabled={!goal.trim()} onClick={startGoal}>
            {t('dashboard.start')}
          </button>
          <button
            className="btn danger"
            disabled={activeJobs.length === 0}
            onClick={() => api.cancelHardTask().then(refresh).catch(() => {})}
          >
            {activeJobs.length > 1
              ? t('dashboard.cancelAll', { count: activeJobs.length })
              : t('dashboard.cancel')}
          </button>
        </div>

        {/* Several goals can run at once, so each needs its own stop button —
            the button above deliberately stops everything. */}
        {activeJobs.length > 0 && (
          <div className="job-list">
            {activeJobs.map((j) => (
              <div key={j.id} className="job-row">
                <span className="job-goal">{j.goal}</span>
                <span className="job-state">{j.progress || j.state}</span>
                <button
                  className="btn danger sm"
                  onClick={() => api.cancelJob(j.id).then(refresh).catch(() => {})}
                >
                  {t('dashboard.stop')}
                </button>
              </div>
            ))}
          </div>
        )}

        <h3 className="section-title">{t('dashboard.skills')}</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          {t('dashboard.skillsHelp', { list: skills.slice(0, 4).map((s) => s.slash).join(' ') })}
        </p>
        <div className="skills-list">
          {skills.map((s) => (
            <div key={s.name} className="skill-chip" title={s.description}>
              <code>{s.slash}</code>
              <span>{s.name}</span>
            </div>
          ))}
          {skills.length === 0 && <span className="muted">{t('dashboard.noSkills')}</span>}
        </div>

        <h3 className="section-title">{t('dashboard.systems')}</h3>
        <div className="status-grid stagger">
          {stats.map((s, i) => (
            <div key={s.label} className={s.on ? 'on' : ''} style={{ '--i': i } as React.CSSProperties}>
              <span>{s.label}</span>
              <b>{s.value}</b>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
