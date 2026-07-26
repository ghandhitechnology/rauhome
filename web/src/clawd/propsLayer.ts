/**
 * Drawing pass for the movable objects.
 *
 * Split from `props.ts` (which owns where things are) and from `room.ts`
 * (which owns the fixtures) so that neither has to import the other. Resting
 * objects are drawn with the room, behind Rau; the one in his claws is drawn
 * after him, so it reads as held rather than as something he is standing next
 * to that happens to be moving.
 */

import { drawProp, propStore, propWidth, PROP_IDS, PROP_SPOTS } from './props'
import { contactShadow, FLOOR_Y } from './stage'

type Ctx = CanvasRenderingContext2D

/** Everything currently sitting on a surface. */
export function drawRestingProps(ctx: Ctx, u: number, time: number) {
  const errand = propStore.activeErrand
  for (const id of PROP_IDS) {
    // The carried one is drawn later, in front of him.
    if (errand && errand.prop === id && (errand.phase === 'carry' || errand.phase === 'place')) {
      continue
    }
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
