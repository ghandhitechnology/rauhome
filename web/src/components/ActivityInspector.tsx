import { useEffect, useMemo, useState } from 'react'
import { api, type ActivitySpan, type AgentStep, type Job } from '../api'
import { activityFor, activityStore, useActivity } from '../activity'
import { live } from '../live'
import './ActivityInspector.css'

const ACTIVE = new Set(['queued', 'running', 'awaiting_confirm'])

export function ActivityChip({
  open,
  onToggle,
  className = '',
}: {
  open: boolean
  onToggle: () => void
  className?: string
}) {
  const { all, visible } = useActivity()
  const active = all.filter((span) => ACTIVE.has(span.status))
  return (
    <button
      type="button"
      className={`activity-chip ${open ? 'on' : ''} ${className}`}
      aria-expanded={open}
      onClick={() => {
        if (!visible) activityStore.setVisible(true)
        else onToggle()
      }}
      title={visible ? 'Open agent activity' : 'Show agent activity'}
    >
      Activity
      {!visible ? (
        <span className="activity-off">off</span>
      ) : active.length > 0 ? (
        <span className="activity-badge">{active.length}</span>
      ) : null}
    </button>
  )
}

function icon(kind: ActivitySpan['kind']) {
  return {
    reasoning: '◌',
    planning: '◇',
    tool: '⌁',
    approval: '!',
    execution: '→',
    verification: '✓',
    retry: '↻',
    completion: '●',
  }[kind]
}

function elapsed(span: ActivitySpan) {
  const seconds = Math.max(0, (span.ended || span.updated) - span.started)
  if (seconds < 1) return '<1s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

function safeJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '{"detail":"unavailable"}'
  }
}

function AgentWorkTree() {
  const [jobs, setJobs] = useState<Array<Job & { steps: AgentStep[] }>>([])
  const [steering, setSteering] = useState<Record<string, string>>({})

  async function refresh() {
    try {
      const listed = await api.jobs()
      const recent = (listed.jobs || []).slice(-12)
      const detailed = await Promise.all(
        recent.map(async (job) => {
          try {
            const result = await api.job(job.id)
            return { ...result.job, steps: result.steps || [] }
          } catch {
            return { ...job, steps: job.plan?.steps || [] }
          }
        }),
      )
      setJobs(detailed)
    } catch {
      // Activity remains useful when the job endpoint is temporarily down.
    }
  }

  useEffect(() => {
    void refresh()
    return live.subscribe((event) => {
      if (event.kind.startsWith('job_') || event.kind.startsWith('confirm_')) {
        void refresh()
      }
    })
  }, [])

  if (!jobs.length) return null
  return (
    <div className="agent-work-tree">
      <h3>Agent work</h3>
      {jobs.map((job) => {
        const active = ACTIVE.has(job.lifecycle_state || job.state)
        const paused = job.progress === 'paused by user'
        return (
          <details key={job.id} className="agent-job" open={active}>
            <summary>
              <span>{job.goal}</span>
              <em>{job.executor || 'python'} · r{job.plan_revision || 1} · {job.state}</em>
            </summary>
            <div className="agent-job-body">
              {job.steps.map((step) => (
                <div className={`agent-step status-${step.state}`} key={step.id}>
                  <strong>{step.ordinal + 1}. {step.title}</strong>
                  <span>
                    {step.executor} · attempt {step.attempt || 0}/{(step.retry_budget || 0) + 1}
                    {step.dependencies?.length ? ` · ${step.dependencies.length} deps` : ''}
                    {step.evidence?.length ? ` · ${step.evidence.length} evidence` : ''}
                  </span>
                  {step.strategy && <p>{step.strategy}</p>}
                </div>
              ))}
              {active && (
                <div className="agent-controls">
                  <button
                    type="button"
                    onClick={() =>
                      (paused ? api.resumeJob(job.id) : api.pauseJob(job.id))
                        .then(refresh)
                        .catch(() => {})
                    }
                  >
                    {paused ? 'Resume' : 'Pause'}
                  </button>
                  <button
                    type="button"
                    onClick={() => api.cancelJob(job.id).then(refresh).catch(() => {})}
                  >
                    Cancel
                  </button>
                  <label>
                    <span>Steer this plan</span>
                    <input
                      value={steering[job.id] || ''}
                      maxLength={4000}
                      onChange={(event) =>
                        setSteering((value) => ({
                          ...value,
                          [job.id]: event.target.value,
                        }))
                      }
                      onKeyDown={(event) => {
                        if (event.key !== 'Enter') return
                        const instruction = (steering[job.id] || '').trim()
                        if (!instruction) return
                        event.preventDefault()
                        void api
                          .steerJob(job.id, instruction)
                          .then(() => {
                            setSteering((value) => ({ ...value, [job.id]: '' }))
                            return refresh()
                          })
                          .catch(() => {})
                      }}
                    />
                  </label>
                </div>
              )}
            </div>
          </details>
        )
      })}
    </div>
  )
}

