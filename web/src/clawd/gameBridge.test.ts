/**
 * The camera, as one matrix.
 *
 * A whole layer of DOM cards rides `viewTransform`, so if it ever disagrees
 * with the projection the canvas actually draws with, every card drifts off
 * the table by exactly that disagreement. These tests are the guard on that:
 * the matrix and the existing per-rect projection have to be the same map.
 */
import { describe, expect, it } from 'vitest'

import { GAME_CAMERA } from './gameTableLayer'
import { Scene } from './scene'

/** Every camera the room can be in, including the one the table uses. */
const CAMERAS = [
  { x: 0, y: 0, zoom: 1 },
  { x: 0, y: 0, zoom: 1.14 },
  { x: -18, y: 1.4, zoom: 1.14 },
  { x: 12, y: -1.2, zoom: 0.92 },
  GAME_CAMERA,
]

const VIEWPORTS = [
  { w: 1440, h: 900 },
  { w: 900, h: 1200 },
  { w: 640, h: 480 },
]

function sceneAt(cam: { x: number; y: number; zoom: number }, w: number, h: number) {
  const scene = new Scene()
  scene.layout(w, h, 1, {})
  scene.camera.x = cam.x
  scene.camera.y = cam.y
  scene.camera.zoom = cam.zoom
  return scene
}

describe('viewTransform', () => {
  it('agrees with the projection everything else uses', () => {
    for (const view of VIEWPORTS) {
      for (const cam of CAMERAS) {
        const scene = sceneAt(cam, view.w, view.h)
        const { k, tx, ty } = scene.viewTransform()
        for (const [x, y] of [
          [0, 0],
          [80, 45],
          [57, 67],
          [160, 90],
          [-20, 110],
        ]) {
          const direct = scene.stagePoint(x, y)
          expect(x * k + tx).toBeCloseTo(direct.x, 6)
          expect(y * k + ty).toBeCloseTo(direct.y, 6)
        }
      }
    }
  })

  it('is a uniform scale, which is what lets one matrix carry the layer', () => {
    // No rotation and no aspect skew: a card scaled by `k` on both axes lands
    // exactly where a rect projected corner-by-corner would.
    const scene = sceneAt(GAME_CAMERA, 1440, 900)
    const { k } = scene.viewTransform()
    const rect = scene.stageRect(57, 67, 4.3, 6.02)
    expect(rect.w).toBeCloseTo(4.3 * k, 6)
    expect(rect.h).toBeCloseTo(6.02 * k, 6)
  })

  it('round-trips a point back to where it came from', () => {
    const scene = sceneAt(GAME_CAMERA, 1280, 720)
    const { k, tx, ty } = scene.viewTransform()
    const screen = scene.stagePoint(87, 67)
    expect((screen.x - tx) / k).toBeCloseTo(87, 6)
    expect((screen.y - ty) / k).toBeCloseTo(67, 6)
  })
})

describe('the table framing', () => {
  it('puts the table in the middle of the frame', () => {
    // The camera scales about the middle of the stage, so `x` being the
    // table's offset from centre is not a coincidence to be re-tuned — it is
    // the condition for the table being centred at all.
    const scene = sceneAt(GAME_CAMERA, 1440, 900)
    const table = scene.stagePoint(72, 70)
    expect(table.x).toBeCloseTo(1440 / 2, 6)
  })

  it('leaves the bottom of the frame free for the hand you are holding', () => {
    const scene = sceneAt(GAME_CAMERA, 1440, 900)
    // His head, the table surface, and how much room is left underneath.
    const head = scene.stagePoint(72, 62.4)
    const surface = scene.stagePoint(72, 70)
    expect(head.y / 900).toBeGreaterThan(0.2)
    expect(head.y / 900).toBeLessThan(0.45)
    expect(surface.y / 900).toBeLessThan(0.7)
  })
})
