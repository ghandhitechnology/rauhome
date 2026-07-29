/* oxlint-disable react/only-export-components -- provider and hook are one API */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useLocale, type TranslationKey } from './i18n'
import { useLocation, useNavigate } from './router'
import './tutorial.css'

export const POST_TUTORIAL_KEY = 'rau.tutorial.post.v1'

type TutorialValue = {
  active: boolean
  start: () => void
}

type TourStep = {
  route: string
  selector: string
  title: TranslationKey
  body: TranslationKey
  action: 'next' | 'target'
}

export const TOUR_STEPS: TourStep[] = [
  {
    route: '/face',
    selector: '[data-tour="room"]',
    title: 'tour.room.title',
    body: 'tour.room.body',
    action: 'next',
  },
  {
    route: '/face',
    selector: '[data-tour="room-composer"]',
    title: 'tour.composer.title',
    body: 'tour.composer.body',
    action: 'target',
  },
  {
    route: '/face',
    selector: '[data-tour="games"]',
    title: 'tour.games.title',
    body: 'tour.games.body',
    action: 'next',
  },
  {
    route: '/dashboard',
    selector: '[data-tour="deep-work"]',
    title: 'tour.work.title',
    body: 'tour.work.body',
    action: 'next',
  },
  {
    route: '/dashboard',
    selector: '[data-tour="deep-work-goal"]',
    title: 'tour.goal.title',
    body: 'tour.goal.body',
    action: 'target',
  },
  {
    route: '/',
    selector: '[data-tour="talk-composer"]',
    title: 'tour.talk.title',
    body: 'tour.talk.body',
    action: 'target',
  },
  {
    route: '/',
    selector: '[data-tour="activity"]',
    title: 'tour.activity.title',
    body: 'tour.activity.body',
    action: 'target',
  },
]

const TutorialContext = createContext<TutorialValue | null>(null)

function initialActive() {
  try {
    return localStorage.getItem(POST_TUTORIAL_KEY) === 'pending'
  } catch {
    return false
  }
}

export function TutorialProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(initialActive)
  const [index, setIndex] = useState(0)
  const nav = useNavigate()
  const loc = useLocation()
  const { t } = useLocale()
  const [rect, setRect] = useState<DOMRect | null>(null)
  const step = TOUR_STEPS[index]

  const writeState = useCallback((value: 'pending' | 'completed' | 'skipped') => {
    try {
      localStorage.setItem(POST_TUTORIAL_KEY, value)
    } catch {
      /* this session can still run the tour */
    }
  }, [])

  const start = useCallback(() => {
    writeState('pending')
    setIndex(0)
    setActive(true)
    nav('/face')
  }, [nav, writeState])

  const finish = useCallback(
    (value: 'completed' | 'skipped') => {
      writeState(value)
      setActive(false)
      setRect(null)
    },
    [writeState],
  )

  const advance = useCallback(() => {
    if (index >= TOUR_STEPS.length - 1) {
      finish('completed')
      return
    }
    const next = TOUR_STEPS[index + 1]
    setIndex((value) => value + 1)
    if (loc.pathname !== next.route) nav(next.route)
  }, [finish, index, loc.pathname, nav])

  useEffect(() => {
    document.documentElement.dataset.tutorial = active ? 'on' : 'off'
    return () => {
      delete document.documentElement.dataset.tutorial
    }
  }, [active])

  useEffect(() => {
    if (!active || !step) return
    if (loc.pathname !== step.route) {
      nav(step.route)
      return
    }

    let target: HTMLElement | null = null
    let resizeObserver: ResizeObserver | null = null
    let mutationObserver: MutationObserver | null = null
    let timer = 0

    const measure = () => {
      target = document.querySelector<HTMLElement>(step.selector)
      if (!target) {
        setRect(null)
        timer = window.setTimeout(measure, 80)
        return
      }
      setRect(target.getBoundingClientRect())
      resizeObserver?.disconnect()
      resizeObserver = new ResizeObserver(() => {
        if (target) setRect(target.getBoundingClientRect())
      })
      resizeObserver.observe(target)
    }

    measure()
    mutationObserver = new MutationObserver(() => {
      if (!target || !document.contains(target)) measure()
    })
    mutationObserver.observe(document.body, { childList: true, subtree: true })
    const onViewport = () => target && setRect(target.getBoundingClientRect())
    window.addEventListener('resize', onViewport)
    window.addEventListener('scroll', onViewport, true)

    const onClick = (event: MouseEvent) => {
      if (step.action !== 'target') return
      const clicked = (event.target as Element | null)?.closest(step.selector)
      if (clicked) window.setTimeout(advance, 0)
    }
    document.addEventListener('click', onClick, true)

    return () => {
      window.clearTimeout(timer)
      resizeObserver?.disconnect()
      mutationObserver?.disconnect()
      window.removeEventListener('resize', onViewport)
      window.removeEventListener('scroll', onViewport, true)
      document.removeEventListener('click', onClick, true)
    }
  }, [active, advance, loc.pathname, nav, step])

  const value = useMemo(() => ({ active, start }), [active, start])

  const diameter = rect ? Math.max(rect.width, rect.height) + 30 : 0
  const centerX = rect ? rect.left + rect.width / 2 : 0
  const centerY = rect ? rect.top + rect.height / 2 : 0
  const cardWidth = Math.min(360, window.innerWidth - 32)
  const preferBelow = centerY < window.innerHeight * 0.58
  const cardLeft = Math.max(16, Math.min(window.innerWidth - cardWidth - 16, centerX - cardWidth / 2))
  const cardTop = rect
    ? Math.max(
        16,
        Math.min(
          window.innerHeight - 330,
          preferBelow ? centerY + diameter / 2 + 24 : centerY - diameter / 2 - 300,
        ),
      )
    : 32

  return (
    <TutorialContext.Provider value={value}>
      {children}
      {active && step && rect && (
        <div className="tour-layer" aria-live="polite">
          <div
            className="tour-orbit"
            aria-hidden
            style={{
              width: diameter,
              height: diameter,
              left: centerX - diameter / 2,
              top: centerY - diameter / 2,
            }}
          />
          <aside
            className="tour-card"
            style={{ left: cardLeft, top: cardTop, width: cardWidth }}
            aria-label={t('tour.step', { current: index + 1, total: TOUR_STEPS.length })}
          >
            <div className="tour-card-head">
              <span>{t('tour.step', { current: index + 1, total: TOUR_STEPS.length })}</span>
              <button type="button" onClick={() => finish('skipped')}>
                {t('tour.skip')}
              </button>
            </div>
            <h2>{t(step.title)}</h2>
            <p>{t(step.body)}</p>
            <div className="tour-card-actions">
              <div className="tour-dots" aria-hidden>
                {TOUR_STEPS.map((_, dot) => (
                  <i key={dot} className={dot === index ? 'active' : dot < index ? 'done' : ''} />
                ))}
              </div>
              {step.action === 'next' && (
                <button type="button" className="btn primary" onClick={advance}>
                  {index === TOUR_STEPS.length - 1 ? t('tour.finish') : t('tour.next')}
                </button>
              )}
            </div>
          </aside>
        </div>
      )}
    </TutorialContext.Provider>
  )
}

export function useTutorial() {
  const value = useContext(TutorialContext)
  if (!value) throw new Error('useTutorial must be used inside TutorialProvider')
  return value
}
