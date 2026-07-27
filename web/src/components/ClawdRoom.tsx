import { useEffect, useMemo, useRef, useState } from 'react'
import { bodyController } from '../clawd/body'
import { Director, EMPTY_SIGNALS, type Signals } from '../clawd/director'
import { GameChoreographer } from '../clawd/gameChoreographer'
import { gameBridge, type GameResult } from '../clawd/gameBridge'
import { ClawdRig } from '../clawd/rig'
import { drawBubble, Scene } from '../clawd/scene'
import { STAGE, WALK_RANGE, type RoomState, type StationId } from '../clawd/room'

/** Walk leash for the desktop pet — matches the pet scene's visible band. */
const PET_WALK_RANGE = { min: 58, max: 102 }
import type { RoomVisual } from '../clawd/roomVisual'
import { useClawdCanvas } from '../clawd/useClawdCanvas'
import { live } from '../live'
import { panelStore } from '../panels'
import { wallPanelRects } from '../clawd/panelsLayer'
import type { MotionName } from '../clawd/motions'
import './ClawdRoom.css'

export type HitRect = { x: number; y: number; w: number; h: number }

function within(rect: HitRect, x: number, y: number): boolean {
  return x >= rect.x && x <= rect.x + rect.w && y >= rect.y && y <= rect.y + rect.h
}

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
  /** classic = original flat room; enhanced = materials pass. */
  roomVisual?: RoomVisual
  /** Draw the room backdrop, or only the character (desktop pet). */
  showRoom?: boolean
  /** Character scale multiplier passed to the scene. */
  charScale?: number
  /** Called each frame with body∪bubble bounds in CSS pixels. */
  onHitRect?: (rect: HitRect) => void
  /** Exposes the director so a parent can drive it (motion tester). */
  onReady?: (api: ClawdRoomApi) => void
}

export type ClawdRoomApi = {
  play: (name: MotionName) => void
  goTo: (station: StationId) => void
  setManual: (manual: boolean) => void
  startle: () => void
  /** The card-table ritual, exposed so it can be exercised without a game. */
  game: {
    begin: () => Promise<void>
    end: (opts?: { fast?: boolean; result?: GameResult }) => Promise<void>
  }
}

function unionRect(a: HitRect, b: HitRect): HitRect {
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  const r = Math.max(a.x + a.w, b.x + b.w)
  const bot = Math.max(a.y + a.h, b.y + b.h)
  return { x, y, w: r - x, h: bot - y }
}

