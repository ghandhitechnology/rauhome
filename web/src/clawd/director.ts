/**
 * Clawd's behaviour. Turns Rau's live state into somewhere to stand and
 * something to do there, then walks him between the two.
 *
 * The director never touches parameters directly — it only picks motions,
 * aims the eyes and moves `worldX`. Everything else falls out of the rig.
 */

import { clamp, damp } from './easing'
import { MOTIONS, ONE_SHOTS, WALK_SPEED, type MotionName } from './motions'
import type { ClawdRig, GazeAim } from './rig'
import { FLOOR_Y, STATIONS, WALK_RANGE, station, type StationId } from './room'

/** Everything the director needs to know about Rau right now. */
export type Signals = {
  emotion: string
  listening: boolean
  /** A chat request is in flight. */
  thinking: boolean
  /** hard_task.state from the hub. */
  hardState: string
  /** Timestamp (ms) of the newest assistant message, or 0. */
  lastReplyAt: number
  /** Text Clawd should say, or null. */
  speech: string | null
  /** A confirmation is waiting on the user. */
  awaitingConfirm: boolean
  /** The user's voice is active right now, as opposed to the mic being armed. */
  userSpeaking: boolean
  /** Rau's own speech is playing. */
  rauSpeaking: boolean
  /** Live input amplitude, 0..1. */
  userLevel: number
  /** Live TTS output amplitude, 0..1 — drives the whole speaking body. */
  rauLevel: number
  /** Timestamp (ms) of the last time the user talked over Rau, or 0. */
  interruptedAt: number
  /** Coarse emotional tag for the line being spoken, or null. */
  sentenceTag: string | null
  /** Background jobs currently running. */
  jobs: string[]
}

export const EMPTY_SIGNALS: Signals = {
  emotion: 'idle',
  listening: false,
  thinking: false,
  hardState: 'idle',
  lastReplyAt: 0,
  speech: null,
  awaitingConfirm: false,
  userSpeaking: false,
  rauSpeaking: false,
  userLevel: 0,
  rauLevel: 0,
  interruptedAt: 0,
  sentenceTag: null,
  jobs: [],
}

/** What Clawd does once he has arrived somewhere. */
const AMBIENT: Record<StationId, MotionName[]> = {
  desk: ['type', 'think'],
  window: ['gaze'],
  shelf: ['think', 'idle'],
  plant: ['idle', 'stretch'],
  rug: ['idle', 'stretch'],
  centre: ['idle', 'idle', 'wave', 'stretch'],
}

const HAPPY = new Set(['happy', 'excited', 'love', 'amazed'])
const LOW = new Set(['sad', 'scared'])

/** One-shot beats for the tag on the line Rau is currently saying. */
const TAG_BEATS: Record<string, MotionName> = {
  happy: 'perk',
  excited: 'perk',
  greeting: 'wave',
  celebrate: 'celebrate',
  amazed: 'recoil',
  surprise: 'recoil',
  surprised: 'recoil',
  scared: 'recoil',
  uncertain: 'shrug',
  unsure: 'shrug',
  confused: 'shrug',
  question: 'shrug',
  agree: 'nod',
  yes: 'nod',
}

type GazeIntent = 'camera' | 'away' | 'lock'

const GAZES: Record<GazeIntent, GazeAim> = {
  camera: { x: 0, y: 0.08, speed: 7, wander: 0.35 },
  // People break eye contact while they recall. Slow, high and off to one side.
  away: { x: -0.6, y: -0.5, speed: 2.2, wander: 0.9 },
  // Snapped back on the first word of a reply.
  lock: { x: 0, y: 0.05, speed: 15, wander: 0.2 },
}

/**
 * Floor on the gap between reaction one-shots. Without it every signal that
 * twitches turns him into a character having a seizure rather than a lively one.
 */
const REACTION_GAP = 1.9
const NOD_GAP = 1.5

