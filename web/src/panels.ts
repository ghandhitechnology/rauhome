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
  /**
   * Bumped by every edit. The viewer keys its frame on it, so patching a panel
   * that is currently open reloads the document instead of leaving the old
   * markup on screen.
   */
  revision?: number
  /** h1–h3 text, so the wall can hint at what is inside without opening it. */
  headings?: string[]
}

/**
 * The wall only holds so many before the oldest come down. This matches
 * `MAX_PANELS` in rau/face/panels.py — when it was smaller than the server's,
 * a panel could still be open in the viewer while having fallen off this list,
 * and the header would quietly degrade to "Panel".
 */
const MAX_ON_WALL = 12

type Listener = () => void

export class PanelStore {
  private panels: PanelSummary[] = []
  private listeners = new Set<Listener>()
  /** The one currently open full-screen, if any. */
  private open: string | null = null
  /** Asked to be opened, waiting for someone in the room to see it. */
  private pending: string | null = null

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

  /** An edit landed: same panel, same place on the wall, new contents. */
  update(panel: Partial<PanelSummary> & { panel_id: string }) {
    if (!panel.panel_id) return
    let changed = false
    this.panels = this.panels.map((p) => {
      if (p.panel_id !== panel.panel_id) return p
      changed = true
      return { ...p, ...panel }
    })
    if (changed) this.notify()
  }

  /** One panel taken down, as opposed to the whole wall cleared. */
  remove(panelId: string) {
    if (!this.panels.some((p) => p.panel_id === panelId)) {
      if (this.open !== panelId) return
    }
    this.panels = this.panels.filter((p) => p.panel_id !== panelId)
    if (this.open === panelId) this.open = null
    if (this.pending === panelId) this.pending = null
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
    this.pending = null
    this.notify()
  }

  show(panelId: string | null) {
    if (this.open === panelId) return
    this.open = panelId
    this.notify()
  }

  /**
   * Rau asking for a panel to be opened.
   *
   * Recorded rather than acted on, because only the room honours it — see
   * `Face.tsx`, which consumes this on mount. Anywhere else the request simply
   * waits, so "look at this" becomes something waiting for you in the room
   * rather than a modal thrown over whatever you were doing.
   */
  present(panelId: string) {
    if (!panelId) return
    this.pending = panelId
    this.notify()
  }

  /** Claim a pending present, if there is one. Only the room calls this. */
  takePending(): string | null {
    const next = this.pending
    if (next === null) return null
    this.pending = null
    this.notify()
    return next
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
