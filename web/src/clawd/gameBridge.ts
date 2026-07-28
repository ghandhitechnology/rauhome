/**
 * The seam between the canvas room and the DOM the game is made of.
 *
 * The playing pieces are DOM — thirteen hand-drawn card faces, or a board of
 * side-elevation chessmen, real buttons, real focus order — but they have to
 * behave like objects in the room: when the camera pushes in, the deck has to
 * push in with it, on the same frame. Positioning them from React state would
 * put them one frame behind the canvas, and one frame of lag on a moving
 * camera is exactly the difference between a card lying on the table and a
 * sticker stuck to the screen.
 *
 * So this runs inside the canvas render loop, at the canvas frame rate, and
 * writes transforms directly. Two DOM writes per frame, both skipped when
 * nothing moved:
 *
 *   1. one matrix on the world layer, carrying the whole camera
 *   2. one transform on his hand, which follows his claws rather than the room
 *
 * Everything else — the fan you are holding, the raised card, the countdown —
 * is screen-space and never touched from here.
 *
 * Nothing here knows which game is up. The active `TableSurface` names the
 * places that matter — `deck` and `discard`, or the four corners of a board —
 * and this projects whatever it finds. That is what lets a second game reuse
 * the ritual instead of forking it.
 */

import type { ClawdRig } from './rig'
import type { Scene } from './scene'
import { clawdAnchors } from './sprite'
import { FLOOR_Y } from './stage'
import type { Pt, Rect, TableSurface } from './tableSurface'

export type { Pt, Rect, TableSurface }

/**
 * One readable beat of his body during a hand.
 *
 * Named for what the body does, not for who won: `cheer` is him cheering,
 * which is the moment *you* lost. The vocabulary is per game — kittens has a
 * `kitten`, chess has a `blunder` — so this is deliberately just a string,
 * and each table declares the clip its own verbs map to.
 */
export type GameVerb = string

/** Which way a finished game went, from the player's side of the table. */
export type GameResult = 'win' | 'loss' | null

/**
 * What the choreography side promises the game side.
 *
 * The split is the whole contract: the game owns when phases change and where
 * the pieces are, the choreographer owns where *he* is and what his body is
 * doing. Neither reaches into the other.
 */
export type TableChoreo = {
  /** Walk over, sit, push the camera in. Resolves once the shot is set. */
  summon(): Promise<void>
  /** Adopt the seated shot with no ritual — a reload mid-game. */
  seatInstantly(): void
  /** Play the dealing flourish. Returns ms offsets of each card flick. */
  startDeal(cards: number): number[]
  /** Stand, pull back, put the table away. Resolves once the room is his. */
  dismiss(opts?: { fast?: boolean; result?: GameResult }): Promise<void>
  /** Queue body beats derived from a table diff. */
  observe(verbs: GameVerb[]): void
  /**
   * Let go of a held pose, without standing him up.
   *
   * A terminal beat is meant to be still on his body when you read the result,
   * so nothing tidies it away — the next beat does. A game that starts over
   * from the same seat has no next beat: the position is simply replaced, and
   * `diffBeats` says nothing across a new game. Without this he sets the board
   * up again while still slumped over the last one. The card table gets the
   * same release for free out of its dealing flourish; a table that does not
   * deal has to ask.
   */
  settle(): void
}

type Snapshot = {
  /** The camera as `screen = stage * k + t`. */
  k: number
  tx: number
  ty: number
  /**
   * The surface's named anchors in screen pixels, for drag hit-testing,
   * flight endpoints and positioning the DOM board.
   */
  spots: Record<string, Rect>
  /** Where his fan of backs currently is, in screen pixels. */
  rauHand: Pt
  head: Pt
  w: number
  h: number
}

/** Below this, a transform change is not worth a DOM write. */
const EPSILON = 0.01

class GameBridge {
  private table: TableSurface | null = null

  /** True from the moment Play is pressed until the room is his again. */
  get active(): boolean {
    return this.table !== null
  }

  /** Which table is up, or null. The room draws whatever this says. */
  get surface(): TableSurface | null {
    return this.table
  }

  /**
   * Put a table up, or take it away.
   *
   * This also publishes the fact to the document, because the render loop is
   * upstream of the game and must not import it: the canvas hook reads a
   * dataset flag to know it should be running at the display's rate rather
   * than the room's idle rate. One flag, written where the fact changes.
   */
  activate(surface: TableSurface | null) {
    this.table = surface
    if (typeof document === 'undefined') return
    if (surface) document.documentElement.dataset.rauTable = 'true'
    else delete document.documentElement.dataset.rauTable
  }