/** How long after the last conversational signal he keeps holding station. */
const CONVERSATION_HOLD = 18

export type DirectorMode = 'room' | 'roam' | 'conversing'

export class Director {
  /** Set true to stop autonomous wandering (used by the motion tester). */
  manual = false

  /**
   * Pin conversation mode on — for a caller that knows a voice session is live
   * even while the signals are momentarily quiet. `currentMode` still reports
   * what he is actually doing.
   */
  conversing = false

  private target: StationId = 'centre'
  private arrived = true
  private nextDecisionAt = 0
  private clock = 0
  private lastReplySeen = 0
  private speakUntil = 0
  private startleUntil = 0
  private walkBlend = 0

  /** Free-roam target in stage units, used when there are no stations. */
  private roamX: number | null = null

  /** Conversation state. */
  private lastEngagedAt = -CONVERSATION_HOLD * 2
  private wasUserSpeaking = false
  private userSpokeSince = 0
  private userQuietAt = 0
  private nextNodAt = 0
  private nextIdleBeatAt = 0
  private reactionReadyAt = 0
  private lastTag: string | null = null
  private lastInterrupt = 0
  private gazeIntent: GazeIntent | null = null

  private rig: ClawdRig
  /** Where he goes back to once the conversation has gone quiet. */
  private baseMode: DirectorMode
  private mode: DirectorMode

  constructor(rig: ClawdRig, mode: DirectorMode = 'room') {
    this.rig = rig
    this.baseMode = mode === 'conversing' ? 'room' : mode
    this.mode = mode
    // Starting mid-conversation means holding station until the room goes quiet.
    if (mode === 'conversing') this.lastEngagedAt = 0
    this.rig.worldX = station('centre').x
  }

  /** Current speech bubble text, or null. */
  speech: string | null = null

  get targetStation(): StationId {
    return this.target
  }

  get currentMode(): DirectorMode {
    return this.mode
  }

  /**
   * Switch behaviour mid-session — a voice session starting or ending, rather
   * than a new Director, so he keeps his position and whatever he was doing.
   */
  setMode(mode: DirectorMode) {
    this.conversing = mode === 'conversing'
    if (this.conversing) {
      // Hold it open until the room actually goes quiet, the same way a
      // conversation detected from the signals does.
      this.lastEngagedAt = this.clock
    } else {
      this.baseMode = mode
      // An explicit end leaves only a short tail — long enough that he does not
      // turn on his heel the instant the session drops.
      this.lastEngagedAt = Math.min(this.lastEngagedAt, this.clock - CONVERSATION_HOLD + 4)
    }
    // The switch itself lands on the next tick, so entering and leaving a
    // conversation always runs through one path.
  }

  /** Send Clawd somewhere deliberately. */
  goTo(id: StationId) {
    this.target = id
    this.arrived = false
  }

  /** Poke him — he jumps, then carries on. */
  startle() {
    if (this.rig.play('startle', { force: true, restart: true })) {
      this.startleUntil = this.clock + 0.85
    }
  }

  /** Play a clip immediately and suspend autonomous choices while it runs. */
  force(name: MotionName) {
    this.rig.play(name, { force: true, restart: true })
    this.startleUntil = this.clock + 0.4
  }

