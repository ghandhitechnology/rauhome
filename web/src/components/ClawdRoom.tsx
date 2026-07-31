import { useEffect, useMemo, useRef, useState } from 'react'
import { noteActivity } from '../clawd/activity'
import { bodyController } from '../clawd/body'
import { CHESS_GAME } from '../clawd/chessTableLayer'
import { Director, EMPTY_SIGNALS, type Signals } from '../clawd/director'
import { GameChoreographer } from '../clawd/gameChoreographer'
import { KITTENS_GAME } from '../clawd/gameTableLayer'
import { gameBridge, type GameResult, type TableChoreo } from '../clawd/gameBridge'
import { propStore } from '../clawd/props'
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
  /** Called after the room canvas has painted its first frame. */
  onFirstFrame?: () => void
}

/** Sitting him down at one table, exposed so it can be run without a game. */
export type TableRitual = {
  begin: () => Promise<void>
  end: (opts?: { fast?: boolean; result?: GameResult }) => Promise<void>
}

export type ClawdRoomApi = {
  play: (name: MotionName) => void
  goTo: (station: StationId) => void
  setManual: (manual: boolean) => void
  startle: () => void
  /** The card-table ritual. */
  game: TableRitual
  /** The same ritual, at the chess board. */
  chess: TableRitual
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
  onFirstFrame,
}: Props) {
  const rig = useMemo(() => new ClawdRig(), [])
  const director = useMemo(() => new Director(rig, 'room'), [rig])
  const scene = useMemo(() => new Scene(), [])

  /**
   * One ritual per table, sharing the one body.
   *
   * The walk, the seat and the push-in are the same machine, but the shot it
   * settles on and the clip each beat plays are not, and those are fixed when
   * the choreographer is built. So there is one per game rather than one that
   * is reconfigured mid-hand — a table being swapped underneath a character
   * who is halfway into a chair is not a state worth being able to represent.
   */
  const choreographers = useMemo(
    () => ({
      kittens: new GameChoreographer({ rig, director }, KITTENS_GAME),
      chess: new GameChoreographer({ rig, director }, CHESS_GAME),
    }),
    [rig, director],
  )

  // The table only exists in the full room; the desktop pet has no floor to
  // put one on. Registering here rather than in the game keeps the contract
  // one-directional: the game asks the room for choreography, never the
  // other way round.
  //
  // What gets registered is a router rather than one of the two, because the
  // question the game side actually asks is "the choreography for the table
  // that is up" — and the bridge already knows which that is, since nothing
  // can be up without having told it.
  useEffect(() => {
    if (!showRoom) return
    const busy = (): GameChoreographer | null => {
      if (choreographers.chess.busy) return choreographers.chess
      if (choreographers.kittens.busy) return choreographers.kittens
      return null
    }
    /*
      Which table the question is about.

      A raised surface is the game saying which table it means, and it is right
      about that even while the other one is still being cleared away — Rau can
      set the board out himself in the middle of a hand of cards, and for a
      second or so the room is putting one table away and fetching the other.
      Falling back to whoever is on their feet covers the opposite end of that
      second, where the surface has already been handed back but the character
      it belonged to is still standing up.
    */
    const forTable = (): GameChoreographer => {
      if (gameBridge.surface) {
        return gameBridge.surface.id === 'chess'
          ? choreographers.chess
          : choreographers.kittens
      }
      return busy() ?? choreographers.kittens
    }
    const router: TableChoreo = {
      summon: () => forTable().summon(),
      seatInstantly: () => forTable().seatInstantly(),
      startDeal: (cards) => forTable().startDeal(cards),
      // The one question that is not about the table that is up. By the time a
      // game asks to be put away the surface may already belong to the game
      // replacing it, and the standing-up is still owed by the one leaving.
      dismiss: (opts) => (busy() ?? forTable()).dismiss(opts),
      observe: (verbs) => forTable().observe(verbs),
      settle: () => forTable().settle(),
    }
    gameBridge.registerChoreo(router)
    return () => {
      gameBridge.registerChoreo(null)
    }
  }, [choreographers, showRoom])

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
        // Either table counts — he is just as seated at the board as at
        // the cards.
        if (choreographers.kittens.busy || choreographers.chess.busy) {
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
  }, [director, choreographers])

  useEffect(() => {
    // A human reaching for the body mid-game gets it, but the table has to be
    // put away first — otherwise he walks off to the shelf still seated, with
    // a card table left standing in an empty room.
    const clearTable = () => {
      for (const c of Object.values(choreographers)) {
        if (c.busy) void c.dismiss({ fast: true })
      }
    }
    // Exercised from the motion tester there is no game to raise the surface,
    // so the ritual raises it itself: without one the room would draw the
    // wrong table, or the right one at the wrong shot.
    const ritual = (c: GameChoreographer): TableRitual => ({
      begin: () => {
        gameBridge.activate(c.surface)
        return c.summon()
      },
      end: async (opts) => {
        await c.dismiss(opts)
        if (gameBridge.surface === c.surface) gameBridge.activate(null)
      },
    })
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
      game: ritual(choreographers.kittens),
      chess: ritual(choreographers.chess),
    })
  }, [choreographers, director, onReady])

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
      // A live conversation is activity even with nobody touching the desk:
      // voice levels and streams never fire a window listener, and the room
      // must not nap mid-answer.
      if (
        s.rauSpeaking ||
        s.userSpeaking ||
        s.streaming ||
        s.thinking ||
        s.working ||
        s.hardState === 'running' ||
        s.jobs.length > 0
      ) {
        noteActivity()
      }
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
      // rather than a tick behind it. Both are ticked whether or not either is
      // doing anything: an idle one is a pair of damped values settling to
      // zero, and skipping it is how a dismissed table stops halfway out.
      if (showRoom) {
        choreographers.kittens.update(dt, scene)
        choreographers.chess.update(dt, scene)
      }

      director.update(dt, s)
      // An object crossing into and out of his claws is a movement, not a
      // phase change, so it needs a clock of its own.
      propStore.tick(dt)
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

      // Only one table can be up at a time, so combining the two is a way of
      // saying "whichever of them has something to say this frame" without
      // having to decide which that is.
      const kit = choreographers.kittens
      const chs = choreographers.chess
      const cameraTarget = showRoom ? kit.cameraTarget ?? chs.cameraTarget : null
      /*
        Presence is the exception, because it is the one of these that belongs to
        a specific piece of furniture. `drawGameTable` paints whichever surface
        the bridge is holding, so during a handoff — where both choreographers
        are running, one rising and one still standing up — the maximum is the
        *outgoing* table's number applied to the *incoming* table's drawing, and
        the new table appears fully formed instead of rising into place. Asking
        the choreographer that owns the surface being painted keeps the number
        and the furniture describing the same thing. The max survives as the
        fallback for the frames after a surface is handed back, which is the case
        it was always right for.
      */
      const owner =
        gameBridge.surface?.id === 'chess'
          ? chs
          : gameBridge.surface?.id === 'kittens'
            ? kit
            : null
      const tablePresence = showRoom
        ? owner
          ? owner.presence
          : Math.max(kit.presence, chs.presence)
        : 0
      const tableDim = showRoom ? Math.max(kit.dim, chs.dim) : 0
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
        gameTable: tablePresence,
        gameDim: tableDim,
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
    [rig, director, scene, choreographers],
    { onFirstFrame },
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
          if (choreographers.kittens.busy || choreographers.chess.busy) {
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
