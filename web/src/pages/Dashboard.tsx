import { useEffect, useState } from 'react'
import { Link } from '../router'
import ClawdAvatar from '../components/ClawdAvatar'
import PageSkeleton from '../components/PageSkeleton'
import { api, type Job } from '../api'
import { useLocale } from '../i18n'
import { live as liveChannel } from '../live'
import './Dashboard.css'

const HARD_STATES: Record<string, string> = {
  idle: 'nothing running',
  running: 'working',
  awaiting_confirm: 'waiting on you',
  done: 'finished',
  cancelled: 'cancelled',
  failed: 'failed',
}

const EFFORTS = ['low', 'medium', 'high', 'max'] as const

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
      setEffortError(err instanceof Error ? err.message : 'Could not update effort')
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
    { label: 'Voice', value: status?.voice_pipeline ? 'up' : 'off', on: !!status?.voice_pipeline },
    { label: 'Face', value: status?.face_busy ? 'busy' : 'free', on: !!status?.face_busy },
    {
      label: 'MCP',
      value: status?.mcp?.servers?.composio?.configured ? 'composio' : '—',
      on: !!status?.mcp?.servers?.composio?.configured,
    },
    { label: 'Diary today', value: String(status?.memory?.today_entries ?? 0), on: (status?.memory?.today_entries ?? 0) > 0 },
    { label: 'Identity', value: status?.identity_ready ? 'ready' : 'setup', on: !!status?.identity_ready },
    { label: 'Skills', value: String(status?.skills_count ?? skills.length), on: (status?.skills_count ?? skills.length) > 0 },
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
              {live ? 'live' : 'polling'}
            </span>
            <span className={`pill ${status?.listening ? 'on' : 'off'}`}>
              <i className="pill-dot" />
              {status?.listening ? 'listening' : 'quiet'}
            </span>
          </div>
        </div>

        <p className="dash-sub">
          Systems room. <Link to="/">Back to talk</Link>.
        </p>

        <ClawdAvatar emotion={emotion} />
        <p className="line">{status?.text || '—'}</p>

        <div className="row">
          <button
            className="btn"
            onClick={() => api.control(status?.listening ? 'stop' : 'start').then(refresh).catch(() => {})}
          >
            {status?.listening ? 'Pause listening' : 'Start listening'}
          </button>
          <button className="btn" onClick={() => api.control('test').catch(() => {})}>
            Test voice
          </button>
          <button className="btn danger" onClick={() => api.control('shutdown').catch(() => {})}>
            Shutdown face
          </button>
        </div>

        <h3 className="section-title">Model effort</h3>
        <p className="muted" style={{ marginTop: 0 }}>Whole-runtime power profile</p>
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
              {profile}
            </button>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 0 }}>
          Thinking depth for the current provider/model. Levels adapt to what that
          backend supports. Also `/effort …` in talk for face.
        </p>
        {effortError ? (
          <p className="muted" style={{ color: 'var(--danger)', marginTop: 0 }}>
            {effortError}
          </p>
        ) : null}
        {([
          ['face', 'Face'],
          ['subagent', 'Subagent'],
          ['dream', 'Dream'],
        ] as const).map(([slot, label]) => {
          const view = effort.slots[slot]
          const allowed = view?.supported ? view.allowed || [] : []
          return (
            <div key={slot} className="effort-row">
              <span className="effort-label">{label}</span>
              {!view?.supported || allowed.length === 0 ? (
                <span className="muted" style={{ fontSize: '0.85rem' }}>
                  No reasoning control for this model
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
                      {level}
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
                    ? `Set every slot that supports ${level}`
                    : `No current model accepts ${level}`
                }
              >
                All → {level}
              </button>
            )
          })}
        </div>

        {confirm && (
          <div className="confirm-box">
            <h3>Confirm</h3>
            <p>{confirm.summary}</p>
            <div className="row end">
              <button className="btn danger sm" onClick={() => api.confirm(false, confirm.id).then(refresh).catch(() => {})}>
                Deny
              </button>
              <button className="btn primary sm" onClick={() => api.confirm(true, confirm.id).then(refresh).catch(() => {})}>
                Allow
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
            {HARD_STATES[hardState] || hardState}
          </span>
        </div>

        {activeGoal?.text && (
          <div className="goal-box">
            <div className="dash-head" style={{ marginBottom: '0.35rem' }}>
              <h3 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 400 }}>Active goal</h3>
              <button className="btn sm danger" onClick={() => api.clearGoal().then(refresh).catch(() => {})}>Clear</button>
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
            {activeJobs.length > 1 ? `Cancel all (${activeJobs.length})` : t('dashboard.cancel')}
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
                  Stop
                </button>
              </div>
            ))}
          </div>
        )}

        <h3 className="section-title">Skills</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Always available. Slash in talk: {skills.slice(0, 4).map((s) => s.slash).join(' ')}…
        </p>
        <div className="skills-list">
          {skills.map((s) => (
            <div key={s.name} className="skill-chip" title={s.description}>
              <code>{s.slash}</code>
              <span>{s.name}</span>
            </div>
          ))}
          {skills.length === 0 && <span className="muted">No skills loaded</span>}
        </div>

        <h3 className="section-title">Systems</h3>
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