  update(dt: number, s: Signals) {
    this.clock += dt
    const rig = this.rig

    // Waiting on a reply: show a moving ellipsis — never the previous line.
    if (s.thinking) {
      const phase = Math.floor(this.clock * 3) % 3
      this.speech = ['.', '..', '...'][phase]
      this.speakUntil = this.clock + 0.5
    } else if (s.lastReplyAt > this.lastReplySeen) {
      // ── react to one-off events ────────────────────────────────────
      this.lastReplySeen = s.lastReplyAt
      if (s.speech) {
        this.speech = s.speech
        // Roughly reading speed, clamped to something watchable.
        this.speakUntil = this.clock + clamp(1.8 + s.speech.length * 0.045, 2.5, 11)
      }
      this.target = this.mode === 'roam' ? this.target : 'centre'
      this.arrived = this.mode === 'roam'
      if (HAPPY.has(s.emotion)) this.react('celebrate')
    } else if (this.clock > this.speakUntil) {
      this.speech = null
    }

    this.updateMood(dt, s)
    this.updateBeats(s)

    // A deliberate one-shot owns the character until it finishes.
    if (this.clock < this.startleUntil || rig.busy) {
      this.settleWalk(dt, 0)
      return
    }

    if (this.manual) {
      this.settleWalk(dt, 0)
      return
    }

    if (this.mode === 'conversing') {
      this.converse(dt, s)
      return
    }

    // ── choose where to be ───────────────────────────────────────────
    const desired = this.desiredStation(s)
    if (desired && desired !== this.target) {
      this.target = desired
      this.arrived = false
    }

    // ── walk there ───────────────────────────────────────────────────
    const targetX = this.mode === 'roam' ? (this.roamX ?? rig.worldX) : station(this.target).x
    if (this.travelTo(targetX, dt)) return

    if (!this.arrived) {
      this.arrived = true
      this.nextDecisionAt = this.clock + 3 + Math.random() * 5
      if (this.mode === 'room') rig.facing = station(this.target).facing
      this.playAmbient(s)
    }

    this.settleWalk(dt, 0)

    // ── ambient churn ────────────────────────────────────────────────
    if (this.clock >= this.nextDecisionAt) {
      this.nextDecisionAt = this.clock + 6 + Math.random() * 10
      if (this.isPinned(s)) {
        this.playAmbient(s)
      } else if (this.mode === 'room') {
        // Wander somewhere new now and then.
        const options = STATIONS.filter((st) => st.id !== this.target)
        const pick = options[Math.floor(Math.random() * options.length)]
        if (Math.random() < 0.7) {
          this.target = pick.id
          this.arrived = false
        } else {
          this.playAmbient(s)
        }
      } else {
        this.roamX = WALK_RANGE.min + Math.random() * (WALK_RANGE.max - WALK_RANGE.min)
        this.arrived = false
      }
    }
  }

  /**
   * Conversation mode: hold the centre of the room, face the camera and cycle
   * listen → think → talk. Wandering off to water the plant halfway through an
   * answer is the single fastest way to break the illusion of attention.
   */
  private converse(dt: number, s: Signals) {
    const rig = this.rig
    const spot = station('centre')
    if (this.travelTo(spot.x, dt)) return

    this.arrived = true
    rig.facing = spot.facing
    this.settleWalk(dt, 0)

    const pose = this.conversationPose(s)
    this.setLoop(pose)

    // Idle variety, but only in the gaps — a stretch mid-answer reads as bored.
    if (pose === 'idle' && this.clock >= this.nextIdleBeatAt) {
      this.nextIdleBeatAt = this.clock + 14 + Math.random() * 16
      this.react('stretch', 6)
    }
  }

  private conversationPose(s: Signals): MotionName {
    if (s.emotion === 'sleep') return 'sleep'
    if (s.rauSpeaking || (this.speech !== null && !s.thinking)) return 'talk'
    if (s.hardState === 'running' || s.jobs.length > 0) return 'shuffle'
    if (s.thinking) return 'think'
    if (s.userSpeaking || s.listening || s.awaitingConfirm) return 'listen'
    // Stay attentive through the short gaps between turns.
    return this.clock - this.lastEngagedAt < 6 ? 'listen' : 'idle'
  }

