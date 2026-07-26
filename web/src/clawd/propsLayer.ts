/**
 * Drawing pass for the movable objects.
 *
 * Split from `props.ts` (which owns where things are) and from `room.ts`
 * (which owns the fixtures) so that neither has to import the other. Resting
 * objects are drawn with the room, behind Rau; the one in his claws is drawn
 * after him, so it reads as held rather than as something he is standing next
 * to that happens to be moving.
 */

import { drawProp, propStore, propWidth, PROP_IDS, PROP_SPOTS, type PropId } from './props'
import { contactShadow, FLOOR_Y } from './stage'

type Ctx = CanvasRenderingContext2D

/** Objects that animate, and so cannot be baked into the backdrop. */
const ANIMATED = new Set<PropId>(['plant'])

/** The prop currently in his claws, and so absent from the surfaces. */
function carriedProp(): PropId | '' {
  const errand = propStore.activeErrand
  if (!errand) return ''
  if (errand.phase !== 'carry' && errand.phase !== 'place') return ''
  return errand.prop as PropId
}

/**
 * Everything currently sitting on a surface.
 *
 * `still` selects only the objects that hold perfectly still, which is what
 * the baked backdrop can take; the rest are drawn live each frame.
 */
export function drawRestingProps(
  ctx: Ctx,
  u: number,
  time: number,
  opts: { still?: boolean; living?: boolean } = {},
) {
  const carried = carriedProp()
  for (const id of PROP_IDS) {
    if (opts.still && ANIMATED.has(id)) continue
    if (opts.living && !ANIMATED.has(id)) continue
    // The carried one is drawn later, in front of him.
    if (carried === id) continue
    const spot = PROP_SPOTS[propStore.spotOf(id)]
    const width = propWidth(id)
    // Only things on the floor get a cast shadow; a mug on a shelf sits in the
    // shelf's own shadow and a second one under it reads as grime.
    if (spot.y >= FLOOR_Y) {
      contactShadow(ctx, u, spot.x + width / 2, spot.y + 0.8, width * 0.85, 1.7, 0.5)
    } else {
      contactShadow(ctx, u, spot.x + width / 2, spot.y + 0.3, width * 0.6, 0.7, 0.4)
    }
    drawProp(ctx, u, id, spot.x, spot.y, time)
  }
}

/** The objects that move on their own — just the plant, and only its fronds. */
export function drawLivingProps(ctx: Ctx, u: number, time: number) {
  drawRestingProps(ctx, u, time, { living: true })
}

/**
 * The object in his claws, drawn after the character.
 *
 * `carrier` is where he is standing, in stage units.
 */
export function drawCarriedProp(
  ctx: Ctx,
  u: number,
  time: number,
  carrier: { x: number; y: number },
) {
  const errand = propStore.activeErrand
  if (!errand) return
  if (errand.phase !== 'carry' && errand.phase !== 'place') return
  const at = propStore.placement(errand.prop, carrier)
  if (!at.carried) return
  drawProp(ctx, u, errand.prop, at.x, at.y, time, 0.92)
}

/**
 * Everything `drawRestingProps` depends on, as a cache key.
 *
 * The still props are baked into the backdrop, so every input to them has to
 * reach the bake key or the room silently stops responding to it. This lives
 * beside the painter deliberately: when the two were in different files the
 * carried-object case was missed, and the backdrop kept a mug on the desk
 * while a second one rode across the room in his claws.
 */
export function restingPropsKey(): string {
  const spots = PROP_IDS.map((id) => `${id}:${propStore.spotOf(id)}`).join(',')
  return `${spots}|carried:${carriedProp()}`
}
