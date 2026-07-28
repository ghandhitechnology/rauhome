/**
 * What a table has to be, for the room to seat him at it.
 *
 * The arrival is the same every time and it took a while to get right: he
 * perks up, walks over, waits for the furniture to catch up with him, sits,
 * and the camera closes the rest of the way as he goes down. That sequence is
 * the whole difference between a game you opened and a game you are playing
 * with him, and it is worth exactly nothing if it has to be written twice.
 * So it is written once, in `gameChoreographer`, and a table that wants it
 * hands over the four things the ritual cannot guess for itself: where the
 * furniture stands, where the shot ends up, how far the rest of the room
 * falls away around it, and what to paint each frame.
 *
 * `spots` is the reason this is a type rather than four more arguments. Every
 * game in this room is half canvas and half DOM — the canvas draws the table
 * and the character, the DOM owns the cards and the pieces, because those
 * need real buttons, real focus order and hand-drawn SVG. The two halves have
 * to agree about where the deck is, or where the corner of the board is, to
 * the pixel; the moment they disagree the DOM stops being an object lying on
 * the table and becomes a sticker on the screen. Naming those places on the
 * surface itself is how they agree: the surface declares them in stage units,
 * `gameBridge` projects all of them into screen pixels once a frame, and the
 * DOM reads the answer. Two piles for kittens, four board corners for chess,
 * and neither the bridge nor the choreographer has to learn the difference.
 */

export type Pt = { x: number; y: number }
export type Rect = { x: number; y: number; w: number; h: number }

/** Where the camera settles once he is seated, and how fast it gets there. */
export type TableShot = { x: number; y: number; zoom: number; lambda: number }

export type TableSurface = {
  /** Which table this is — `'kittens'`, `'chess'`. */
  id: string
  /** The furniture itself, in stage units. */
  table: { x: number; topY: number; h: number; w: number }
  camera: TableShot
  /** 0..1 — how dark the room goes outside the light over the table. */
  dim: number
  /**
   * Named anchors in STAGE units; `gameBridge` publishes them as screen
   * `Rect`s every frame. A zero-sized rect is a point, and reads back through
   * `gameBridge.spot(name)` as exactly that point.
   */
  spots: Record<string, Rect>
  /**
   * Draw the surface each frame.
   *
   * `presence` runs 0..1 as he arrives and back down as he leaves — it is not
   * only an alpha, it is how the table gets to rise into the room instead of
   * fading on the spot in front of a character still walking towards it.
   */
  draw(ctx: CanvasRenderingContext2D, u: number, presence: number, time: number): void
}