  /** A card the player is considering, in screen pixels. He looks at it. */
  hoverPoint: Pt | null = null
  /** When the player last said something, so he can glance up mid-turn. */
  userChattedAt = 0

  /** Last published frame. Read synchronously; never a React dependency. */
  current: Snapshot | null = null

  private worldEl: HTMLElement | null = null
  private rauEl: HTMLElement | null = null
  private choreo: TableChoreo | null = null
  private lastK = 0
  private lastTx = 0
  private lastTy = 0
  private lastFan = { x: 0, y: 0, a: 0, s: 0 }
  /**
   * Force the next write regardless of how little has moved.
   *
   * A freshly attached element has no transform at all, and the camera is
   * usually already settled by the time the cards mount — so without this the
   * "nothing changed" check is correct and the layer never gets positioned.
   */
  private worldDirty = true
  private fanDirty = true
  private tagsEl: HTMLElement | null = null
  private tagsDirty = true

  /** The camera-locked layer. Its children are authored in stage units. */
  attachWorld(el: HTMLElement | null) {
    this.worldEl = el
    this.worldDirty = true
  }

  /**
   * Give the layer back, but only if it is still yours.
   *
   * There is one bridge and two tables, and a handoff overlaps them: the
   * arriving game mounts and attaches while the leaving one is still standing
   * up, so the leaving table's cleanup runs *after* the arriving table has
   * taken the layer. An unconditional `attachWorld(null)` there detaches
   * somebody else's element, and because both tables attach from a callback ref
   * that React has no reason to call again, nothing ever puts it back — the new
   * table's DOM children silently stop tracking the camera for the rest of the
   * game while the canvas underneath them keeps moving.
   *
   * Passing the element you attached makes that a no-op instead of a bug, and
   * means neither table has to know the other exists.
   */
  releaseWorld(el: HTMLElement | null) {
    if (el && this.worldEl !== el) return
    this.worldEl = null
    this.worldDirty = true
  }

  /** Who currently owns the camera-locked layer. Read-only; for tests. */
  get world(): HTMLElement | null {
    return this.worldEl
  }

  /** The fan of backs in his claws. Follows him, not the room. */
  attachRauHand(el: HTMLElement | null) {
    this.rauEl = el
    this.fanDirty = true
  }

  /**
   * Where the labels on the two piles go, in screen pixels.
   *
   * The counts cannot live in the world layer with the cards: text there is
   * laid out tiny, counter-scaled, and then magnified by the camera, and what
   * arrives on screen is a blur. So the labels stay in screen space and are
   * told where to be. A surface with no piles simply never gets written to.
   */
  attachTags(el: HTMLElement | null) {
    this.tagsEl = el
    this.tagsDirty = true
  }

  registerChoreo(c: TableChoreo | null) {
    this.choreo = c
  }

  get choreography(): TableChoreo | null {
    return this.choreo
  }

  /** Stage units → screen pixels, from the last published frame. */
  toScreen(p: Pt): Pt {
    const s = this.current
    if (!s) return { x: 0, y: 0 }
    return { x: p.x * s.k + s.tx, y: p.y * s.k + s.ty }
  }

  /** Screen pixels → stage units. */
  toStage(p: Pt): Pt {
    const s = this.current
    if (!s || s.k === 0) return { x: 0, y: 0 }
    return { x: (p.x - s.tx) / s.k, y: (p.y - s.ty) / s.k }
  }

  /**
   * Where his eyes should go, or null.
   *
   * The card you are hovering is most of a screen below his head, and aimed
   * at literally the eyes bottom out and stay there — every card in the fan
   * would look the same to him. Keeping the horizontal aim exact and easing
   * the vertical one keeps the deflection inside its useful range, so which
   * card you are considering is actually readable on his face.
   */
  get lookAt(): Pt | null {
    const p = this.hoverPoint
    if (!p) return null
    const head = this.current?.head
    if (!head) return p
    return { x: p.x, y: head.y + (p.y - head.y) * 0.55 }
  }

