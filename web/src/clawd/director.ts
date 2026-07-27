/**
 * Clawd's behaviour. Turns Rau's live state into somewhere to stand and
 * something to do there, then walks him between the two.
 *
 * The director never touches parameters directly — it only picks motions,
 * aims the eyes and moves `worldX`. Everything else falls out of the rig.
 */

import { bodyController, GAZE_AIMS, type BodyCue } from './body'
import { clamp, damp } from './easing'
import { MOTIONS, ONE_SHOTS, WALK_SPEED, type MotionName } from './motions'
import type { ClawdRig, GazeAim } from './rig'
import { FLOOR_Y, STATIONS, WALK_RANGE, station, type StationId } from './room'

/** Everything the director needs to know about Rau right now. */
export type Signals = {
  emotion: string
  listening: boolean
  /** A chat request is in flight — LLM reasoning / waiting on first tokens. */
  thinking: boolean
  /**
   * A face tool or browse is running. Distinct from `thinking`: the bubble
   * ellipsis is for reasoning; desk work walks him to the computer instead.
   */
  working: boolean
  /**
   * A `/ws` reply is arriving token-by-token. While true, the bubble follows
   * `speech` even if desk-work would otherwise clear it.
   */
  streaming: boolean
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
  working: false,
  streaming: false,
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
  // What he actually does in each place, rather than a generic idle with a
  // different backdrop. Weighted by repetition: he is at the desk to work, and
  // at the window mostly to stare out of it.
  desk: ['type', 'search', 'search', 'think', 'scribble', 'read'],
  window: ['gaze', 'stargaze', 'stargaze', 'doze', 'ponder'],
  shelf: ['read', 'read', 'think', 'tidy', 'idle'],
  plant: ['water', 'tidy', 'idle', 'stretch'],
  rug: ['sit', 'idle', 'stretch', 'groove'],
  centre: ['idle', 'loiter', 'ponder', 'stretch', 'yawn', 'wave'],
  // The table is only ever reached deliberately, and the choreographer owns
  // what he does once he is there. This exists to satisfy the map.
  table: ['sitTable', 'idle'],
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

/** What the eyes are currently obeying. `cue` is a model-authored aim. */
type GazeSource = GazeIntent | 'cue'

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

/**
 * How long a deliberate goTo / cue station sticks before ambient wandering
 * may send him somewhere else again.
 */
const DIRECTED_HOLD = 20

export type DirectorMode = 'room' | 'roam' | 'conversing'

export class Director {
  /** Set true to stop autonomous wandering (used by the motion tester). */
  manual = false

  /**
   * Set while something else owns the eyes — the card table, where he watches
   * the pile, the card you are hovering, and you when you talk over his turn.
   * Conversation mode would otherwise pull his gaze back to the camera every
   * time he opened his mouth, and he talks the whole way through a game.
   */
  gazeHeld = false

  /**
   * Pin conversation mode on — for a caller that knows a voice session is live
   * even while the signals are momentarily quiet. `currentMode` still reports
   * what he is actually doing.
   */
  conversing = false

  private target: StationId = 'centre'
  private arrived = true
  /**
   * A human goTo or a model cue with a station. While set, conversing mode
   * holds that spot instead of dragging him back to centre.
   */
  private directed = false
  /** Clock time when directed may expire after arrival; 0 until he arrives. */
  private directedUntil = 0
  /** Whether the current directed walk is one someone is waiting on. */
  private directedHurry = false
  private nextDecisionAt = 0
  private clock = 0
  private lastReplySeen = 0
  private speakUntil = 0
  private startleUntil = 0
  private walkBlend = 0
  /** The clip currently carrying him across the room. */
  private gait: MotionName = 'walk'

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
  private gazeIntent: GazeSource | null = null

  /** The model-authored cue currently holding the body, or null. */
  private cue: BodyCue | null = null
  /** Whether this cue's motion has been played yet — deferred until arrival. */
  private cuePlayed = false
  /** Whether the active station cue has told the body controller it arrived. */
  private cueArrivalSignaled = false
  /** Which semantic gaze the current cue installed, so it is set only once. */
  private cueGazeName: string | null = null

  private rig: ClawdRig
  /** Where he goes back to once the conversation has gone quiet. */
  private baseMode: DirectorMode
  private mode: DirectorMode
  /** Horizontal leash in stage units (desktop pet uses a narrower band). */
  private walkRange = { ...WALK_RANGE }

  constructor(rig: ClawdRig, mode: DirectorMode = 'room') {
    this.rig = rig
    this.baseMode = mode === 'conversing' ? 'room' : mode
    this.mode = mode
    // Starting mid-conversation means holding station until the room goes quiet.
    if (mode === 'conversing') this.lastEngagedAt = 0
    this.rig.worldX = station('centre').x
  }

  /** Limit how far he may walk (keeps the desktop pet inside its window). */
  setWalkRange(range: { min: number; max: number }) {
    this.walkRange = {
      min: Math.min(range.min, range.max),
      max: Math.max(range.min, range.max),
    }
    this.rig.worldX = clamp(this.rig.worldX, this.walkRange.min, this.walkRange.max)
    if (this.roamX != null) {
      this.roamX = clamp(this.roamX, this.walkRange.min, this.walkRange.max)
    }
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

  /** True once he has reached wherever he was last sent. */
  get isArrived(): boolean {
    return this.arrived
  }

  /**
   * Take the eyes, or give them back.
   *
   * Giving them back clears the remembered aim as well, so the next tick
   * genuinely re-applies one instead of deciding nothing has changed and
   * leaving him staring wherever the last owner left him.
   */
  holdGaze(held: boolean) {
    this.gazeHeld = held
    if (!held) this.gazeIntent = null
  }

  /**
   * Send Clawd somewhere deliberately (Direct panel / human override).
   *
   * `hurry` is for walks the user is waiting on the end of — the card-table
   * ritual most of all, where a stroll in from the shelf would be four
   * seconds of nothing happening.
   */
  goTo(id: StationId, opts: { hurry?: boolean } = {}) {
    this.target = id
    this.arrived = false
    this.directed = true
    this.directedUntil = 0
    this.directedHurry = !!opts.hurry
    // Outrank a leftover one-shot or poke so the walk starts on the next tick.
    this.startleUntil = 0
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

  /** True while a model-authored cue owns the body. */
  get cued(): boolean {
    return this.cue !== null
  }

  /**
   * Take the body for one cue from the face model.
   *
   * A cue with somewhere to be walks there first and gestures on arrival:
   * playing the clip and then sliding across the room reads as two unrelated
   * things happening rather than one intention.
   */
  applyCue(cue: BodyCue) {
    this.cue = cue
    this.cuePlayed = false
    this.cueArrivalSignaled = false
    // A cue outranks the leftover lockout from a click or a reaction.
    this.startleUntil = 0
    if (cue.station) {
      this.target = cue.station
      this.arrived = false
      this.directed = true
      this.directedUntil = 0
      // The cue carries its own pace; a leftover hurry from a game ritual
      // must not make him sprint to the window.
      this.directedHurry = false
    }
    if (!cue.station && cue.motion) this.playCueMotion()
  }

  /** Hand the body back to autonomous behaviour. */
  releaseCue() {
    if (!this.cue) return
    const hadGaze = this.cueGazeName !== null
    // A station cue leaves directed set so conversing does not yank him back.
    this.cue = null
    this.cuePlayed = false
    this.cueArrivalSignaled = false
    this.cueGazeName = null
    // Deliberately no snap-back: he keeps the spot he was sent to, and the
    // ambient clock gets a beat before it decides to wander off again.
    this.nextDecisionAt = Math.max(this.nextDecisionAt, this.clock + 2.5)
    if (hadGaze) {
      // The behaviour layer often wants no aim at all, and "no aim" is not a
      // change it would notice — so the cue's aim has to be cleared here or he
      // keeps staring at the floor for the rest of the session.
      this.gazeIntent = null
      this.rig.setGaze(null)
    }
  }

  private playCueMotion() {
    // Mark even an empty motion as played: without this a station-only cue
    // never gets past this point, and the walk clip carries on marching on
    // the spot for the rest of the hold.
    this.cuePlayed = true
    const name = this.cue?.motion
    if (!name) return
    this.rig.play(name, { force: true, restart: true })
  }

  update(dt: number, s: Signals) {
    this.clock += dt
    const rig = this.rig

    // Live `/ws` text wins over thinking dots and desk-work bubble clears —
    // otherwise tool calls mid-reply wipe the stream the user is reading.
    if (s.streaming && s.speech) {
      const freshReply = s.lastReplyAt > this.lastReplySeen
      if (freshReply) {
        this.lastReplySeen = s.lastReplyAt
        if (!this.cue && !this.directed) {
          this.target = this.mode === 'roam' ? this.target : 'centre'
          this.arrived = this.mode === 'roam'
        }
        if (HAPPY.has(s.emotion)) this.react('celebrate')
      }
      if (freshReply || s.speech !== this.speech) {
        this.speech = s.speech
        this.speakUntil = this.clock + clamp(1.8 + s.speech.length * 0.045, 2.5, 14)
      }
    } else if (s.thinking && !s.working) {
      // Reasoning wait: thinking bubble. Tool/desk work uses the computer pose
      // instead — an ellipsis over a typing claw would say the wrong thing.
      const phase = Math.floor(this.clock * 3) % 3
      this.speech = ['.', '..', '...'][phase]
      this.speakUntil = this.clock + 0.5
    } else if (s.working && !s.rauSpeaking) {
      this.speech = null
    } else if (s.lastReplyAt > this.lastReplySeen) {
      // ── react to one-off events ────────────────────────────────────
      this.lastReplySeen = s.lastReplyAt
      if (s.speech) {
        this.speech = s.speech
        // Roughly reading speed, clamped to something watchable.
        this.speakUntil = this.clock + clamp(1.8 + s.speech.length * 0.045, 2.5, 11)
      }
      // A cue or deliberate goTo already said where he should be; pulling him
      // back to the middle of the room would undo that mid-sentence.
      if (!this.cue && !this.directed) {
        this.target = this.mode === 'roam' ? this.target : 'centre'
        this.arrived = this.mode === 'roam'
      }
      if (HAPPY.has(s.emotion)) this.react('celebrate')
    } else if (s.speech && s.speech !== this.speech) {
      // Progressive chat / caption growth — refresh the bubble without
      // treating every delta as a brand-new reply (no re-celebrate).
      this.speech = s.speech
      this.speakUntil = this.clock + clamp(1.8 + s.speech.length * 0.045, 2.5, 11)
    } else if (this.clock > this.speakUntil) {
      this.speech = null
    }

    this.updateMood(dt, s)
    this.updateBeats(s)
    this.expireDirected()

    // A model-authored cue outranks both conversation posture and ambient
    // wandering for as long as it holds the body.
    if (this.cue) {
      if (this.clock < this.startleUntil || (rig.busy && !this.cue.station)) {
        this.settleWalk(dt, 0)
        return
      }
      this.followCue(dt, s)
      return
    }

    // Direct-panel goTo outranks one-shots and conversing — otherwise a poke
    // or voice session leaves "Send him to" stuck on centre forever.
    if (this.directed && !this.arrived) {
      const spot = station(this.target)
      if (this.travelTo(this.clampX(spot.x), dt, 'walk', this.directedHurry)) return
      this.markStationArrival(spot.facing)
      this.directedHurry = false
    }

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
    if (!this.directed) {
      const desired = this.desiredStation(s)
      if (desired && desired !== this.target) {
        this.target = desired
        this.arrived = false
      }
    }

    // ── walk there ───────────────────────────────────────────────────
    const targetX =
      this.mode === 'roam'
        ? (this.roamX ?? rig.worldX)
        : this.clampX(station(this.target).x)
    if (this.travelTo(targetX, dt)) return

    if (!this.arrived) {
      this.markStationArrival(this.mode === 'room' ? station(this.target).facing : this.rig.facing)
      this.nextDecisionAt = this.clock + 3 + Math.random() * 5
      this.playAmbient(s)
    }

    this.settleWalk(dt, 0)

    // ── ambient churn ────────────────────────────────────────────────
    if (this.clock >= this.nextDecisionAt) {
      this.nextDecisionAt = this.clock + 6 + Math.random() * 10
      if (this.isPinned(s) || this.directed) {
        this.playAmbient(s)
      } else if (this.mode === 'room') {
        // Wander somewhere new now and then — stay inside the leash.
        const options = STATIONS.filter(
          (st) =>
            st.id !== this.target &&
            // The card table is not somewhere he wanders to. Sitting down at
            // it with no game on would be him miming a hand of cards.
            st.id !== 'table' &&
            st.x >= this.walkRange.min &&
            st.x <= this.walkRange.max,
        )
        const pick =
          options.length > 0
            ? options[Math.floor(Math.random() * options.length)]
            : null
        if (pick && Math.random() < 0.7) {
          this.target = pick.id
          this.arrived = false
        } else {
          this.playAmbient(s)
        }
      } else {
        const span = this.walkRange.max - this.walkRange.min
        this.roamX = this.walkRange.min + Math.random() * span
        this.arrived = false
      }
    }
  }

  /**
   * Carry out the cue that currently owns the body.
   *
   * Walk first if it named a station, gesture on arrival, then hold whatever
   * pose it asked for until the controller takes the body back. A one-shot
   * that has finished settles into the conversation pose rather than freezing
   * on its last frame for the rest of the hold.
   */
  private followCue(dt: number, s: Signals) {
    const cue = this.cue
    if (!cue) return

    // A cue whose motion is itself a way of moving — carry, push, tiptoe,
    // pace — travels *in* that clip rather than walking there and then
    // adopting it on arrival. "Carry it to the shelf" is one action.
    const gait = cue.motion && this.isGait(cue.motion) ? cue.motion : 'walk'

    if (cue.station) {
      const spot = station(cue.station)
      if (this.travelTo(this.clampX(spot.x), dt, gait, !!cue.hurry)) return
      if (!this.arrived) this.markStationArrival(spot.facing)
      this.signalCueArrival()
      if (!this.cuePlayed) {
        // A gait has been playing its clip through the whole walk here —
        // restarting it for the one frame before the pose swap reads as a
        // stumble on the doorstep, not as arriving.
        if (cue.motion && this.isGait(cue.motion)) this.cuePlayed = true
        else {
          this.playCueMotion()
          return
        }
      }
    }

    this.settleWalk(dt, 0)

    if (!cue.motion) {
      this.setLoop(this.conversationPose(s))
      return
    }
    if (this.rig.busy) return
    // A gait that has arrived has nothing left to do; settle rather than
    // marching on the spot at the destination.
    if (cue.station && this.isGait(cue.motion)) {
      this.setLoop(this.conversationPose(s))
      return
    }
    this.setLoop(ONE_SHOTS.includes(cue.motion) ? this.conversationPose(s) : cue.motion)
  }

  /**
   * Conversation mode: hold station and face the camera, cycling
   * listen → think → talk. Default station is centre; a directed goTo or cue
   * keeps him where he was sent so movement is not undone mid-conversation.
   */
  private converse(dt: number, s: Signals) {
    const rig = this.rig
    // Tool work breaks the usual centre latch — he should be at the computer.
    const home: StationId = s.working ? 'desk' : 'centre'
    const spot = station(this.directed ? this.target : home)
    if (!this.directed && this.target !== home) {
      this.target = home
      this.arrived = false
    }
    if (this.travelTo(spot.x, dt, 'walk', s.working)) return

    if (!this.arrived) this.markStationArrival(spot.facing)
    else rig.facing = spot.facing
    this.settleWalk(dt, 0)

    const pose = this.conversationPose(s)
    this.setLoop(pose)

    // Idle variety, but only in the gaps — a stretch mid-answer reads as bored.
    if (pose === 'idle' && this.clock >= this.nextIdleBeatAt) {
      this.nextIdleBeatAt = this.clock + 14 + Math.random() * 16
      this.react('stretch', 6)
    }
  }

  private markStationArrival(facing: 1 | -1) {
    this.arrived = true
    this.rig.facing = facing
    if (this.directed) this.directedUntil = this.clock + DIRECTED_HOLD
  }

  /** Tell the body controller a station cue has landed so its hold can start. */
  private signalCueArrival() {
    if (!this.cue?.station || this.cueArrivalSignaled) return
    this.cueArrivalSignaled = true
    bodyController.cueArrived()
  }

  private expireDirected() {
    if (!this.directed || this.cue) return
    if (!this.arrived || this.directedUntil <= 0) return
    if (this.clock < this.directedUntil) return
    this.directed = false
    this.directedUntil = 0
  }

  private conversationPose(s: Signals): MotionName {
    if (s.emotion === 'sleep') return 'sleep'
    if (s.rauSpeaking || (this.speech !== null && !s.thinking && !s.working)) return 'talk'
    if (s.working) return 'type'
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
      // A cue owns where he stands and what he is doing; switching behaviour
      // underneath it must not walk him back to the middle of the room or
      // stomp the clip it just started.
      if (!this.cue) this.arrived = false
      if (mode === 'conversing') {
        if (!this.cue && !this.directed) this.target = 'centre'
        this.nextIdleBeatAt = this.clock + 10
      } else if (!this.manual && !this.cue) {
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

    if (this.gazeHeld) return

    // A cue that named somewhere to look owns the eyes for its whole hold —
    // including through the walk, so he looks where he is going.
    const cueGaze = this.cue?.gaze
    if (cueGaze) {
      if (this.gazeIntent !== 'cue' || this.cueGazeName !== cueGaze) {
        this.gazeIntent = 'cue'
        this.cueGazeName = cueGaze
        this.rig.setGaze(GAZE_AIMS[cueGaze])
      }
      return
    }
    this.cueGazeName = null

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
      s.working ||
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
    // Ambient beats sit below a deliberate cue; being cut off does not.
    if (this.cue && !urgent) return false
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
    // A finished one-shot still reports its id, so "already playing" must mean
    // actually playing — otherwise re-picking it leaves him frozen on its last
    // frame until the next decision comes around.
    if (this.rig.currentMotion === name && !restart && !this.rig.player.isFinished) return
    this.rig.play(name, { force: true, restart })
  }

  private clampX(x: number) {
    return clamp(x, this.walkRange.min, this.walkRange.max)
  }

  /**
   * Walk toward a stage-unit x. True while still travelling.
   *
   * `gait` names the clip that carries him. Anything with a `locomotion` speed
   * qualifies — carrying something is slower and heavier than a free walk,
   * tiptoeing is quicker and lighter — and the clip's own speed is what he
   * actually travels at, so the legs never slide against the floor.
   */
  private travelTo(
    targetX: number,
    dt: number,
    gait: MotionName = 'walk',
    hurry = false,
  ): boolean {
    const rig = this.rig
    const goal = this.clampX(targetX)
    const dx = goal - rig.worldX
    const dist = Math.abs(dx)
    if (dist <= 1.2) return false

    const clip = MOTIONS[gait]
    const cruise = clip.locomotion || WALK_SPEED
    // Tool dashes to the desk should feel purposeful, not a stroll.
    const boost = hurry ? 1.7 : 1

    this.arrived = false
    rig.facing = dx > 0 ? 1 : -1
    // Ease the last stretch so he does not stop dead.
    const speed = cruise * boost * clamp(dist / 6, 0.35, 1)
    const step = Math.min(dist, speed * dt)
    rig.worldX += step * rig.facing
    rig.worldX = this.clampX(rig.worldX)
    // Advance the cycle by distance covered against this clip's own stride, so
    // a slow heavy gait takes slow heavy steps rather than sprinting in place.
    rig.advanceLegs((step / cruise) * (1 / clip.duration) * 1.6)
    this.gait = gait
    this.setLoop(gait)
    this.settleWalk(dt, 1)
    return true
  }

  /** Whether a clip is one that carries him across the room. */
  private isGait(name: MotionName): boolean {
    return !!MOTIONS[name].locomotion
  }

  /** Blend the travel clip out smoothly when he stops. */
  private settleWalk(dt: number, target: number) {
    this.walkBlend = damp(this.walkBlend, target, 8, dt)
    if (target === 0 && this.walkBlend < 0.05 && this.rig.currentMotion === this.gait) {
      this.setLoop('idle')
      this.gait = 'walk'
    }
  }

  /** Whether current state forces a specific spot rather than free wandering. */
  private isPinned(s: Signals): boolean {
    return (
      s.thinking ||
      s.working ||
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
    // Desk is for real computer work, not for every reasoning pause.
    if (s.working || s.hardState === 'running') return 'desk'
    if (s.thinking) return 'centre'
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
    if (s.working || s.hardState === 'running' || s.jobs.length > 0) {
      if (this.target === 'desk') return s.working ? 'search' : 'type'
      return 'shuffle'
    }
    if (s.thinking) return 'think'
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
