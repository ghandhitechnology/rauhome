import { useEffect, useRef } from 'react'
import { ClawdRig } from '../clawd/rig'
import { drawClawd, GRID } from '../clawd/sprite'
import { useClawdCanvas } from '../clawd/useClawdCanvas'
import type { MotionName } from '../clawd/motions'
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

  useEffect(() => {
    const key = (emotion || 'idle').toLowerCase()
    desired.current = busy ? 'type' : EMOTION_MOTION[key] || 'idle'
    smile.current = SMILEY.has(key) ? 1 : 0
    // One-shots fire immediately; loops are picked up by the frame loop.
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

  const canvasRef = useClawdCanvas((ctx, dt, w, h) => {
    // Headroom above for hops and raised claws, and a margin below so the
    // feet and contact shadow never clip the panel edge.
    const unit = Math.min(w / (GRID.w + 7), h / (GRID.h + 6))
    const x = w / 2
    const y = h - unit * 2.6

    const rect = ctx.canvas.getBoundingClientRect()
    centre.current = { x: rect.left + x, y: rect.top + y - unit * 5 }

    if (!rig.busy && rig.currentMotion !== desired.current) {
      rig.play(desired.current)
    }

    rig.update(dt, {
      lookAt: trackPointer ? pointer.current : null,
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
        onPointerDown={() => rig.play('startle', { force: true, restart: true })}
        aria-hidden
      />
      <span className="sr-only">Clawd, currently {emotion}</span>
    </div>
  )
}
