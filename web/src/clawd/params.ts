/**
 * Clawd's parameter model.
 *
 * This mirrors how a Live2D Cubism model works: the rig exposes a flat set of
 * named, bounded parameters, and everything else — motion clips, physics,
 * automatic blink, the behaviour director — writes into that set. The renderer
 * reads it and never knows who moved what.
 */

export type ParamId =
  // root body transform
  | 'posX'
  | 'posY'
  | 'angle'
  | 'scaleX'
  | 'scaleY'
  // limbs
  | 'clawL'
  | 'clawR'
  | 'legSwing'
  | 'legPhase'
  // face
  | 'eyeOpenL'
  | 'eyeOpenR'
  | 'eyeX'
  | 'eyeY'
  | 'eyeSmile'
  // ambience
  | 'breath'
  | 'talkLevel'
  | 'facing'
  | 'shadow'

type Spec = { min: number; max: number; def: number }

export const PARAMS: Record<ParamId, Spec> = {
  // Offsets from the anchor, in sprite units (1 unit = one pixel block).
  posX: { min: -40, max: 40, def: 0 },
  posY: { min: -30, max: 12, def: 0 },
  angle: { min: -35, max: 35, def: 0 },
  scaleX: { min: 0.6, max: 1.45, def: 1 },
  scaleY: { min: 0.6, max: 1.45, def: 1 },

  // Claw rotation in degrees. Positive lifts the claw upward on both sides;
  // the renderer mirrors the sign for the right claw so motions stay readable.
  clawL: { min: -110, max: 110, def: 0 },
  clawR: { min: -110, max: 110, def: 0 },

  // legSwing is the amplitude of the walk cycle, legPhase drives it 0..1.
  legSwing: { min: 0, max: 42, def: 0 },
  legPhase: { min: 0, max: 1, def: 0 },

  eyeOpenL: { min: 0, max: 1, def: 1 },
  eyeOpenR: { min: 0, max: 1, def: 1 },
  eyeX: { min: -1, max: 1, def: 0 },
  eyeY: { min: -1, max: 1, def: 0 },
  eyeSmile: { min: 0, max: 1, def: 0 },

  breath: { min: 0, max: 1, def: 0 },

  // Loudness of whatever Clawd is saying. He has no mouth, so the rig spends
  // this on the body — bob, squash, claw accents — and the shell carries the
  // rest of it in the renderer.
  talkLevel: { min: 0, max: 1, def: 0 },

  facing: { min: -1, max: 1, def: 1 },
  shadow: { min: 0, max: 1, def: 1 },
}

export const PARAM_IDS = Object.keys(PARAMS) as ParamId[]

export type ParamSet = Record<ParamId, number>

export function defaultParams(): ParamSet {
  const out = {} as ParamSet
  for (const id of PARAM_IDS) out[id] = PARAMS[id].def
  return out
}

export function clampParam(id: ParamId, v: number): number {
  const s = PARAMS[id]
  return v < s.min ? s.min : v > s.max ? s.max : v
}

export function setParam(set: ParamSet, id: ParamId, v: number): void {
  set[id] = clampParam(id, v)
}
