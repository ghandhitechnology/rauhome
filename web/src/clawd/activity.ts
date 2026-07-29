/**
 * How awake the room should be.
 *
 * The render loop's whole budget question reduces to one: is anybody there?
 * While someone is interacting — pointer, keys, a game on the table, the hub
 * mid-reply, a voice turn either way — the room runs at the display's own
 * rate, whatever that is (60Hz, 120Hz, 144Hz): rAF fires per vsync and every
 * one is drawn. Once nothing has happened for five minutes the room drops to
 * a quiet 15fps, enough for him to keep breathing and wandering without
 * holding a GPU to full rate over an empty chair.
 *
 * "Activity" is deliberately broad and cheap to record: one timestamp, written
 * by window input listeners, by the hub's event channel, and by the room's own
 * frame when the signals say a conversation is live. Reading it costs a
 * subtraction.
 */

/** How long without any sign of life before the room naps. */
export const IDLE_AFTER_MS = 5 * 60 * 1000

/** No cap: draw every vsync the display offers. */
export const FULL_RATE = Infinity

/** The quiet rate once the room has been idle for `IDLE_AFTER_MS`. */
export const IDLE_RATE = 15

function now(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

// A page that just loaded has somebody looking at it — start awake.
let lastActivity = now()
let installed = false

/**
 * Record a sign of life. Called by the input listeners below, by the hub's
 * event channel (`live.markActive`), and by the room when the signals say a
 * conversation is under way — voice levels never touch a window listener, and
 * the room must not nap mid-answer.
 */
export function noteActivity(): void {
  lastActivity = now()
}

/** Milliseconds since the last sign of life. */
export function idleMs(): number {
  return now() - lastActivity
}

/** True once nothing has happened for `IDLE_AFTER_MS`. */
export function isIdle(): boolean {
  return idleMs() >= IDLE_AFTER_MS
}

/**
 * The frame rate the render loop should run at right now.
 *
 * A game on the table is the one thing you are unambiguously *playing*, so it
 * always gets the display's rate. An explicit `eco` resource profile is the
 * user's own battery choice and is honoured even mid-conversation. Everything
 * else turns on the idle clock alone.
 */
export function pacingFor(opts: { table: boolean; profile: string }): number {
  if (opts.table) return FULL_RATE
  if (opts.profile === 'eco') return IDLE_RATE
  return isIdle() ? IDLE_RATE : FULL_RATE
}

/**
 * Arm the global input listeners. Idempotent; a no-op outside the browser.
 * Listeners are passive and write a single number, so even a 120Hz pointer
 * stream costs nothing measurable.
 */
export function watchActivity(): void {
  if (installed || typeof window === 'undefined') return
  installed = true
  const types = ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart'] as const
  for (const type of types) {
    window.addEventListener(type, noteActivity, { passive: true })
  }
}

/** Test hook: make the room look as if it has been idle for `ms`. */
export function setIdleForTests(ms: number): void {
  lastActivity = now() - ms
}
