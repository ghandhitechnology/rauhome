/**
 * Bridge between the /pet web view and the Tauri desktop shell.
 *
 * When not running inside Tauri, every call is a no-op so the page still works
 * in a normal browser tab for debugging.
 */

export type PetHitRect = { x: number; y: number; w: number; h: number }

type TauriWindow = {
  __TAURI__?: {
    event?: { emit: (event: string, payload?: unknown) => Promise<void> }
    core?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> }
  }
  __TAURI_INTERNALS__?: {
    invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>
  }
}

function tauri(): TauriWindow['__TAURI__'] | null {
  if (typeof window === 'undefined') return null
  return (window as TauriWindow).__TAURI__ ?? null
}

function invoke(cmd: string, args?: Record<string, unknown>): Promise<unknown> {
  const t = tauri()
  if (t?.core?.invoke) return t.core.invoke(cmd, args)
  const internals = (window as TauriWindow).__TAURI_INTERNALS__
  if (internals?.invoke) return internals.invoke(cmd, args)
  return Promise.resolve(undefined)
}

export function isPetShell(): boolean {
  return !!tauri() || !!(window as TauriWindow).__TAURI_INTERNALS__
}

/** Report the interactive hit box (body ∪ bubble) in window CSS pixels. */
export function reportHitRect(rect: PetHitRect): void {
  const padded = {
    x: Math.floor(rect.x - 6),
    y: Math.floor(rect.y - 6),
    w: Math.ceil(rect.w + 12),
    h: Math.ceil(rect.h + 12),
  }
  void invoke('pet_set_hit_rect', { rect: padded })
  const t = tauri()
  if (t?.event?.emit) void t.event.emit('pet://hit-rect', padded)
}

export function petHide(): Promise<unknown> {
  return invoke('pet_hide')
}

export function petShow(): Promise<unknown> {
  return invoke('pet_show')
}

export function petQuit(): Promise<unknown> {
  return invoke('pet_quit')
}

export function petMoveCorner(
  corner: 'tl' | 'tr' | 'bl' | 'br',
): Promise<unknown> {
  return invoke('pet_move_corner', { corner })
}

export function petSetVisible(visible: boolean): Promise<unknown> {
  return invoke('pet_set_visible', { visible })
}

/** Begin dragging the native pet window (primary button on body). */
export function petStartDrag(): Promise<unknown> {
  return invoke('pet_start_drag')
}
