/**
 * Panels Rau has made and put on his wall.
 *
 * This is only the index — titles, kinds, ids. The documents themselves are
 * never held here and never touch this app's DOM: they are fetched by the
 * browser into a sandboxed frame, from `/api/panels/:id`. See
 * `rau/face/panels.py` for why that frame is safe to open.
 */

export type PanelKind = 'report' | 'poster' | 'dashboard' | 'note'

export type PanelSummary = {
  panel_id: string
  title: string
  kind: string
  created: number
}

/** The wall only holds so many before the oldest come down. */
const MAX_ON_WALL = 6

type Listener = () => void

export class PanelStore {
  private panels: PanelSummary[] = []
  private listeners = new Set<Listener>()
  /** The one currently open full-screen, if any. */
  private open: string | null = null

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  private notify() {
    for (const fn of [...this.listeners]) {
      try {
        fn()
      } catch {
        /* one bad view must not stop the rest updating */
      }
    }
  }

  /** Newest first. */
  list(): PanelSummary[] {
    return this.panels
  }

  get openPanel(): string | null {
    return this.open
  }

  add(panel: PanelSummary) {
    if (!panel.panel_id) return
    if (this.panels.some((p) => p.panel_id === panel.panel_id)) return
    this.panels = [panel, ...this.panels].slice(0, MAX_ON_WALL)
    this.notify()
  }

  replaceAll(panels: PanelSummary[]) {
    this.panels = panels.slice(0, MAX_ON_WALL)
    this.notify()
  }

  clear() {
    if (!this.panels.length && !this.open) return
    this.panels = []
    this.open = null
    this.notify()
  }

  show(panelId: string | null) {
    if (this.open === panelId) return
    this.open = panelId
    this.notify()
  }

  /** The newest panel, which is the one drawn largest on the wall. */
  newest(): PanelSummary | null {
    return this.panels[0] ?? null
  }
}

export const panelStore = new PanelStore()

/** Where the browser fetches a panel document from. */
export function panelUrl(panelId: string): string {
  return `/api/panels/${encodeURIComponent(panelId)}`
}
