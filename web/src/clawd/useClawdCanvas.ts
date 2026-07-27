import { useEffect, useRef } from 'react'

/**
 * Runs a device-pixel-correct canvas render loop.
 *
 * Handles DPR, resize observation, pausing when the tab is hidden, and clamps
 * dt so a backgrounded tab does not resume with one enormous timestep that
 * teleports the character across the room.
 */
export function useClawdCanvas(
  draw: (ctx: CanvasRenderingContext2D, dt: number, w: number, h: number) => void,
  deps: unknown[] = [],
) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawRef = useRef(draw)
  drawRef.current = draw

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    let raf = 0
    let timer: ReturnType<typeof setTimeout> | null = null
    let last = performance.now()
    let width = 0
    let height = 0
    let disposed = false

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

    const targetFps = () => {
      const root = document.documentElement.dataset
      // A hand of cards is the one thing here you are actually *playing*, and
      // a card sliding at 30fps under a hand that moves at 120 is the one
      // place the whole room reads as a cartoon of an interface. It gets the
      // display's own rate for as long as the table is out, and gives it back
      // the moment he stands up.
      if (root.rauTable === 'true') return 60
      const profile = root.resourceProfile || 'balanced'
      const active = root.rauActive === 'true'
      return profile === 'performance' ? 60 : active ? 30 : profile === 'eco' ? 15 : 24
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
    */
    const frame = (now: number) => {
      raf = 0
      if (disposed) return
      const fps = targetFps()
      const budget = 1000 / fps - 0.6
      const elapsed = now - last
      if (elapsed < budget) {
        scheduleFrame()
        return
      }
      // 100ms ceiling: long enough to absorb a hitch, short enough that a
      // restored tab does not fast-forward the simulation.
      const dt = Math.min(0.1, Math.max(0, elapsed / 1000))
      last = now
      if (!document.hidden) {
        ctx.clearRect(0, 0, width, height)
        drawRef.current(ctx, dt, width, height)
      }
      scheduleFrame()
    }

    const scheduleFrame = () => {
      // A hidden tab stops firing rAF, so the slow path keeps a heartbeat
      // going: it is how the loop notices it has been un-hidden.
      if (document.hidden) {
        timer = setTimeout(() => {
          timer = null
          raf = requestAnimationFrame(frame)
        }, 250)
        return
      }
      raf = requestAnimationFrame(frame)
    }

    scheduleFrame()

    const onVisible = () => {
      last = performance.now()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      if (timer) clearTimeout(timer)
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVisible)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return canvasRef
}
