import {
  useEffect,
  useRef,
  useState,
  type AnimationEvent,
  type CSSProperties,
  type MouseEvent,
} from 'react'

import { modeSupportsHyper, useMode, type VoiceLatencyProfile } from '../mode'
import { useLocale } from '../i18n'

const HYPER_ACTIVATE_EVENT = 'rau:hyper-activate'

/* How fast the front travels, in CSS pixels per millisecond. Matched by eye to
   the crest's own easing in index.css: a 1440px-wide viewport clicked at one
   edge is ~1550px corner to corner, so the furthest control starts moving just
   under 400ms in, which is about when the ring gets there. Too slow and the
   controls visibly lag the wave they are supposed to be riding — keep this in
   step with the crest durations in index.css if either is retimed. */
const WAVE_SPEED = 4

/* Anything carrying this attribute is treated as an object floating in the
   medium: it gets shoved away from the click as the front reaches it. Opt-in by
   attribute so a page can join the effect without this file knowing about it. */
const WAKE_SELECTOR = '[data-hyper-wake]'

type HyperDirection = 'on' | 'off'

type HyperOrigin = {
  x: number
  y: number
  dir: HyperDirection
}

type HyperStyle = CSSProperties & {
  '--hyper-x': string
  '--hyper-y': string
  '--hyper-span': string
}

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

export function HyperToggle({
  profile,
  setProfile,
  disabled,
}: {
  profile: VoiceLatencyProfile
  setProfile: (profile: VoiceLatencyProfile) => void
  disabled: boolean
}) {
  const { t } = useLocale()
  const enabling = profile !== 'hyper'
  /* Driven by the click rather than by `profile`, so restoring a saved Hyper
     session on page load doesn't set the button off on its own. */
  const [charging, setCharging] = useState(false)

  function toggle(event: MouseEvent<HTMLButtonElement>) {
    setProfile(enabling ? 'hyper' : 'normal')
    setCharging(true)
    window.dispatchEvent(
      new CustomEvent<HyperOrigin>(HYPER_ACTIVATE_EVENT, {
        detail: { x: event.clientX, y: event.clientY, dir: enabling ? 'on' : 'off' },
      }),
    )
  }

  return (
    <button
      type="button"
      className={`hyper-toggle ${profile === 'hyper' ? 'on' : ''} ${charging ? 'charging' : ''}`}
      onAnimationEnd={() => setCharging(false)}
      aria-label={t('hyper.aria')}
      aria-pressed={profile === 'hyper'}
      disabled={disabled}
      title={disabled ? t('hyper.busy') : t('hyper.hint')}
      onClick={toggle}
    >
      {t('hyper.label')}
    </button>
  )
}

/**
 * The standing state, as opposed to the switch being thrown: while Hyper is on
 * the rim of the screen keeps a faint purple in it, drifting rather than sitting
 * still so the mode reads as live. Deliberately quiet — it has to survive being
 * looked at for a whole conversation.
 *
 * Mounted globally, so it follows Hyper onto whichever page is showing rather
 * than being something /face and /talk each have to remember to render.
 */
export function HyperAmbience() {
  const { mode, voiceLatency } = useMode()
  if (voiceLatency !== 'hyper' || !modeSupportsHyper(mode)) return null
  return (
    <div className="hyper-edge" aria-hidden="true">
      <i className="hyper-edge-drift" />
      <i className="hyper-edge-drift hyper-edge-drift-two" />
    </div>
  )
}

/* The distance from the origin to whichever viewport corner is furthest away —
   the radius the front has to reach before the screen is fully behind it. */
function reachFrom(x: number, y: number) {
  const w = window.innerWidth
  const h = window.innerHeight
  return Math.hypot(Math.max(x, w - x), Math.max(y, h - y))
}

export function HyperActivationRipple() {
  const sequence = useRef(0)
  const woken = useRef<HTMLElement[]>([])
  const [pulse, setPulse] = useState<(HyperOrigin & { id: number }) | null>(null)

  useEffect(() => {
    const activate = (event: Event) => {
      if (prefersReducedMotion()) return
      const detail = (event as CustomEvent<HyperOrigin>).detail
      sequence.current += 1
      setPulse({
        id: sequence.current,
        x: Number.isFinite(detail?.x) ? detail.x : window.innerWidth / 2,
        y: Number.isFinite(detail?.y) ? detail.y : window.innerHeight / 2,
        dir: detail?.dir === 'off' ? 'off' : 'on',
      })
    }
    window.addEventListener(HYPER_ACTIVATE_EVENT, activate)
    return () => window.removeEventListener(HYPER_ACTIVATE_EVENT, activate)
  }, [])

  /* The wake lives on elements this component does not own, so it is applied by
     hand and always taken back off — a stale class here would leave someone
     else's button stuck mid-shove. Every rect is read in one pass before a
     single style is written, to keep this to one layout. */
  useEffect(() => {
    const release = () => {
      for (const node of woken.current) {
        node.classList.remove('hyper-waking')
        node.style.removeProperty('--hyper-wake-delay')
        node.style.removeProperty('--hyper-wake-dx')
        node.style.removeProperty('--hyper-wake-dy')
      }
      woken.current = []
    }
    release()
    if (!pulse) return

    const targets = Array.from(document.querySelectorAll<HTMLElement>(WAKE_SELECTOR))
    const measured = targets.map((node) => {
      const box = node.getBoundingClientRect()
      const dx = box.left + box.width / 2 - pulse.x
      const dy = box.top + box.height / 2 - pulse.y
      return { node, dx, dy, dist: Math.hypot(dx, dy) }
    })
    const reach = reachFrom(pulse.x, pulse.y)

    for (const { node, dx, dy, dist } of measured) {
      /* Going out, near things move first. Coming back, the outermost lets go
         first and the disturbance drains inward toward the button. */
      const travelled = pulse.dir === 'off' ? Math.max(reach - dist, 0) : dist
      const length = dist || 1
      node.style.setProperty('--hyper-wake-delay', `${Math.round(travelled / WAVE_SPEED)}ms`)
      node.style.setProperty('--hyper-wake-dx', `${(dx / length).toFixed(3)}`)
      node.style.setProperty('--hyper-wake-dy', `${(dy / length).toFixed(3)}`)
      node.classList.add('hyper-waking')
      woken.current.push(node)
    }

    return release
  }, [pulse])

  if (!pulse) return null

  const style: HyperStyle = {
    '--hyper-x': `${pulse.x}px`,
    '--hyper-y': `${pulse.y}px`,
    '--hyper-span': `${Math.ceil(reachFrom(pulse.x, pulse.y) * 2)}px`,
  }
  const finish = (event: AnimationEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) setPulse(null)
  }

  return (
    <div
      key={pulse.id}
      className={`hyper-activation-ripple ${pulse.dir}`}
      style={style}
      aria-hidden="true"
      onAnimationEnd={finish}
    >
      {/* Two crests and the refraction ring they carry. Kept as flat siblings on
          purpose — see the note in index.css about backdrop roots. */}
      <i className="hyper-front hyper-front-one" />
      <i className="hyper-front hyper-front-two" />
      <i className="hyper-refract" />
    </div>
  )
}
