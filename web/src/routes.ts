import { lazy } from 'react'

/**
 * Route code-splitting, kept out of `App.tsx` so the router can reach it too.
 *
 * The router preloads a route's chunk *before* it starts a view transition.
 * Without that, the transition snapshots whatever `<Suspense>` is showing and
 * the user watches a polished cross-fade into a loading state — worse than no
 * transition at all. Since `lazy()` memoises its own promise, calling the
 * loader again after the chunk is warm is free.
 */

const load = {
  conversation: () => import('./pages/Conversation'),
  face: () => import('./pages/Face'),
  pet: () => import('./pages/Pet'),
  dashboard: () => import('./pages/Dashboard'),
  operations: () => import('./pages/Operations'),
  setup: () => import('./pages/Setup'),
  identity: () => import('./pages/Identity'),
  settings: () => import('./pages/Settings'),
}

export const Conversation = lazy(load.conversation)
export const Face = lazy(load.face)
export const Pet = lazy(load.pet)
export const Dashboard = lazy(load.dashboard)
export const Operations = lazy(load.operations)
export const Setup = lazy(load.setup)
export const Identity = lazy(load.identity)
export const Settings = lazy(load.settings)

/** Trailing slashes are stripped everywhere so `/settings/` and `/settings` agree. */
export function normalizePath(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
}

const LOADERS: Record<string, () => Promise<unknown>> = {
  '/': load.conversation,
  '/face': load.face,
  '/pet': load.pet,
  '/dashboard': load.dashboard,
  '/operations': load.operations,
  '/setup': load.setup,
  '/identity': load.identity,
  '/settings': load.settings,
}

export function routeLoader(pathname: string): (() => Promise<unknown>) | undefined {
  return LOADERS[normalizePath(pathname)]
}
