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
    let last = performance.now()
    let width = 0
    let height = 0
    let disposed = false

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
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

    const frame = (now: number) => {
      if (disposed) return
      // 100ms ceiling: long enough to absorb a hitch, short enough that a
      // restored tab does not fast-forward the simulation.
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000))
      last = now
      if (!document.hidden) {
        ctx.clearRect(0, 0, width, height)
        drawRef.current(ctx, dt, width, height)
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    const onVisible = () => {
      last = performance.now()
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