export default function ClawdRoom({
  signals,
  cinematic = true,
  hourOverride = null,
  lampOn,
  conversing = false,
  roomVisual = 'enhanced',
  showRoom = true,
  charScale = 1,
  onHitRect,
  onReady,
}: Props) {
  const rig = useMemo(() => new ClawdRig(), [])
  const director = useMemo(() => new Director(rig, 'room'), [rig])
  const scene = useMemo(() => new Scene(), [])
  const choreographer = useMemo(
    () => new GameChoreographer(rig, director),
    [rig, director],
  )

  // The table only exists in the full room; the desktop pet has no floor to
  // put one on. Registering here rather than in the game keeps the contract
  // one-directional: the game asks the room for choreography, never the
  // other way round.
  useEffect(() => {
    if (!showRoom) return
    gameBridge.registerChoreo(choreographer)
    return () => {
      gameBridge.registerChoreo(null)
    }
  }, [choreographer, showRoom])

  useEffect(() => {
    scene.roomVisual = roomVisual
  }, [scene, roomVisual])

  const signalsRef = useRef(signals)
  signalsRef.current = signals
  const pointer = useRef<{ x: number; y: number } | null>(null)
  const parallax = useRef({ x: 0, y: 0 })
  const hitRect = useRef<HitRect>({ x: 0, y: 0, w: 0, h: 0 })
  /** Where each framed panel currently sits on screen, newest first. */
  const panelHits = useRef<{ id: string; rect: HitRect }[]>([])
  const onHitRectRef = useRef(onHitRect)
  onHitRectRef.current = onHitRect
  const [hovering, setHovering] = useState(false)
  const [overPanel, setOverPanel] = useState(false)

  // Screen glow follows whether Rau is actually working.
  const roomState = useRef<RoomState>({ hour: 12, lamp: 0, screen: 0.2, time: 0 })

  useEffect(() => {
    if (!showRoom) {
      // Pet window: roam inside a short leash instead of room stations that
      // sit off the cropped frame (window / shelf).
      director.setWalkRange(PET_WALK_RANGE)
      director.setMode(conversing ? 'conversing' : 'roam')
      return
    }
    director.setWalkRange(WALK_RANGE)
    director.setMode(conversing ? 'conversing' : 'room')
  }, [director, conversing, showRoom])

  // The full room can do everything a plan asks for, locomotion included.
  // Pet mode still receives cues, but stations are clamped to the leash.
  useEffect(() => {
    live.start()
    return bodyController.registerTarget({
      applyCue: (cue) => {
        // A station cue or desk-work sustain would walk him out of a hand:
        // the director's cue branch runs ahead of the `manual` flag the
        // choreographer sets, so the game turns cues away at the door.
        if (choreographer.busy) {
          // A turned-away station cue still owes the controller its arrival:
          // the hold waits on cueArrived(), and with no walk ever coming it
          // would sit pending until the plan expired — taking every later
          // cue with it. pump() arms that hold only after this returns, so
          // the answer has to land a tick later, not synchronously.
          if (cue.station) queueMicrotask(() => bodyController.cueArrived())
          return
        }
        director.applyCue(cue)
      },
      releaseCue: () => director.releaseCue(),
      reportsArrival: true,
    })
  }, [director, choreographer])

  useEffect(() => {
    // A human reaching for the body mid-game gets it, but the table has to be
    // put away first — otherwise he walks off to the shelf still seated, with
    // a card table left standing in an empty room.
    const clearTable = () => {
      if (choreographer.busy) void choreographer.dismiss({ fast: true })
    }
    onReady?.({
      // Anything a human asks for outranks the model's plan, and cancels the
      // rest of it — playing out the remaining cues over the top of what they
      // just asked for is not deference.
      play: (name) => {
        clearTable()
        bodyController.humanTakeover()
        director.force(name)
      },
      goTo: (id) => {
        clearTable()
        bodyController.humanTakeover()
        // Human station picks always win over voice conversing / ambient.
        director.manual = false
        director.goTo(id)
      },
      setManual: (m) => {
        if (m) bodyController.humanTakeover()
        director.manual = m
      },
      startle: () => {
        bodyController.humanTakeover()
        director.startle()
      },
      game: {
        begin: () => choreographer.summon(),
        end: (opts) => choreographer.dismiss(opts),
      },
    })
  }, [choreographer, director, onReady])

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      pointer.current = { x: e.clientX, y: e.clientY }
      parallax.current = {
        x: (e.clientX / window.innerWidth - 0.5) * 2,
        y: (e.clientY / window.innerHeight - 0.5) * 2,
      }
      setHovering(within(hitRect.current, e.clientX, e.clientY))
      setOverPanel(
        panelHits.current.some((hit) => within(hit.rect, e.clientX, e.clientY)),
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

      // Before the director, so a ritual in progress owns the walk this tick
      // rather than a tick behind it.
      if (showRoom) choreographer.update(dt, scene)

      director.update(dt, s)
      rig.update(dt, {
        // He looks at the pointer only when it is nearby, otherwise he
        // attends to whatever he is doing — or, at the table, to the card you
        // are currently thinking about playing.
        lookAt: hovering ? pointer.current : gameBridge.lookAt,
        screen: { x: hitRect.current.x + hitRect.current.w / 2, y: hitRect.current.y },
        // Real TTS amplitude, so the body moves with the voice rather than on
        // a timer. Zero when he is not the one talking.
        talkLevel: s.rauSpeaking ? s.rauLevel : 0,
      })

      // Pet mode: clear to full transparency so the desktop shows through.
      if (!showRoom) {
        ctx.clearRect(0, 0, w, h)
      }

      const cameraTarget = showRoom ? choreographer.cameraTarget : null
      scene.layout(w, h, 1, { showRoom, charScale })
      scene.update(dt, rig.worldX, {
        follow: cinematic && showRoom,
        parallax: showRoom ? parallax.current : { x: 0, y: 0 },
        showRoom,
        charScale,
        cameraTarget,
      })
      scene.render(ctx, rig.params, rig.worldX, room, {
        follow: cinematic && showRoom,
        showRoom,
        charScale,
        gameTable: showRoom ? choreographer.presence : 0,
        gameDim: showRoom ? choreographer.dim : 0,
      })

      // Publish the camera and his claws to the DOM cards. After the render,
      // so what they are glued to is the frame that was just drawn.
      if (showRoom) gameBridge.frame(scene, rig, w, h)

      let combined = scene.screenRect(rig.params, rig.worldX, charScale)

      if (director.speech) {
        const r = combined
        const bubble = drawBubble(
          ctx,
          director.speech,
          r.x + r.w / 2,
          r.y,
          Math.min(showRoom ? 420 : 220, w * 0.85),
          Math.min(1.4, Math.max(0.75, w / (showRoom ? 900 : 320))),
        )
        if (bubble) combined = unionRect(combined, bubble)
      }

      hitRect.current = combined
      onHitRectRef.current?.(combined)

      // The framed panels are painted into the baked backdrop, so their screen
      // positions are projected fresh here rather than captured from the draw:
      // the camera drifts with parallax every frame while the bake does not.
      panelHits.current = showRoom
        ? wallPanelRects().map(({ panel, x, y, w, h }) => ({
            id: panel.panel_id,
            rect: scene.stageRect(x, y, w, h),
          }))
        : []
    },
    // Only the stable objects. Everything else the frame needs reaches the
    // loop through drawRef, which is refreshed every render — listing the
    // props here tore the RAF loop down and rebuilt it on every hover or
    // hour scrub, a one-frame blank each time.
    [rig, director, scene, choreographer],
  )

  return (
    <div
      className={`clawd-room ${hovering ? 'over-clawd' : ''} ${
        overPanel ? 'over-panel' : ''
      } ${showRoom ? '' : 'pet-mode'}`}
    >
      <canvas
        ref={canvasRef}
        onPointerDown={(e) => {
          if (e.button === 2) return
          // Panels are checked first: they hang on the back wall, so when one
          // sits behind him the frame is the thing being pointed at, not the
          // character standing in front of it.
          const framed = panelHits.current.find((hit) =>
            within(hit.rect, e.clientX, e.clientY),
          )
          if (framed) {
            panelStore.show(framed.id)
            return
          }
          if (!within(hitRect.current, e.clientX, e.clientY)) return
          // Poking him at the table startles him *in his seat*. The standing
          // startle would eject him out of it for a second and drop the hand
          // he is holding.
          if (choreographer.busy) {
            rig.play('kittenRecoil', { force: true, restart: true })
            return
          }
          bodyController.humanTakeover()
          director.startle()
          // Pet shell: drag the native window from the body hit area.
          if (!showRoom) {
            void import('../clawd/petBridge').then((m) => m.petStartDrag())
          }
        }}
      />
    </div>
  )
}

export { EMPTY_SIGNALS, STAGE }
export type { Signals }