export default function ActivityInspector({
  turnId,
  jobId,
  global = false,
  className = '',
  defaultOpen = false,
  onClose,
}: {
  turnId?: string
  jobId?: string
  global?: boolean
  className?: string
  defaultOpen?: boolean
  onClose?: () => void
}) {
  const { all, visible } = useActivity()
  const [open, setOpen] = useState(defaultOpen)

  useEffect(() => {
    if (turnId) void activityStore.ensureTurn(turnId)
  }, [turnId])
  useEffect(() => {
    if (jobId) void activityStore.ensureJob(jobId)
  }, [jobId])

  const items = useMemo(() => {
    const filtered = activityFor(all, { turnId, jobId, global })
    return filtered.slice(-160)
  }, [all, global, jobId, turnId])

  if (!visible || items.length === 0) return null
  const active = items.filter((item) => ACTIVE.has(item.status))
  const tools = items.filter((item) => item.kind === 'tool').length
  const jobs = new Set(items.map((item) => item.job_id).filter(Boolean)).size
  const failed = items.some((item) => item.status === 'failed')
  const done = active.length === 0 && items.some((item) => item.ended)
  const label = active.at(-1)?.label || (failed ? 'Activity failed' : done ? 'Activity complete' : 'Activity')

  return (
    <section className={`activity-inspector ${open ? 'is-open' : ''} ${className}`}>
      <button
        type="button"
        className="activity-summary"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={`activity-state ${failed ? 'failed' : active.length ? 'active' : 'done'}`} />
        <span className="activity-summary-label">{label}</span>
        <span className="activity-counts">
          {tools ? `${tools} tool${tools === 1 ? '' : 's'}` : ''}
          {tools && jobs ? ' · ' : ''}
          {jobs ? `${jobs} agent${jobs === 1 ? '' : 's'}` : ''}
        </span>
        <span className="activity-chevron" aria-hidden>⌄</span>
      </button>
      {open && (
        <div className="activity-body">
          <div className="activity-toolbar">
            <span>{items.length} events</span>
            <button
              type="button"
              onClick={() => {
                activityStore.setVisible(false)
                onClose?.()
              }}
              title="Hide activity in Chat and Face"
            >
              Hide activity
            </button>
            {onClose && (
              <button type="button" onClick={onClose}>Close</button>
            )}
          </div>
          {global && <AgentWorkTree />}
          <ol className="activity-timeline" aria-label="Rau activity timeline">
            {items.map((span) => (
              <li key={span.id} className={`activity-item status-${span.status}`}>
                <span className="activity-icon" aria-hidden>{icon(span.kind)}</span>
                <div className="activity-copy">
                  <div className="activity-line">
                    <strong>{span.label}</strong>
                    <span>{elapsed(span)}</span>
                  </div>
                  {span.summary && <p>{span.summary}</p>}
                  {(span.step_id || span.job_id) && (
                    <span className="activity-correlation">
                      {span.source}
                      {span.step_id ? ` · step ${span.step_id.slice(0, 8)}` : ''}
                    </span>
                  )}
                  {Object.keys(span.details || {}).length > 0 && (
                    <details className="activity-details">
                      <summary>Technical details</summary>
                      <pre>{safeJson(span.details)}</pre>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}
