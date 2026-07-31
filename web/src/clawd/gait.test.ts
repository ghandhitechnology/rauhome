/**
 * The no-sliding contract.
 *
 * A gait clip is played off ground covered rather than elapsed time, which is
 * only worth anything if one cycle of the clip covers exactly as much ground as
 * the legs physically reach in it. These tests pin that down at several speeds,
 * because the speeds are where it used to come apart: the director eases the
 * last stretch of every walk and boosts a hurry by 1.7x, and under the old
 * split clocks both of those made the feet skate.
 */

import { describe, expect, it } from 'vitest'
import { cycleDistance, gaitDuration, LEG_LENGTH, strideAngle, WALK_SPEED } from './gait'
import { MOTIONS, type MotionName } from './motions'
import { ClawdRig } from './rig'

const DEG = Math.PI / 180
const DT = 1 / 60

/** Every clip that carries him across the room. */
const GAITS: MotionName[] = ['walk', 'carry', 'push', 'tiptoe', 'pace']

/**
 * Run the rig forward, feeding it ground at `speed`, and report the distance
 * covered per full cycle of the leg phase alongside the leg amplitude in use.
 *
 * Distance and phase are both accumulated across many cycles and divided at the
 * end rather than measured between two wraps: a wrap is only ever detected on a
 * frame boundary, and at cruising speed a single frame is 3% of a cycle, which
 * is larger than the error being tested for.
 */
function measureCycle(gait: MotionName, speed: number) {
  const rig = new ClawdRig()
  rig.play(gait, { force: true, restart: true })
  const cruise = MOTIONS[gait].locomotion || WALK_SPEED
  const step = speed * DT
  const stride = speed / cruise

  // Past the fade-in, so the parameters have reached their authored values.
  for (let i = 0; i < 120; i++) {
    rig.advanceGait(step, stride)
    rig.update(DT)
  }

  let prev = rig.params.legPhase
  let cycles = 0
  let distance = 0

  for (let i = 0; i < 600; i++) {
    rig.advanceGait(step, stride)
    rig.update(DT)
    const phase = rig.params.legPhase
    cycles += phase - prev + (phase < prev ? 1 : 0)
    prev = phase
    distance += step
  }

  return { distance: distance / cycles, legSwing: rig.params.legSwing }
}

describe('stride geometry', () => {
  it('derives a cycle distance from the reach of the legs', () => {
    // A leg swung to 30 degrees puts its foot sin(30) * 2.5 = 1.25 units ahead
    // of the hip, so a planted step is 2.5 units and a two-step cycle is 5.
    expect(cycleDistance(30)).toBeCloseTo(5, 6)
    expect(cycleDistance(0)).toBe(0)
  })

  it('scales stride by the sine, not by the angle', () => {
    // Halving the angle would not halve the stride; halving the sine does.
    expect(Math.sin(strideAngle(30, 0.5) * DEG)).toBeCloseTo(Math.sin(30 * DEG) * 0.5, 6)
    expect(cycleDistance(strideAngle(24, 0.5))).toBeCloseTo(cycleDistance(24) * 0.5, 6)
  })

  it('gives every gait a duration its own legs can cover', () => {
    for (const name of GAITS) {
      const clip = MOTIONS[name]
      const swing = clip.tracks.find((t) => t.param === 'legSwing')?.keys[0].v ?? 0
      expect(clip.locomotion, name).toBeGreaterThan(0)
      expect(clip.duration, name).toBeCloseTo(gaitDuration(swing, clip.locomotion!), 6)
    }
  })
})

describe('gait clips', () => {
  it('all run off distance rather than the clock', () => {
    for (const name of GAITS) {
      expect(MOTIONS[name].phaseSource, name).toBe('distance')
    }
    // And nothing played in place does — a think or a wave must still run even
    // though he is standing still.
    expect(MOTIONS.idle.phaseSource).toBeUndefined()
    expect(MOTIONS.think.phaseSource).toBeUndefined()
  })
})

describe('feet stay on the ground', () => {
  it.each(GAITS)('%s covers exactly the ground its legs reach', (gait) => {
    const { distance, legSwing } = measureCycle(gait, MOTIONS[gait].locomotion || WALK_SPEED)
    expect(distance).toBeGreaterThan(0)
    expect(distance).toBeCloseTo(cycleDistance(legSwing), 1)
  })

  // 0.35 and 1.7 are not arbitrary: they are the arrival ease floor and the
  // hurry boost the director actually applies.
  it.each([0.35, 0.6, 1, 1.7])('holds at %sx of cruising speed', (factor) => {
    const cruise = MOTIONS.walk.locomotion!
    const { distance, legSwing } = measureCycle('walk', cruise * factor)
    expect(distance).toBeCloseTo(cycleDistance(legSwing), 1)
  })

  it('takes shorter, quicker steps as it slows rather than the same walk slowly', () => {
    const cruise = MOTIONS.walk.locomotion!
    const full = measureCycle('walk', cruise)
    const creep = measureCycle('walk', cruise * 0.35)

    // Shorter: less ground per cycle, and a visibly smaller leg swing.
    expect(creep.distance).toBeLessThan(full.distance * 0.6)
    expect(creep.legSwing).toBeLessThan(full.legSwing)

    // Quicker: cadence is cycles per second, and it falls away by much less
    // than the speed does. Playing the same clip at 0.35x would give 0.35.
    const cadence = (d: number, speed: number) => speed / d
    const ratio = cadence(creep.distance, cruise * 0.35) / cadence(full.distance, cruise)
    expect(ratio).toBeGreaterThan(0.6)
  })
})

describe('a gait with nothing behind it', () => {
  it('does not advance when he is not moving', () => {
    const rig = new ClawdRig()
    rig.play('walk', { force: true, restart: true })
    rig.advanceGait(2)
    rig.update(DT)
    const moved = rig.params.legPhase

    for (let i = 0; i < 30; i++) rig.update(DT)
    expect(rig.params.legPhase).toBe(moved)
  })

  it('runs on the clock for a panel that walks on the spot', () => {
    const rig = new ClawdRig()
    rig.treadmill = true
    rig.play('walk', { force: true, restart: true })
    for (let i = 0; i < 30; i++) rig.update(DT)
    expect(rig.params.legPhase).toBeGreaterThan(0)
  })
})

describe('leg geometry matches the sprite', () => {
  it('keeps LEG_LENGTH in step with what is drawn', async () => {
    // The stride maths is meaningless if the legs are not the length it thinks.
    const source = await import('node:fs').then((fs) =>
      fs.readFileSync(new URL('./sprite.ts', import.meta.url), 'utf8'),
    )
    const match = source.match(/const LEG = \{ y: [\d.]+, w: [\d.]+, h: ([\d.]+) \}/)
    expect(match?.[1]).toBe(String(LEG_LENGTH))
  })
})