  /** Conversation mode, breathing rate and where the eyes are pointed. */
  private updateMood(dt: number, s: Signals) {
    if (this.conversing || this.engaged(s)) this.lastEngagedAt = this.clock
    const mode: DirectorMode =
      this.clock - this.lastEngagedAt < CONVERSATION_HOLD ? 'conversing' : this.baseMode

    if (mode !== this.mode) {
      this.mode = mode
      this.arrived = false
      if (mode === 'conversing') {
        this.target = 'centre'
        this.nextIdleBeatAt = this.clock + 10
      } else if (!this.manual) {
        // A looping clip never reports finished, so the conversation pose would
        // outrank everything the ambient behaviour tries next.
        this.rig.play('idle', { force: true })
      }
    }

    // Hand the voice envelope to the rig. A host that measures the TTS output
    // itself passes it through RigOptions instead, which wins over this. The
    // level is only meaningful while he is the one talking — an output meter
    // still ringing down after the last chunk is not speech.
    this.rig.talkLevel = s.rauSpeaking ? s.rauLevel : 0

    this.rig.breathRate = damp(this.rig.breathRate, this.breathRateFor(s), 1.6, dt)

    const intent = this.gazeFor(s)
    if (intent !== this.gazeIntent) {
      this.gazeIntent = intent
      this.rig.setGaze(intent ? GAZES[intent] : null)
    }
  }

  /**
   * Effort has to show up somewhere, and with no mouth or brow to work with the
   * breath is the one channel no clip ever competes for.
   */
  private breathRateFor(s: Signals): number {
    if (s.emotion === 'sleep') return 0.55
    if (s.thinking || s.hardState === 'running' || s.jobs.length > 0) return 1.6
    if (HAPPY.has(s.emotion)) return 1.4
    if (s.rauSpeaking) return 1.25
    if (s.userSpeaking || s.listening) return 1.05
    return 1
  }

  private gazeFor(s: Signals): GazeIntent | null {
    if (this.mode !== 'conversing') return null
    if (s.rauSpeaking || (this.speech !== null && !s.thinking)) return 'lock'
    if (s.thinking || s.hardState === 'running' || s.jobs.length > 0) return 'away'
    return 'camera'
  }

  /** One-shot reactions: interruption, sentence tags, and backchannel nods. */
  private updateBeats(s: Signals) {
    // Being cut off outranks whatever else he was in the middle of.
    if (s.interruptedAt > this.lastInterrupt) {
      this.lastInterrupt = s.interruptedAt
      this.react('recoil', 2.2, true)
    }

    if (s.sentenceTag !== this.lastTag) {
      this.lastTag = s.sentenceTag
      const beat = s.sentenceTag ? TAG_BEATS[s.sentenceTag] : undefined
      if (beat) this.react(beat)
    }

    // Backchannel. A listener who never nods reads as a frozen video call.
    if (s.userSpeaking !== this.wasUserSpeaking) {
      this.wasUserSpeaking = s.userSpeaking
      if (s.userSpeaking) {
        // Being addressed after a silence deserves a visible pick-up.
        if (this.clock - this.userQuietAt > 2.5) this.react('perk', 2.2)
        this.userSpokeSince = this.clock
        this.nextNodAt = this.clock + 2.4 + Math.random() * 2
      } else {
        this.userQuietAt = this.clock
        // The pause at the end of a thought is where a listener actually nods.
        if (this.clock - this.userSpokeSince > 0.7) this.react('nod', NOD_GAP)
      }
    } else if (s.userSpeaking && this.clock >= this.nextNodAt) {
      // Mid-turn nods keep a long stretch of talking from feeling ignored.
      if (this.react('nod', NOD_GAP)) this.nextNodAt = this.clock + 3.2 + Math.random() * 2.6
    }
  }

  /** Whether anything in the signals counts as an active exchange. */
  private engaged(s: Signals): boolean {
    // `listening` is deliberately absent: an always-armed microphone would pin
    // him to the middle of the room forever and kill the ambient life.
    return (
      s.userSpeaking ||
      s.rauSpeaking ||
      s.thinking ||
      s.awaitingConfirm ||
      this.speech !== null
    )
  }

