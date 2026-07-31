/**
 * Drawing pass for the movable objects.
 *
 * Split from `props.ts` (which owns where things are) and from `room.ts`
 * (which owns the fixtures) so that neither has to import the other. Resting
 * objects are drawn with the room, behind Rau; the one in his claws is drawn
 * after him, so it reads as held rather than as something he is standing next
 * to that happens to be moving.
 */

import { grip as gripFor, drawProp, propStore, propWidth, PROP_IDS, PROP_SPOTS, type PropId } from './props'
import { clawdAnchors } from './sprite'
import type { ParamSet } from './params'
import { contactShadow, FLOOR_Y } from './stage'

type Ctx = CanvasRenderingContext2D

/** Objects that animate, and so cannot be baked into the backdrop. */
const ANIMATED = new Set<PropId>(['plant'])

/**
 * The prop Rau currently has an errand for, and so is drawing himself.
 *
 * The whole errand, not just the part where it is off the ground: the object
 * crosses into and out of his claws rather than teleporting, so ownership of
 * drawing it has to cross with it.
 */
function carriedProp(): PropId | '' {
  const errand = propStore.activeErrand
  if (!errand) return ''
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
 * The object he has hold of, drawn after the character.
 *
 * `sprite` is everything needed to re-derive where his claws actually are:
 * the live parameter set, the scale he is drawn at, and where his feet land in
 * canvas pixels. `clawdAnchors` walks the same transform chain the renderer
 * does, so a held object inherits the bob, the lean, the squash and the claw
 * springs for free — and, because it is the same maths, cannot drift out of
 * his grip however he moves.
 */
export function drawCarriedProp(
  ctx: Ctx,
  u: number,
  time: number,
  sprite: { params: ParamSet; unit: number; x: number; y: number },
) {
  const errand = propStore.activeErrand
  if (!errand) return

  const anchors = clawdAnchors(sprite.params, sprite)
  // Anchors come back in canvas pixels; everything about a prop is stage units.
  const at = propStore.placement(errand.prop, {
    x: anchors.fan.x / u,
    y: anchors.fan.y / u,
    facing: sprite.params.facing < 0 ? -1 : 1,
  })

  const width = propWidth(errand.prop, gripFor(errand.prop).scale)
  // The shadow stays with the floor and fades as it leaves it, so the moment
  // he takes the weight is visible in the shadow as well as in the object.
  if (at.grip < 1) {
    const spot = PROP_SPOTS[propStore.spotOf(errand.prop)]
    const onFloor = spot.y >= FLOOR_Y
    contactShadow(
      ctx,
      u,
      spot.x + width / 2,
      spot.y + (onFloor ? 0.8 : 0.3),
      width * (onFloor ? 0.85 : 0.6) * (1 - at.grip * 0.4),
      onFloor ? 1.7 : 0.7,
      (onFloor ? 0.5 : 0.4) * (1 - at.grip),
    )
  }

  drawProp(ctx, u, errand.prop, at.x, at.y, time, gripFor(errand.prop).scale)
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
