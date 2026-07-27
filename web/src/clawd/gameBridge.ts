/**
 * The seam between the canvas room and the DOM cards.
 *
 * The cards are DOM — thirteen hand-drawn SVG faces, real buttons, real focus
 * order — but they have to behave like objects in the room: when the camera
 * pushes in, the deck has to push in with it, on the same frame. Positioning
 * them from React state would put them one frame behind the canvas, and one
 * frame of lag on a moving camera is exactly the difference between a card
 * lying on the table and a sticker stuck to the screen.
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
 */

import { GAME_CARD, GAME_TABLE } from './gameTableLayer'
import type { ClawdRig } from './rig'
import type { Scene } from './scene'
import { clawdAnchors } from './sprite'
import { FLOOR_Y } from './stage'

export type Pt = { x: number; y: number }
export type Rect = { x: number; y: number; w: number; h: number }

/**
 * One readable beat of his body during a hand.
 *
 * Named for what the body does, not for who won: `cheer` is him cheering,
 * which is the moment *you* lost.
 */
export type GameVerb =
  | 'draw'
  | 'play'
  | 'nope'
  | 'kitten'
  | 'defuse'
  | 'attack'
  | 'cheer'
  | 'slump'

/** Which way a finished game went, from the player's side of the table. */
export type GameResult = 'win' | 'loss' | null

/**
 * What the choreography side promises the game side.
 *
 * The split is the whole contract: the game owns when phases change and where
 * the cards are, the choreographer owns where *he* is and what his body is
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
}

type Snapshot = {
  /** The camera as `screen = stage * k + t`. */
  k: number
  tx: number
  ty: number
  /** Screen-space rects, for drag hit-testing and flight endpoints. */
  deck: Rect
  discard: Rect
  /** Where his fan of backs currently is, in screen pixels. */
  rauHand: Pt
  head: Pt
  w: number
  h: number
}

/** Below this, a transform change is not worth a DOM write. */
const EPSILON = 0.01

class GameBridge {
  private isActive = false

  /** True from the moment Play is pressed until the room is his again. */
  get active(): boolean {
    return this.isActive
  }

  /**
   * Setting this also publishes it to the document, because the render loop
   * is upstream of the game and must not import it: the canvas hook reads a
   * dataset flag to know it should be running at the display's rate rather
   * than the room's idle rate. One flag, written where the fact changes.
   */
  set active(on: boolean) {
    this.isActive = on
    if (typeof document === 'undefined') return
    if (on) document.documentElement.dataset.rauTable = 'true'
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
   * told where to be.
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

  /** Centre of a pile, in screen pixels — where a card flies from or to. */
  spot(which: 'deck' | 'discard'): Pt {
    const s = this.current
    if (!s) return { x: 0, y: 0 }
    const r = which === 'deck' ? s.deck : s.discard
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
    if (!this.active) {
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

    const cardRect = (cx: number): Rect => ({
      x: (cx - GAME_CARD.w / 2) * k + tx,
      y: GAME_TABLE.cardY * k + ty,
      w: GAME_CARD.w * k,
      h: GAME_CARD.h * k,
    })

    this.current = {
      k,
      tx,
      ty,
      deck: cardRect(GAME_TABLE.deckX),
      discard: cardRect(GAME_TABLE.discardX),
      rauHand: { x: fanX * k + tx, y: fanY * k + ty },
      head: { x: (a.head.x / u) * k + tx, y: (a.head.y / u) * k + ty },
      w,
      h,
    }

    // ── the labels on the piles ────────────────────────────────────────
    if (this.tagsEl && (this.tagsDirty || Math.abs(k - this.lastK) > EPSILON ||
        Math.abs(tx - this.lastTx) > EPSILON || Math.abs(ty - this.lastTy) > EPSILON)) {
      this.tagsDirty = false
      const style = this.tagsEl.style
      const deck = this.current.deck
      const discard = this.current.discard
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
