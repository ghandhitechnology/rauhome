import {
  useEffect,
  useRef,
  useState,
  type AnimationEvent,
  type CSSProperties,
  type MouseEvent,
} from 'react'

import type { VoiceLatencyProfile } from '../mode'
import { useLocale } from '../i18n'

const HYPER_ACTIVATE_EVENT = 'rau:hyper-activate'

type HyperOrigin = {
  x: number
  y: number
}

type HyperStyle = CSSProperties & {
  '--hyper-x': string
  '--hyper-y': string
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

  function toggle(event: MouseEvent<HTMLButtonElement>) {
    setProfile(enabling ? 'hyper' : 'normal')
    if (!enabling) return
    window.dispatchEvent(
      new CustomEvent<HyperOrigin>(HYPER_ACTIVATE_EVENT, {
        detail: { x: event.clientX, y: event.clientY },
      }),
    )
  }

  return (
    <button
      type="button"
      className={`hyper-toggle ${profile === 'hyper' ? 'on' : ''}`}
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

export function HyperActivationRipple() {
  const sequence = useRef(0)
  const [pulse, setPulse] = useState<(HyperOrigin & { id: number }) | null>(null)

  useEffect(() => {
    const activate = (event: Event) => {
      const detail = (event as CustomEvent<HyperOrigin>).detail
      sequence.current += 1
      setPulse({
        id: sequence.current,
        x: Number.isFinite(detail?.x) ? detail.x : window.innerWidth / 2,
        y: Number.isFinite(detail?.y) ? detail.y : window.innerHeight / 2,
      })
    }
    window.addEventListener(HYPER_ACTIVATE_EVENT, activate)
    return () => window.removeEventListener(HYPER_ACTIVATE_EVENT, activate)
  }, [])

  if (!pulse) return null

  const style: HyperStyle = {
    '--hyper-x': `${pulse.x}px`,
    '--hyper-y': `${pulse.y}px`,
  }
  const finish = (event: AnimationEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) setPulse(null)
  }

  return (
    <div
      key={pulse.id}
      className="hyper-activation-ripple"
      style={style}
      aria-hidden="true"
      onAnimationEnd={finish}
    >
      <i className="hyper-wave hyper-wave-one" />
      <i className="hyper-wave hyper-wave-two" />
    </div>
  )
}
