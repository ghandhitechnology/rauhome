import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type AgentStep,
  type Job,
  type Schedule,
  type ScheduleRun,
} from '../api'
import { live } from '../live'
import { useLocale, tr } from '../i18n'
import PageSkeleton from '../components/PageSkeleton'
import './Operations.css'

function when(timestamp?: number | null) {
  if (!timestamp) return tr('ops.notScheduled')
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZoneName: 'short',
  }).format(new Date(timestamp * 1000))
}

export default function Operations() {
  const { t } = useLocale()
  const [jobs, setJobs] = useState<Job[]>([])
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [runs, setRuns] = useState<Record<string, ScheduleRun[]>>({})
  const [confirmations, setConfirmations] = useState<any[]>([])
  const [computer, setComputer] = useState<any[]>([])
  // Without this the page renders fully-formed-but-empty on first paint — five
  // empty arrays look exactly like "you have no jobs" — and then pops full a
  // moment later. `loaded` distinguishes "nothing yet" from "nothing at all".
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [goal, setGoal] = useState('')
  const [kind, setKind] = useState<'once' | 'interval' | 'cron'>('cron')
  const [expression, setExpression] = useState('0 9 * * 1-5')
  const [interval, setIntervalValue] = useState(3600)
  const [onceAt, setOnceAt] = useState('')
  const [timezone, setTimezone] = useState('Asia/Seoul')
  const [profile, setProfile] = useState<'eco' | 'balanced' | 'performance'>('balanced')
  /**
   * Live events arrive in bursts (one job transition can emit several). Fold
   * those into at most one active request and one trailing refresh, instead of
   * racing full snapshots and an N+1 schedule-history load against each other.
   */
  const refreshState = useRef({ running: false, queued: false, includeRuns: false })

  const refresh = useCallback(async (includeRuns = false) => {
    const state = refreshState.current
    state.queued = true
    state.includeRuns ||= includeRuns
    if (state.running) return
    state.running = true

    while (state.queued) {
      const loadRuns = state.includeRuns
      state.queued = false
      state.includeRuns = false
      try {
        const [jobData, scheduleData, pending, sessions] = await Promise.all([
          api.jobs(),
          api.schedules(),
          api.confirmations(),
          api.computerSessions(),
        ])
        const nextSchedules = scheduleData.schedules || []
        setJobs(jobData.jobs || [])
        setSchedules(nextSchedules)
        setConfirmations(pending.confirmations || [])
        setComputer(sessions.sessions || [])
        if (loadRuns) {
          const histories = await Promise.all(
            nextSchedules.map(async (schedule) => [
              schedule.id,
              (await api.scheduleRuns(schedule.id)).runs || [],
            ] as const),
          )
          setRuns(Object.fromEntries(histories))
        }
        setError('')
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : tr('ops.loadFailed'))
      } finally {
        // Even a failed load has to leave the skeleton, or the error banner it
        // just set would never be reachable.
        setLoaded(true)
      }
    }
    state.running = false
  }, [])

  useEffect(() => {
    void refresh(true)
    const off = live.subscribe((event) => {
      if (event.kind.startsWith('schedule_')) {
        void refresh(true)
      } else if (
        event.kind.startsWith('job_') ||
        event.kind.startsWith('computer_') ||
        event.kind.startsWith('confirm_')
      ) {
        void refresh(false)
      }
    })
    return off
  }, [refresh])

  async function createSchedule() {
    if (!name.trim() || !goal.trim()) return
    let trigger: Record<string, unknown>
    if (kind === 'cron') trigger = { kind, expression }
    else if (kind === 'interval') {
      trigger = { kind, seconds: interval, anchor: new Date().toISOString() }
    } else {
      // `datetime-local` has no offset. Send the wall time intact so the hub
      // can interpret it in the IANA timezone selected below; converting here
      // would silently use the browser's timezone instead.
      trigger = { kind, at: onceAt }
    }
    try {
      await api.createSchedule({
        name: name.trim(),
        goal: goal.trim(),
        trigger,
        timezone,
        resource_profile: profile,
        permission_policy: 'approval',
        enabled: true,
      })
      setName('')
      setGoal('')
      await refresh(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('ops.createFailed'))
    }
  }

  const activeComputer = computer.find((session) =>
    ['active', 'acting', 'verifying', 'awaiting_review'].includes(session.state),
  )
  const roots = useMemo(() => jobs.filter((job) => !job.parent_id), [jobs])

  if (!loaded) {
    return <PageSkeleton pathname="/operations" />
  }

  return (
    <div className="operations">
      <div className="ops-head">
        <div>
          <h1>{t('ops.title')}</h1>
          <p>{t('ops.lede')}</p>
        </div>
        <button className="btn" onClick={() => void refresh(true)}>
          {t('ops.refresh')}
        </button>
      </div>
      {error ? <p className="ops-error">{error}</p> : null}

      <section className="panel ops-wide">
        <div className="dash-head">
          <h2>{t('ops.jobPlans')}</h2>
          <span className="pill">{t('ops.persisted', { count: jobs.length })}</span>
        </div>
        <div className="ops-list">
          {roots.map((job) => (
            <JobTree key={job.id} job={job} jobs={jobs} />
          ))}
          {!roots.length ? <p className="muted">{t('ops.noJobs')}</p> : null}
        </div>
      </section>

      <div className="ops-grid">
        <section className="panel">
          <h2>{t('ops.newSchedule')}</h2>
          <label className="field">{t('ops.name')}<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field">{t('ops.goal')}<textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={4} /></label>
          <div className="ops-form-row">
            <label className="field">{t('ops.trigger')}
              <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                <option value="cron">{t('ops.cron')}</option>
                <option value="interval">{t('ops.interval')}</option>
                <option value="once">{t('ops.once')}</option>
              </select>
            </label>
            <label className="field">{t('ops.profile')}
              <select value={profile} onChange={(e) => setProfile(e.target.value as typeof profile)}>
                <option value="eco">{t('ops.eco')}</option>
                <option value="balanced">{t('ops.balanced')}</option>
                <option value="performance">{t('ops.performance')}</option>
              </select>
            </label>
          </div>
          {kind === 'cron' ? (
            <label className="field">{t('ops.cronField')}<input value={expression} onChange={(e) => setExpression(e.target.value)} /></label>
          ) : kind === 'interval' ? (
            <label className="field">{t('ops.seconds')}<input type="number" min={60} value={interval} onChange={(e) => setIntervalValue(Number(e.target.value))} /></label>
          ) : (
            <label className="field">{t('ops.runAt')}<input type="datetime-local" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} /></label>
          )}
          <label className="field">{t('ops.timezone')}<input value={timezone} onChange={(e) => setTimezone(e.target.value)} /></label>
          <button
            className="btn primary"
            onClick={() => void createSchedule()}
            disabled={!name.trim() || !goal.trim() || (kind === 'once' && !onceAt)}
          >
            {t('ops.create')}
          </button>
        </section>

        <section className="panel">
          <h2>{t('ops.approvals')}</h2>
          <div className="ops-list">
            {confirmations.map((confirmation) => (
              <div className="ops-card warning" key={confirmation.id}>
                <b>{confirmation.tool || t('ops.actionApproval')}</b>
                <p>{confirmation.summary}</p>
                <small>{t('ops.expires', { when: when(confirmation.expires) })}</small>
                <div className="row">
                  <button className="btn sm danger" onClick={() => api.confirm(false, confirmation.id).then(() => refresh(false)).catch(() => {})}>{t('ops.deny')}</button>
                  <button className="btn sm primary" onClick={() => api.confirm(true, confirmation.id).then(() => refresh(false)).catch(() => {})}>{t('ops.approve')}</button>
                </div>
              </div>
            ))}
            {!confirmations.length ? <p className="muted">{t('ops.nothingWaiting')}</p> : null}
          </div>
          <h3 className="section-title">{t('ops.computerSession')}</h3>
          {activeComputer ? (
            <div className="ops-card">
              <b>{activeComputer.app?.name || t('ops.frontmost')}</b>
              <p>
                {t('ops.effect', {
                  state: activeComputer.state,
                  effect: activeComputer.effect_state,
                })}
              </p>
              <small>
                {t('ops.observation', {
                  id: activeComputer.latest_observation_id || t('ops.notCaptured'),
                })}
                <br />
                {t('ops.verification', {
                  value: String(activeComputer.result?.verified ?? t('ops.pending')),
                })}
              </small>
              {activeComputer.state === 'awaiting_review' ? (
                <strong className="takeover">{t('ops.takeover')}</strong>
              ) : null}
            </div>
          ) : <p className="muted">{t('ops.noLease')}</p>}
        </section>
      </div>

      <section className="panel ops-wide">
        <h2>{t('ops.schedules')}</h2>
        <div className="ops-list">
          {schedules.map((schedule) => (
            <div className="ops-card" key={schedule.id}>
              <div className="ops-card-head">
                <div><b>{schedule.name}</b><p>{schedule.goal}</p></div>
                <span className={`pill ${schedule.enabled ? 'on' : 'off'}`}>
                  {schedule.enabled ? t('ops.enabled') : t('ops.paused')}
                </span>
              </div>
              <small>
                {schedule.trigger_kind} · {JSON.stringify(schedule.trigger)} · {schedule.timezone}<br />
                {t('ops.next', { when: when(schedule.next_run_at) })} · {schedule.resource_profile}
              </small>
              <div className="row">
                <button className="btn sm" onClick={() => api.runSchedule(schedule.id).then(() => refresh(true)).catch(() => {})}>{t('ops.runNow')}</button>
                <button className="btn sm" onClick={() => (schedule.enabled ? api.pauseSchedule(schedule.id) : api.resumeSchedule(schedule.id)).then(() => refresh(true)).catch(() => {})}>
                  {schedule.enabled ? t('ops.pause') : t('ops.resume')}
                </button>
                <button className="btn sm danger" onClick={() => api.deleteSchedule(schedule.id).then(() => refresh(true)).catch(() => {})}>{t('ops.delete')}</button>
              </div>
              <div className="run-strip">
                {(runs[schedule.id] || []).slice(0, 8).map((run) => (
                  <span key={run.id} title={JSON.stringify(run.outcome)}>
                    {when(run.nominal_at)} · {run.state} · {t('ops.attempt', { attempt: run.attempt })}
                    {run.coalesced_count > 1
                      ? t('ops.coalesced', { count: run.coalesced_count })
                      : ''}
                  </span>
                ))}
              </div>
            </div>
          ))}
          {!schedules.length ? <p className="muted">{t('ops.noSchedules')}</p> : null}
        </div>
      </section>
    </div>
  )
}

function JobTree({ job, jobs }: { job: Job; jobs: Job[] }) {
  const { t } = useLocale()
  const steps = (job.plan?.steps || []) as AgentStep[]
  const children = jobs.filter((candidate) => candidate.parent_id === job.id)
  return (
    <div className="ops-card job-tree">
      <div className="ops-card-head">
        <div><b>{job.goal}</b><p>{job.progress || job.state}</p></div>
        <span className="pill">{job.executor || 'python'} · {job.lifecycle_state || job.state}</span>
      </div>
      {steps.map((step) => (
        <div className="step-row" key={step.id}>
          <span>{step.ordinal + 1}</span>
          <div>
            <b>{step.title}</b>
            <small>
              {t('ops.stepMeta', {
                state: step.state,
                attempt: step.attempt,
                executor: step.executor,
              })}
              <br />
              {t('ops.evidence', {
                count: step.evidence?.length || 0,
                budget: JSON.stringify(job.budget || {}),
              })}
            </small>
          </div>
        </div>
      ))}
      {children.length ? <div className="job-children">{children.map((child) => <JobTree key={child.id} job={child} jobs={jobs} />)}</div> : null}
    </div>
  )
}