  /**
   * Fire a reaction clip, subject to the rate limit. `urgent` skips both the
   * wait and the clip already running — being cut off is exactly the moment he
   * is most likely to be mid-gesture — but still resets the wait, so it never
   * opens the door to a run of them.
   */
  private react(name: MotionName, cooldown = REACTION_GAP, urgent = false): boolean {
    if (this.manual) return false
    if (!urgent && (this.rig.busy || this.clock < this.reactionReadyAt)) return false
    this.rig.play(name, { force: true, restart: true })
    this.reactionReadyAt = this.clock + cooldown
    return true
  }

  /**
   * Swap the standing loop. Forced, because a looping clip never reports
   * finished and priority alone would let a stale walk or listen block
   * everything that comes after it.
   */
  private setLoop(name: MotionName, restart = false) {
    if (this.rig.currentMotion === name && !restart) return
    this.rig.play(name, { force: true, restart })
  }

  /** Walk toward a stage-unit x. True while still travelling. */
  private travelTo(targetX: number, dt: number): boolean {
    const rig = this.rig
    const dx = targetX - rig.worldX
    const dist = Math.abs(dx)
    if (dist <= 1.2) return false

    this.arrived = false
    rig.facing = dx > 0 ? 1 : -1
    // Ease the last stretch so he does not stop dead.
    const speed = WALK_SPEED * clamp(dist / 6, 0.35, 1)
    const step = Math.min(dist, speed * dt)
    rig.worldX += step * rig.facing
    rig.worldX = clamp(rig.worldX, WALK_RANGE.min, WALK_RANGE.max)
    rig.advanceLegs((step / WALK_SPEED) * (1 / 0.62) * 1.6)
    this.setLoop('walk')
    this.settleWalk(dt, 1)
    return true
  }

  /** Blend the walk clip out smoothly when he stops. */
  private settleWalk(dt: number, target: number) {
    this.walkBlend = damp(this.walkBlend, target, 8, dt)
    if (target === 0 && this.walkBlend < 0.05 && this.rig.currentMotion === 'walk') {
      this.setLoop('idle')
    }
  }

  /** Whether current state forces a specific spot rather than free wandering. */
  private isPinned(s: Signals): boolean {
    return (
      s.thinking ||
      s.hardState === 'running' ||
      s.jobs.length > 0 ||
      s.awaitingConfirm ||
      LOW.has(s.emotion) ||
      this.speech !== null
    )
  }

  private desiredStation(s: Signals): StationId | null {
    if (this.mode !== 'room') return null
    if (s.awaitingConfirm) return 'centre'
    if (s.thinking || s.hardState === 'running') return 'desk'
    if (this.speech) return 'centre'
    if (LOW.has(s.emotion)) return 'window'
    return null
  }

  private playAmbient(s: Signals) {
    const pick = this.ambientPick(s)
    this.setLoop(pick, pick === 'wave')
    // A finished one-shot holds its last pose, so come back for a loop as soon
    // as it is done rather than leaving him frozen mid-gesture.
    if (ONE_SHOTS.includes(pick)) {
      this.nextDecisionAt = this.clock + MOTIONS[pick].duration + 0.3
    }
  }

  private ambientPick(s: Signals): MotionName {
    if (s.thinking || s.hardState === 'running' || s.jobs.length > 0) {
      if (this.target === 'desk') return 'type'
      return s.thinking ? 'think' : 'shuffle'
    }
    if (this.speech) return 'talk'
    if (s.awaitingConfirm) return 'wave'
    if (LOW.has(s.emotion)) return 'gaze'
    if (s.emotion === 'sleep') return 'sleep'

    const pool = AMBIENT[this.target]
    return pool[Math.floor(Math.random() * pool.length)]
  }
}

/** Convert a stage-unit x into the sprite's screen anchor. */
export function stageAnchor(worldX: number) {
  return { x: worldX, y: FLOOR_Y }
}
