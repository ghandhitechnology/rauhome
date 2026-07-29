import { useLayoutEffect, useRef } from 'react'
import { FULL_RATE, pacingFor, watchActivity } from './activity'

/**
 * Runs a device-pixel-correct canvas render loop.
 *
 * Handles DPR, resize observation, pausing when the tab is hidden, and clamps
 * dt so a backgrounded tab does not resume with one enormous timestep that
 * teleports the character across the room.
 *
 * The rate is the display's own whenever anybody is around — a 120Hz panel
 * gets 120 drawn frames a second — and a quiet 15fps only once the room has
 * been left alone for five minutes (see `activity.ts`).
 */
export function useClawdCanvas(
  draw: (ctx: CanvasRenderingContext2D, dt: number, w: number, h: number) => void,
  deps: unknown[] = [],
  options: { onFirstFrame?: () => void } = {},
) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawRef = useRef(draw)
  const onFirstFrameRef = useRef(options.onFirstFrame)
  drawRef.current = draw
  onFirstFrameRef.current = options.onFirstFrame

  useLayoutEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    let raf = 0
    let last = performance.now()
    let width = 0
    let height = 0
    let disposed = false
    let firstFrame = true

    const resize = () => {
      const profile = document.documentElement.dataset.resourceProfile || 'balanced'
      const maxDpr = profile === 'eco' ? 1 : profile === 'performance' ? 2 : 1.5
      const dpr = Math.min(window.devicePixelRatio || 1, maxDpr)
      const rect = canvas.getBoundingClientRect()
      width = Math.max(1, Math.round(rect.width))
      height = Math.max(1, Math.round(rect.height))
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    watchActivity()

    const targetFps = () => {
      const root = document.documentElement.dataset
      return pacingFor({
        table: root.rauTable === 'true',
        profile: root.resourceProfile || 'balanced',
      })
    }

    /*
      Paced on rAF alone, not on a timer that then asks for a frame.
      `setTimeout(1000/fps)` followed by `requestAnimationFrame` costs a
      timeout *and* a wait for the next vsync, so 60fps asked for 16.7ms and
      got 33 — every other frame dropped, which is exactly the judder this is
      meant to avoid. Here every vsync is considered and one is skipped only
      when the budget for the target rate has not elapsed. The 0.6 slack is a
      half-ish frame: without it a 16.66ms vsync always lands a hair under a
      16.67ms budget and every frame is skipped.

      FULL_RATE draws every vsync: the budget is negative, so the skip branch
      can never fire and the display — 60Hz, 120Hz, 144Hz — sets the pace.
    */
    const paint = (dt: number) => {
      ctx.clearRect(0, 0, width, height)
      drawRef.current(ctx, dt, width, height)
      if (!firstFrame) return
      firstFrame = false
      onFirstFrameRef.current?.()
    }

    const frame = (now: number) => {
      raf = 0
      if (disposed) return
      const fps = targetFps()
      const budget = fps === FULL_RATE ? -1 : 1000 / fps - 0.6
      const elapsed = now - last
      if (elapsed < budget) {
        scheduleFrame()
        return
      }
      // 100ms ceiling: long enough to absorb a hitch, short enough that a
      // restored tab does not fast-forward the simulation.
      const dt = Math.min(0.1, Math.max(0, elapsed / 1000))
      last = now
      if (!document.hidden) paint(dt)
      scheduleFrame()
    }

    const scheduleFrame = () => {
      // Visibility events restart the loop. Do no work while hidden: even a
      // 250ms timer becomes thousands of needless wakeups in a background tab.
      if (document.hidden) return
      raf = requestAnimationFrame(frame)
    }

    // Paint once in the layout phase. Room view transitions can now capture a
    // complete incoming canvas immediately instead of waiting for the next rAF
    // (or for the safety timeout when rendering is paused during a snapshot).
    if (!document.hidden) paint(0)
    last = performance.now()
    scheduleFrame()

    const onVisible = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf)
        raf = 0
        return
      }
      last = performance.now()
      if (!raf) scheduleFrame()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVisible)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return canvasRef
}