  /**
   * Centre of one of the surface's named spots, in screen pixels.
   *
   * Where a card flies from or to; where a corner of the board lands. An
   * unknown name is the origin rather than a throw — this is called from
   * inside a render loop, and a game asking for a spot the table it is
   * sitting at does not have is a wiring bug, not a reason to stop drawing.
   */
  spot(name: string): Pt {
    const r = this.current?.spots[name]
    if (!r) return { x: 0, y: 0 }
    return { x: r.x + r.w / 2, y: r.y + r.h / 2 }
  }

  /**
   * Publish one frame. Called from the room's draw loop, after the render.
   *
   * Everything here is arithmetic. No `getBoundingClientRect`, no layout
   * reads: a forced reflow inside the render loop would cost more than the
   * whole rest of the frame.
   */
  frame(scene: Scene, rig: ClawdRig, w: number, h: number) {
    const surface = this.table
    if (!surface) {
      this.current = null
      return
    }

    const { k, tx, ty } = scene.viewTransform()
    const u = scene.unit

    // His claws, in the canvas space the sprite is drawn in, then divided
    // back into stage units so his hand lives in the same coordinates as the
    // table it is sitting behind.
    const a = clawdAnchors(rig.params, {
      unit: u * 1.25,
      x: rig.worldX * u,
      y: FLOOR_Y * u,
    })
    const fanX = a.fan.x / u
    const fanY = a.fan.y / u

    // The surface authored these in stage units once; every frame they get
    // the same uniform scale the canvas just drew with, so the DOM and the
    // paint can never drift apart by more than a rounding error.
    const spots: Record<string, Rect> = {}
    for (const name in surface.spots) {
      const r = surface.spots[name]
      spots[name] = { x: r.x * k + tx, y: r.y * k + ty, w: r.w * k, h: r.h * k }
    }

    this.current = {
      k,
      tx,
      ty,
      spots,
      rauHand: { x: fanX * k + tx, y: fanY * k + ty },
      head: { x: (a.head.x / u) * k + tx, y: (a.head.y / u) * k + ty },
      w,
      h,
    }

    // ── the labels on the piles ────────────────────────────────────────
    const deck = spots.deck
    const discard = spots.discard
    if (this.tagsEl && deck && discard &&
        (this.tagsDirty || Math.abs(k - this.lastK) > EPSILON ||
        Math.abs(tx - this.lastTx) > EPSILON || Math.abs(ty - this.lastTy) > EPSILON)) {
      this.tagsDirty = false
      const style = this.tagsEl.style
      style.setProperty('--deck-x', `${deck.x + deck.w / 2}px`)
      style.setProperty('--deck-y', `${deck.y + deck.h}px`)
      style.setProperty('--disc-x', `${discard.x + discard.w / 2}px`)
      style.setProperty('--disc-y', `${discard.y + discard.h}px`)
    }

    // ── the camera, as one matrix ──────────────────────────────────────
    if (
      this.worldEl &&
      (this.worldDirty ||
        Math.abs(k - this.lastK) > EPSILON ||
        Math.abs(tx - this.lastTx) > EPSILON ||
        Math.abs(ty - this.lastTy) > EPSILON)
    ) {
      const style = this.worldEl.style
      this.worldDirty = false
      style.transform = `matrix(${k}, 0, 0, ${k}, ${tx}, ${ty})`
      // Text inside the world layer is laid out at a normal size and scaled
      // *down* by this before the matrix scales it back up. Authoring it at
      // the layer's own scale would mean declaring a font-size under a pixel,
      // which a browser with a minimum font size set would quietly refuse and
      // then magnify twentyfold.
      style.setProperty('--inv', String(1 / k))
      this.lastK = k
      this.lastTx = tx
      this.lastTy = ty
    }

    // ── his hand, following his claws ──────────────────────────────────
    if (this.rauEl) {
      // Squash is passed through at half strength: enough that a flinch
      // travels into the cards, not so much that the seated pose shrinks
      // them noticeably.
      const scale = 0.5 + a.squash * 0.5
      const last = this.lastFan
      if (
        this.fanDirty ||
        Math.abs(fanX - last.x) > EPSILON ||
        Math.abs(fanY - last.y) > EPSILON ||
        Math.abs(a.angle - last.a) > EPSILON ||
        Math.abs(scale - last.s) > EPSILON
      ) {
        this.fanDirty = false
        this.rauEl.style.transform =
          `translate(${fanX}px, ${fanY}px) rotate(${a.angle}deg) scale(${scale})`
        last.x = fanX
        last.y = fanY
        last.a = a.angle
        last.s = scale
      }
    }
  }
}

export const gameBridge = new GameBridge()
