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

// innerWidth/innerHeight flush layout, so this only runs on frames that draw the spotlight
function spotlightLayout(rect: DOMRect) {
  const diameter = Math.max(rect.width, rect.height) + 30
  const centerX = rect.left + rect.width / 2
  const centerY = rect.top + rect.height / 2
  const cardWidth = Math.min(360, window.innerWidth - 32)
  const preferBelow = centerY < window.innerHeight * 0.58
  const cardLeft = Math.max(16, Math.min(window.innerWidth - cardWidth - 16, centerX - cardWidth / 2))
  const cardTop = Math.max(
    16,
    Math.min(
      window.innerHeight - 330,
      preferBelow ? centerY + diameter / 2 + 24 : centerY - diameter / 2 - 300,
    ),
  )
  return { diameter, centerX, centerY, cardWidth, cardLeft, cardTop }
}

export function TutorialProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState(initialActive)
  const [index, setIndex] = useState(0)
  const [finale, setFinale] = useState(false)
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
    setFinale(false)
    setActive(true)
    nav('/face')
  }, [nav, writeState])

  const finish = useCallback(
    (value: 'completed' | 'skipped') => {
      writeState(value)
      setActive(false)
      setFinale(false)
      setRect(null)
      nav('/face')
    },
    [nav, writeState],
  )

  const advance = useCallback(() => {
    if (index >= TOUR_STEPS.length - 1) {
      setRect(null)
      setFinale(true)
      return
    }
    const next = TOUR_STEPS[index + 1]
    setIndex((value) => value + 1)
    if (loc.pathname !== next.route) nav(next.route)
  }, [index, loc.pathname, nav])

  useEffect(() => {
    document.documentElement.dataset.tutorial = active ? 'on' : 'off'
    return () => {
      delete document.documentElement.dataset.tutorial
    }
  }, [active])

  useEffect(() => {
    if (!active || finale || !step) return
    if (loc.pathname !== step.route) {
      nav(step.route)
      return
    }

    let target: HTMLElement | null = null
    let resizeObserver: ResizeObserver | null = null
    let mutationObserver: MutationObserver | null = null
    let timer = 0
    let frame = 0
    let last: DOMRect | null | undefined

    // the spotlight rides a 200vmax box-shadow, so committing a rect that did not move
    // repaints the whole viewport for nothing
    const applyRect = (next: DOMRect | null) => {
      if (
        next &&
        last &&
        next.left === last.left &&
        next.top === last.top &&
        next.width === last.width &&
        next.height === last.height
      ) {
        return
      }
      if (next === null && last === null) return
      last = next
      setRect(next)
    }

    const measure = () => {
      window.clearTimeout(timer)
      target = document.querySelector<HTMLElement>(step.selector)
      if (!target) {
        applyRect(null)
        timer = window.setTimeout(measure, 80)
        return
      }
      applyRect(target.getBoundingClientRect())
      resizeObserver?.disconnect()
      resizeObserver = new ResizeObserver(() => {
        if (target) applyRect(target.getBoundingClientRect())
      })
      resizeObserver.observe(target)
    }

    // one measure per frame at most: scroll fires per nested scroller and the body-wide
    // mutation observer fires per streamed token, and both only ever want the same answer
    const sync = () => {
      frame = 0
      if (!target || !document.contains(target)) {
        measure()
        return
      }
      applyRect(target.getBoundingClientRect())
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(sync)
    }

    // The card is sized and clamped against the viewport as well as the target,
    // so a resize has to commit even when the target itself did not move — an
    // in-flow panel keeps its rect exactly when only the height changes.
    const onResize = () => {
      last = undefined
      schedule()
    }

    measure()
    mutationObserver = new MutationObserver(schedule)
    mutationObserver.observe(document.body, { childList: true, subtree: true })
    window.addEventListener('resize', onResize, { passive: true })
    window.addEventListener('scroll', schedule, { capture: true, passive: true })

    const onClick = (event: MouseEvent) => {
      if (step.action !== 'target') return
      const clicked = (event.target as Element | null)?.closest(step.selector)
      if (clicked) window.setTimeout(advance, 0)
    }
    document.addEventListener('click', onClick, true)

    return () => {
      window.clearTimeout(timer)
      cancelAnimationFrame(frame)
      resizeObserver?.disconnect()
      mutationObserver?.disconnect()
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', schedule, true)
      document.removeEventListener('click', onClick, true)
    }
  }, [active, advance, finale, loc.pathname, nav, step])

  const value = useMemo(() => ({ active, start }), [active, start])

  const layout = active && !finale && step && rect ? spotlightLayout(rect) : null

  return (
    <TutorialContext.Provider value={value}>
      {children}
      {active && finale && (
        <div className="tour-layer tour-finale" aria-live="polite">
          <aside className="tour-card tour-congrats" aria-label={t('tour.congrats.title')}>
            <figure className="tour-congrats-art">
              {/* intrinsic size only: the CSS still sizes it, but the box is reserved
                  before the bytes land so the card does not re-centre mid-entrance */}
              <img
                src="/onboarding/congrats-colored-pencil.webp"
                alt=""
                width={861}
                height={670}
                decoding="async"
              />
            </figure>
            <h2>{t('tour.congrats.title')}</h2>
            <p>{t('tour.congrats.body')}</p>
            <div className="tour-card-actions tour-congrats-actions">
              <button type="button" className="btn primary" onClick={() => finish('completed')}>
                {t('tour.congrats.begin')}
              </button>
            </div>
          </aside>
        </div>
      )}
      {layout && step && (
        <div className="tour-layer" aria-live="polite">
          {/*
            The scrim is a sibling of the ring rather than the ring's own
            box-shadow. Sharing one element made the ring's paint bounds the
            whole viewport, so its brightness pulse repainted the entire screen
            every frame for the length of onboarding. Same geometry, so the
            spotlight hole lands identically; see tutorial.css.
          */}
          <div
            className="tour-scrim"
            aria-hidden
            style={{
              width: layout.diameter,
              height: layout.diameter,
              left: layout.centerX - layout.diameter / 2,
              top: layout.centerY - layout.diameter / 2,
            }}
          />
          <div
            className="tour-orbit"
            aria-hidden
            style={{
              width: layout.diameter,
              height: layout.diameter,
              left: layout.centerX - layout.diameter / 2,
              top: layout.centerY - layout.diameter / 2,
            }}
          />
          <aside
            className="tour-card"
            style={{ left: layout.cardLeft, top: layout.cardTop, width: layout.cardWidth }}
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
                  {t('tour.next')}
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
