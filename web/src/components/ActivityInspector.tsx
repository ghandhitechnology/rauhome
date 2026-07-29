import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type ActivitySpan, type AgentStep, type Job } from '../api'
import {
  activityFor,
  activityStore,
  type ActivityAgent,
  useActivity,
} from '../activity'
import { live } from '../live'
import { useLocale } from '../i18n'
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
  const { t } = useLocale()
  const { all, visible } = useActivity()
  const active = all.filter((span) => ACTIVE.has(span.status))
  return (
    <button
      type="button"
      data-tour="activity"
      className={`activity-chip ${open ? 'on' : ''} ${className}`}
      aria-expanded={open}
      onClick={() => {
        if (!visible) activityStore.setVisible(true)
        else onToggle()
      }}
      title={visible ? t('activity.open') : t('activity.show')}
    >
      {t('activity.label')}
      {!visible ? (
        <span className="activity-off">{t('activity.off')}</span>
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
  const { t } = useLocale()
  const [jobs, setJobs] = useState<Array<Job & { steps: AgentStep[] }>>([])
  const [steering, setSteering] = useState<Record<string, string>>({})

  async function refresh() {
    try {
      const listed = await api.jobs()
      const recent = (listed.jobs || []).slice(-12).reverse()
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
      <h3>{t('activity.agentWork')}</h3>
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
                    {t('activity.attempt', {
                      executor: step.executor,
                      attempt: step.attempt || 0,
                      total: (step.retry_budget || 0) + 1,
                    })}
                    {step.dependencies?.length
                      ? t('activity.deps', { count: step.dependencies.length })
                      : ''}
                    {step.evidence?.length
                      ? t('activity.evidence', { count: step.evidence.length })
                      : ''}
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
                    {paused ? t('activity.resume') : t('activity.pause')}
                  </button>
                  <button
                    type="button"
                    onClick={() => api.cancelJob(job.id).then(refresh).catch(() => {})}
                  >
                    {t('activity.cancel')}
                  </button>
                  <label>
                    <span>{t('activity.steer')}</span>
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

function ActivityTimeline({ items, label }: { items: ActivitySpan[]; label?: string }) {
  const { t } = useLocale()
  const listRef = useRef<HTMLOListElement>(null)
  /** Stick to the newest edge (top) unless the user scrolls down into history. */
  const stickRef = useRef(true)
  const topIdRef = useRef<string | null>(null)

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const onScroll = () => {
      stickRef.current = el.scrollTop <= 24
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const el = listRef.current
    if (!el || items.length === 0) return
    const topId = items[0]?.id ?? null
    const arrived = topId !== topIdRef.current
    topIdRef.current = topId
    if (arrived && stickRef.current) {
      el.scrollTop = 0
    }
  }, [items])

  return (
    <ol
      ref={listRef}
      className="activity-timeline"
      aria-label={label || t('activity.timeline')}
    >
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
                {span.step_id ? t('activity.step', { id: span.step_id.slice(0, 8) }) : ''}
              </span>
            )}
            {Object.keys(span.details || {}).length > 0 && (
              <details className="activity-details">
                <summary>{t('activity.details')}</summary>
                <pre>{safeJson(span.details)}</pre>
              </details>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

export default function ActivityInspector({
  turnId,
  jobId,
  global = false,
  className = '',
  defaultOpen = false,
  variant = 'fold',
  onClose,
}: {
  turnId?: string
  jobId?: string
  global?: boolean
  className?: string
  defaultOpen?: boolean
  /** `sidebar` = always-open panel chrome for the chat rail. */
  variant?: 'fold' | 'sidebar'
  onClose?: () => void
}) {
  const { t } = useLocale()
  const { all, visible } = useActivity()
  const [open, setOpen] = useState(defaultOpen || variant === 'sidebar')
  const [agent, setAgent] = useState<ActivityAgent>('main')
  const sidebar = variant === 'sidebar'

  useEffect(() => {
    if (turnId) void activityStore.ensureTurn(turnId)
  }, [turnId])
  useEffect(() => {
    if (jobId) void activityStore.ensureJob(jobId)
  }, [jobId])

  const items = useMemo(() => {
    const filtered = activityFor(all, {
      turnId,
      jobId,
      global,
      // Per-turn activity belongs beside the main reply. Deep Work has its
      // own selectable panel; a job-specific inspector remains job-only.
      agent: global ? agent : jobId ? 'deep-work' : 'main',
    })
    // Newest first — keep the latest window, then reverse for the rail.
    return filtered.slice(-160).reverse()
  }, [agent, all, global, jobId, turnId])

  const globalCounts = useMemo(() => {
    if (!global) return { main: 0, deepWork: 0 }
    return {
      main: activityFor(all, { global: true, agent: 'main' }).length,
      deepWork: activityFor(all, { global: true, agent: 'deep-work' }).length,
    }
  }, [all, global])

  if (!visible) return null
  if (!sidebar && items.length === 0) return null

  const active = items.filter((item) => ACTIVE.has(item.status))
  const tools = items.filter((item) => item.kind === 'tool').length
  const jobs = new Set(items.map((item) => item.job_id).filter(Boolean)).size
  const failed = items.some((item) => item.status === 'failed')
  const done = active.length === 0 && items.some((item) => item.ended)
  const label =
    items.length === 0
      ? t('activity.label')
      : active[0]?.label ||
        (failed
          ? t('activity.failed')
          : done
            ? t('activity.complete')
            : t('activity.label'))
  const counts = [
    tools
      ? tools === 1
        ? t('activity.tools', { count: tools })
        : t('activity.toolsPlural', { count: tools })
      : '',
    jobs
      ? jobs === 1
        ? t('activity.agents', { count: jobs })
        : t('activity.agentsPlural', { count: jobs })
      : '',
  ]
    .filter(Boolean)
    .join(' · ')

  const toolbar = (
    <div className="activity-toolbar">
      <span>{t('activity.events', { count: items.length })}</span>
      <button
        type="button"
        onClick={() => {
          activityStore.setVisible(false)
          onClose?.()
        }}
        title={t('activity.hideTitle')}
      >
        {t('activity.hide')}
      </button>
      {onClose && (
        <button type="button" onClick={onClose}>
          {t('activity.close')}
        </button>
      )}
    </div>
  )

  const agentSelector = global ? (
    <div className="activity-agent-tabs" role="tablist" aria-label={t('activity.source')}>
      <button
        type="button"
        role="tab"
        aria-selected={agent === 'main'}
        className={agent === 'main' ? 'is-active' : ''}
        onClick={() => setAgent('main')}
      >
        {t('activity.mainAgent')}
        {globalCounts.main > 0 && <span>{globalCounts.main}</span>}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={agent === 'deep-work'}
        className={agent === 'deep-work' ? 'is-active' : ''}
        onClick={() => setAgent('deep-work')}
      >
        {t('activity.deepWork')}
        {globalCounts.deepWork > 0 && <span>{globalCounts.deepWork}</span>}
      </button>
    </div>
  ) : null

  const activityPanel = (
    <div
      className={`activity-agent-panel activity-agent-panel-${agent}`}
      role={global ? 'tabpanel' : undefined}
      aria-label={
        global
          ? agent === 'main'
            ? t('activity.mainPanel')
            : t('activity.deepWorkPanel')
          : undefined
      }
    >
      {global && agent === 'deep-work' && <AgentWorkTree />}
      {items.length > 0 ? (
        <ActivityTimeline
          items={items}
          label={
            agent === 'deep-work'
              ? t('activity.deepWorkTimeline')
              : t('activity.mainTimeline')
          }
        />
      ) : (
        <p className="activity-empty">
          {global && agent === 'deep-work'
            ? t('activity.emptyDeepWork')
            : t('activity.emptyMain')}
        </p>
      )}
    </div>
  )

  if (sidebar) {
    return (
      <section className={`activity-inspector activity-sidebar ${className}`}>
        <header className="activity-sidebar-head">
          <div className="activity-sidebar-title">
            <span className={`activity-state ${failed ? 'failed' : active.length ? 'active' : 'done'}`} />
            <div>
              <strong>{label}</strong>
              {counts ? <em>{counts}</em> : null}
            </div>
          </div>
          {agentSelector}
          {toolbar}
        </header>
        <div className="activity-body">
          {activityPanel}
        </div>
      </section>
    )
  }

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
        <span className="activity-counts">{counts}</span>
        <span className="activity-chevron" aria-hidden>⌄</span>
      </button>
      {open && (
        <div className="activity-body">
          {agentSelector}
          {toolbar}
          {activityPanel}
        </div>
      )}
    </section>
  )
}
