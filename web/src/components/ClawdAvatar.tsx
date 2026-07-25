import { useEffect, useRef } from 'react'
import { bodyController, compactCue, GAZE_AIMS, type BodyCue } from '../clawd/body'
import { ClawdRig } from '../clawd/rig'
import { drawClawd, GRID } from '../clawd/sprite'
import { useClawdCanvas } from '../clawd/useClawdCanvas'
import { live } from '../live'
import { ONE_SHOTS, type MotionName } from '../clawd/motions'
import './ClawdAvatar.css'

/** Rau emotions mapped onto Clawd's ambient clips. */
const EMOTION_MOTION: Record<string, MotionName> = {
  idle: 'idle',
  curious: 'idle',
  thinking: 'think',
  determined: 'type',
  happy: 'idle',
  excited: 'bounce',
  sad: 'gaze',
  love: 'idle',
  amazed: 'bounce',
  scared: 'startle',
  sleep: 'sleep',
}

const SMILEY = new Set(['happy', 'love', 'excited', 'amazed'])

type Props = {
  emotion?: string
  /** Show the typing loop regardless of emotion. */
  busy?: boolean
  /** Follow the pointer with the eyes. */
  trackPointer?: boolean
  className?: string
}

/**
 * The small inline Clawd — same rig as the room scene, no scenery.
 * Click him and he startles.
 */
export default function ClawdAvatar({
  emotion = 'idle',
  busy = false,
  trackPointer = true,
  className = '',
}: Props) {
  const rigRef = useRef<ClawdRig | null>(null)
  if (!rigRef.current) rigRef.current = new ClawdRig()
  const rig = rigRef.current

  const pointer = useRef<{ x: number; y: number } | null>(null)
  const centre = useRef({ x: 0, y: 0 })
  const desired = useRef<MotionName>('idle')
  const smile = useRef(0)
  /** The cue holding this avatar, and the timer for its walk-in-place. */
  const cue = useRef<BodyCue | null>(null)
  const walkTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const key = (emotion || 'idle').toLowerCase()
    desired.current = busy ? 'type' : EMOTION_MOTION[key] || 'idle'
    smile.current = SMILEY.has(key) ? 1 : 0
    // One-shots fire immediately; loops are picked up by the frame loop. A cue
    // owns the body while it holds it, so emotion waits its turn.
    if (cue.current) return
    if (desired.current === 'bounce' || desired.current === 'startle') {
      rig.play(desired.current, { force: true, restart: true })
    }
  }, [emotion, busy, rig])

  useEffect(() => {
    if (!trackPointer) return
    const onMove = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY }
    }
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [trackPointer])

  useEffect(() => {
    live.start()

    const clearWalk = () => {
      if (walkTimer.current !== null) {
        clearTimeout(walkTimer.current)
        walkTimer.current = null
      }
    }

    const gesture = (motion: MotionName | null) => {
      rig.play(motion ?? 'idle', { force: true, restart: motion !== null })
    }

    const unregister = bodyController.registerTarget({
      applyCue: (next) => {
        clearWalk()
        cue.current = next
        rig.setGaze(next.gaze ? GAZE_AIMS[next.gaze] : null)
        const step = compactCue(next)
        if (step.walkMs <= 0) {
          if (step.motion) gesture(step.motion)
          return
        }
        // Travel first, gesture on arrival — the same order the room uses.
        rig.play('walk', { force: true, restart: true })
        walkTimer.current = setTimeout(() => {
          walkTimer.current = null
          if (cue.current !== next) return
          gesture(step.motion)
        }, step.walkMs)
      },
      releaseCue: () => {
        clearWalk()
        cue.current = null
        rig.setGaze(null)
        // A finished one-shot holds its last pose; come back to the ambient
        // clip rather than leaving him frozen mid-gesture.
        rig.play(desired.current, { force: true })
      },
    })

    return () => {
      unregister()
      clearWalk()
      cue.current = null
    }
  }, [rig])

  const canvasRef = useClawdCanvas((ctx, dt, w, h) => {
    // Headroom above for hops and raised claws, and a margin below so the
    // feet and contact shadow never clip the panel edge.
    const unit = Math.min(w / (GRID.w + 7), h / (GRID.h + 6))
    const x = w / 2
    const y = h - unit * 2.6

    const rect = ctx.canvas.getBoundingClientRect()
    centre.current = { x: rect.left + x, y: rect.top + y - unit * 5 }

    const held = cue.current
    if (held) {
      // Hold the cue's pose for its whole life: a loop stays put, and a
      // one-shot that has run out settles rather than snapping to emotion.
      const want = held.motion && !ONE_SHOTS.includes(held.motion) ? held.motion : null
      if (want && !rig.busy && rig.currentMotion !== want) {
        rig.play(want, { force: true })
      }
    } else if (!rig.busy && rig.currentMotion !== desired.current) {
      rig.play(desired.current)
    }

    rig.update(dt, {
      // A cue that named somewhere to look owns the eyes; otherwise the
      // pointer does, because being looked at outranks the behaviour layer.
      lookAt: trackPointer && !held?.gaze ? pointer.current : null,
      screen: centre.current,
    })

    // Emotion-driven smile rides on top of whatever the clip is doing.
    if (smile.current > 0 && !rig.player.owned.has('eyeSmile')) {
      rig.params.eyeSmile = smile.current
    }

    drawClawd(ctx, rig.params, { unit, x, y })
  }, [rig, trackPointer])

  return (
    <div className={`clawd-avatar ${className}`}>
      <canvas
        ref={canvasRef}
        onPointerDown={() => {
          // A poke is human input, and outranks the model's plan.
          bodyController.humanTakeover()
          rig.play('startle', { force: true, restart: true })
        }}
        aria-hidden
      />
      <span className="sr-only">Clawd, currently {emotion}</span>
    </div>
  )
}
