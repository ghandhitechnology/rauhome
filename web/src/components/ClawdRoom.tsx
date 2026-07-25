import { useEffect, useMemo, useRef, useState } from 'react'
import { bodyController } from '../clawd/body'
import { Director, EMPTY_SIGNALS, type Signals } from '../clawd/director'
import { ClawdRig } from '../clawd/rig'
import { drawBubble, Scene } from '../clawd/scene'
import { STAGE, type RoomState } from '../clawd/room'
import { useClawdCanvas } from '../clawd/useClawdCanvas'
import { live } from '../live'
import type { MotionName } from '../clawd/motions'
import './ClawdRoom.css'

type Props = {
  signals: Signals
  /** Follow the character with a tighter camera. */
  cinematic?: boolean
  /** Override the wall-clock hour, 0..24. Used by the time scrubber. */
  hourOverride?: number | null
  lampOn?: boolean
  /**
   * Hold station and face the camera instead of wandering. Set while a voice
   * session is live — walking off mid-answer breaks the conversation.
   */
  conversing?: boolean
  /** Exposes the director so a parent can drive it (motion tester). */
  onReady?: (api: ClawdRoomApi) => void
}

export type ClawdRoomApi = {
  play: (name: MotionName) => void
  goTo: (station: 'desk' | 'window' | 'shelf' | 'rug' | 'centre' | 'plant') => void
  setManual: (manual: boolean) => void
}

export default function ClawdRoom({
  signals,
  cinematic = true,
  hourOverride = null,
  lampOn,
  conversing = false,
  onReady,
}: Props) {
  const rig = useMemo(() => new ClawdRig(), [])
  const director = useMemo(() => new Director(rig, 'room'), [rig])
  const scene = useMemo(() => new Scene(), [])

  const signalsRef = useRef(signals)
  signalsRef.current = signals
  const pointer = useRef<{ x: number; y: number } | null>(null)
  const parallax = useRef({ x: 0, y: 0 })
  const hitRect = useRef({ x: 0, y: 0, w: 0, h: 0 })
  const [hovering, setHovering] = useState(false)

  // Screen glow follows whether Rau is actually working.
  const roomState = useRef<RoomState>({ hour: 12, lamp: 0, screen: 0.2, time: 0 })

  useEffect(() => {
    director.setMode(conversing ? 'conversing' : 'room')
  }, [director, conversing])

  // The full room can do everything a plan asks for, locomotion included.
  useEffect(() => {
    live.start()
    return bodyController.registerTarget({
      applyCue: (cue) => director.applyCue(cue),
      releaseCue: () => director.releaseCue(),
    })
  }, [director])

  useEffect(() => {
    onReady?.({
      // Anything a human asks for outranks the model's plan, and cancels the
      // rest of it — playing out the remaining cues over the top of what they
      // just asked for is not deference.
      play: (name) => {
        bodyController.humanTakeover()
        director.force(name)
      },
      goTo: (id) => {
        bodyController.humanTakeover()
        director.goTo(id)
      },
      setManual: (m) => {
        if (m) bodyController.humanTakeover()
        director.manual = m
      },
    })
  }, [director, onReady])

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY }
      parallax.current = {
        x: (e.clientX / window.innerWidth - 0.5) * 2,
        y: (e.clientY / window.innerHeight - 0.5) * 2,
      }
      const r = hitRect.current
      setHovering(
        e.clientX >= r.x && e.clientX <= r.x + r.w && e.clientY >= r.y && e.clientY <= r.y + r.h,
      )
    }
    window.addEventListener('pointermove', onMove)
    return () => window.removeEventListener('pointermove', onMove)
  }, [])

  const canvasRef = useClawdCanvas(
    (ctx, dt, w, h) => {
      const s = signalsRef.current
      const room = roomState.current
      room.time += dt

      const now = new Date()
      room.hour = hourOverride ?? now.getHours() + now.getMinutes() / 60
      const wantLamp = lampOn ?? (room.hour < 7 || room.hour > 18.5)
      room.lamp += ((wantLamp ? 1 : 0) - room.lamp) * Math.min(1, dt * 2)
      // The monitor pulses with his voice too, so the room breathes with him
      // rather than sitting inert behind a talking character.
      const wantScreen = s.thinking || s.hardState === 'running'
        ? 1
        : 0.22 + (s.rauSpeaking ? s.rauLevel * 0.5 : 0)
      room.screen += (wantScreen - room.screen) * Math.min(1, dt * 3)

      director.update(dt, s)
      rig.update(dt, {
        // He looks at the pointer only when it is nearby, otherwise he
        // attends to whatever he is doing.
        lookAt: hovering ? pointer.current : null,
        screen: { x: hitRect.current.x + hitRect.current.w / 2, y: hitRect.current.y },
        // Real TTS amplitude, so the body moves with the voice rather than on
        // a timer. Zero when he is not the one talking.
        talkLevel: s.rauSpeaking ? s.rauLevel : 0,
      })

      scene.layout(w, h, 1)
      scene.update(dt, rig.worldX, { follow: cinematic, parallax: parallax.current })
      scene.render(ctx, rig.params, rig.worldX, room, { follow: cinematic })

      hitRect.current = scene.screenRect(rig.params, rig.worldX)

      if (director.speech) {
        const r = hitRect.current
        drawBubble(
          ctx,
          director.speech,
          r.x + r.w / 2,
          r.y,
          Math.min(420, w * 0.62),
          Math.min(1.4, Math.max(0.85, w / 900)),
        )
      }
    },
    [rig, director, scene, cinematic, hourOverride, lampOn, hovering],
  )

  return (
    <div className={`clawd-room ${hovering ? 'over-clawd' : ''}`}>
      <canvas
        ref={canvasRef}
        onPointerDown={(e) => {
          const r = hitRect.current
          const inside =
            e.clientX >= r.x && e.clientX <= r.x + r.w && e.clientY >= r.y && e.clientY <= r.y + r.h
          if (!inside) return
          bodyController.humanTakeover()
          director.startle()
        }}
      />
    </div>
  )
}

export { EMPTY_SIGNALS, STAGE }
export type { Signals }
