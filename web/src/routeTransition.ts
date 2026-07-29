export type Point = {
  x: number
  y: number
}

export type RouteTransition =
  | { kind: 'room-open'; origin: Point }
  | { kind: 'room-close' }

const ROOM_CANVAS_WAIT_MS = 300

let resolveCanvas: (() => void) | null = null

/**
 * Hold a room route's new snapshot until its canvas has drawn once.
 *
 * A single route can be entering at a time. Arming a newer transition releases
 * an older waiter so a superseded navigation can never strand the router.
 */
export function waitForRouteCanvas(timeoutMs = ROOM_CANVAS_WAIT_MS): Promise<void> {
  resolveCanvas?.()

  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      if (resolveCanvas === finish) resolveCanvas = null
      resolve()
    }
    const timer = window.setTimeout(finish, timeoutMs)
    resolveCanvas = finish
  })
}

/** Called by the first frame of the incoming room or talk-page avatar. */
export function signalRouteCanvasReady() {
  resolveCanvas?.()
}

export function centerOf(rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>): Point {
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  }
}

export function rippleRadius(origin: Point, width: number, height: number): number {
  return Math.hypot(
    Math.max(origin.x, width - origin.x),
    Math.max(origin.y, height - origin.y),
  )
}

export function roomTransitionBetween(
  from: string,
  to: string,
  launcherRect?: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'> | null,
): RouteTransition | undefined {
  const fromPath = from.length > 1 ? from.replace(/\/+$/, '') : from
  const toPath = to.length > 1 ? to.replace(/\/+$/, '') : to
  if (fromPath === '/' && toPath === '/face') {
    const origin = launcherRect
      ? centerOf(launcherRect)
      : { x: window.innerWidth / 2, y: window.innerHeight / 2 }
    return { kind: 'room-open', origin }
  }
  if (fromPath === '/face' && toPath === '/') return { kind: 'room-close' }
  return undefined
}
