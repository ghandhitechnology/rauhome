import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ClawdAvatar from '../components/ClawdAvatar'
import { api, type Job } from '../api'
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

export default function Dashboard() {
  const [status, setStatus] = useState<any>(null)
  const [emotion, setEmotion] = useState('idle')
  const [goal, setGoal] = useState('')
  const [skills, setSkills] = useState<any[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [effort, setEffort] = useState({ face: 'medium', subagent: 'high', dream: 'medium' })
  const [live, setLive] = useState(false)
  const [busyEffort, setBusyEffort] = useState('')

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
        setEffort({
          face: ef.face || 'medium',
          subagent: ef.subagent || 'high',
          dream: ef.dream || 'medium',
        })
      } else if (s.effort) {
        setEffort({
          face: s.effort.face || 'medium',
          subagent: s.effort.subagent || 'high',
          dream: s.effort.dream || 'medium',
        })
      }
    } catch {
      /* hub down */
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2000)
    let ws: WebSocket | null = null
    try {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => setLive(true)
      ws.onclose = () => setLive(false)
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data)
          if (data.kind === 'ping' || data.kind === 'hello') {
            if (data.status) setStatus(data.status)
          }
          if (data.kind === 'hard_task' || data.kind === 'confirm_request') refresh()
        } catch {
          /* ignore */
        }
      }
    } catch {
      /* ignore */
    }
    return () => {
      clearInterval(id)
      ws?.close()
    }
  }, [])

  async function setSlotEffort(slot: 'face' | 'subagent' | 'dream' | 'all', level: string) {
    setBusyEffort(slot)
    try {
      const body = slot === 'all' ? { all: level } : { [slot]: level }
      const res = await api.putEffort(body)
      setEffort({
        face: res.face || level,
        subagent: res.subagent || level,
        dream: res.dream || level,
      })
    } finally {
      setBusyEffort('')
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
    return (
      <div className="dash grid-2">
        {[0, 1].map((i) => (
          <section key={i} className="panel">
            <div className="skeleton skeleton-line" style={{ width: '40%', height: '1.6rem' }} />
            <div className="skeleton" style={{ height: '9rem', marginTop: '1rem' }} />
          </section>
        ))}
      </div>
    )
  }

  return (
    <div className="dash grid-2">
      <section className="panel">
        <div className="dash-head">
          <h2>Presence</h2>
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
            onClick={() => api.control(status?.listening ? 'stop' : 'start').then(refresh)}
          >
            {status?.listening ? 'Pause listening' : 'Start listening'}
          </button>
          <button className="btn" onClick={() => api.control('test')}>
            Test voice
          </button>
          <button className="btn danger" onClick={() => api.control('shutdown')}>
            Shutdown face
          </button>
        </div>

        <h3 className="section-title">Model effort</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Thinking depth for face / deep work / dream. Also `/effort low|medium|high|max` in talk.
        </p>
        {([
          ['face', 'Face'],
          ['subagent', 'Subagent'],
          ['dream', 'Dream'],
        ] as const).map(([slot, label]) => (
          <div key={slot} className="effort-row">
            <span className="effort-label">{label}</span>
            <div className="effort-seg">
              {EFFORTS.map((level) => (
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
          </div>
        ))}
        <div className="row" style={{ marginTop: '0.75rem' }}>
          {EFFORTS.map((level) => (
            <button
              key={level}
              className="btn sm"
              disabled={busyEffort !== ''}
              onClick={() => setSlotEffort('all', level)}
            >
              All → {level}
            </button>
          ))}
        </div>

        {confirm && (
          <div className="confirm-box">
            <h3>Confirm</h3>
            <p>{confirm.summary}</p>
            <div className="row end">
              <button className="btn danger sm" onClick={() => api.confirm(false, confirm.id).then(refresh)}>
                Deny
              </button>
              <button className="btn primary sm" onClick={() => api.confirm(true, confirm.id).then(refresh)}>
                Allow
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="dash-head">
          <h2>Deep work</h2>
          <span className={`pill ${hardState === 'running' ? 'on' : 'off'}`}>
            <i className="pill-dot" />
            {HARD_STATES[hardState] || hardState}
          </span>
        </div>

        {activeGoal?.text && (
          <div className="goal-box">
            <div className="dash-head" style={{ marginBottom: '0.35rem' }}>
              <h3 style={{ margin: 0, fontFamily: 'var(--font-display)', fontWeight: 400 }}>Active goal</h3>
              <button className="btn sm danger" onClick={() => api.clearGoal().then(refresh)}>Clear</button>
            </div>
            <p style={{ margin: 0 }}>{activeGoal.text}</p>
          </div>
        )}

        {hard.goal && <p className="hard-goal">{hard.goal}</p>}
        {hard.progress && <p className="hard-progress">{hard.progress}</p>}
        {hard.result && hardState === 'done' && <pre className="doc hard-result">{hard.result}</pre>}

        <div className="field">
          <label>New goal</label>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && goal.trim()) api.startHardTask(goal).then(refresh)
            }}
            placeholder="What should Rau dig into?"
          />
        </div>

        <div className="row">
          <button
            className="btn primary"
            disabled={!goal.trim()}
            onClick={() =>
              api.startHardTask(goal).then(() => {
                setGoal('')
                refresh()
              })
            }
          >
            Start deep work
          </button>
          <button
            className="btn danger"
            disabled={activeJobs.length === 0}
            onClick={() => api.cancelHardTask().then(refresh)}
          >
            {activeJobs.length > 1 ? `Cancel all (${activeJobs.length})` : 'Cancel'}
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
                  onClick={() => api.cancelJob(j.id).then(refresh)}
                >
                  Stop
                </button>
              </div>
            ))}
          </div>
        )}

        <h3 className="section-title">Skills</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Always on. Slash in talk: {skills.slice(0, 4).map((s) => s.slash).join(' ')}…
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
