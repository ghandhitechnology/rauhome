/* oxlint-disable react/only-export-components -- the provider and its tiny hook API belong together */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { flushSync } from 'react-dom'
import { routeLoader } from './routes'
import {
  centerOf,
  rippleRadius,
  roomTransitionBetween,
  waitForRouteCanvas,
  type RouteTransition,
} from './routeTransition'

type ViewTransitionCapableDocument = Document & {
  startViewTransition?: (
    update: () => void | Promise<void>,
  ) => { finished: Promise<void> }
}

/**
 * How long we will hold the outgoing page on screen waiting for the incoming
 * route's chunk. Under that, the swap is seamless. Over it — a cold cache, a
 * throttled connection — we stop waiting and let `<Suspense>` show the route's
 * skeleton, because a frozen UI is worse than a visible loading state.
 */
const CHUNK_WAIT_MS = 250
const ROOM_FALLBACK_MS = 180

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

function canViewTransition(): boolean {
  return typeof (document as ViewTransitionCapableDocument).startViewTransition === 'function'
}

/** Warm a lazy route for intent signals such as hover or keyboard focus. */
export async function preloadRoute(pathname: string): Promise<void> {
  try {
    await routeLoader(pathname)?.()
  } catch {
    // Navigation still owns the visible loading/error path if preloading fails.
  }
}

/** Resolve once the chunk is warm, or once we have waited long enough. */
function settleRoute(pathname: string): Promise<void> {
  const loader = routeLoader(pathname)
  if (!loader) return Promise.resolve()
  return Promise.race([
    // A chunk that fails to load must not wedge navigation — the route will
    // surface the error itself once React tries to render it.
    loader().then(
      () => undefined,
      () => undefined,
    ),
    new Promise<void>((resolve) => window.setTimeout(resolve, CHUNK_WAIT_MS)),
  ])
}

export type Location = {
  pathname: string
  search: string
  hash: string
}

export type NavigateOptions = {
  replace?: boolean
  transition?: RouteTransition
}

type RouterValue = {
  location: Location
  navigate: (to: string, options?: NavigateOptions) => void
}

const RouterContext = createContext<RouterValue | null>(null)

function readLocation(): Location {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  }
}

function launcherRect(): DOMRect | null {
  return document.querySelector<HTMLElement>('.convo-room-launcher')?.getBoundingClientRect() ?? null
}

function configureRoomTransition(transition: RouteTransition) {
  const root = document.documentElement
  root.dataset.routeTransition = transition.kind
  if (transition.kind !== 'room-open') return
  root.style.setProperty('--room-ripple-x', `${transition.origin.x}px`)
  root.style.setProperty('--room-ripple-y', `${transition.origin.y}px`)
  root.style.setProperty(
    '--room-ripple-radius',
    `${rippleRadius(transition.origin, window.innerWidth, window.innerHeight)}px`,
  )
}

function configureCloseOrigin() {
  const rect = launcherRect()
  if (!rect) return
  const origin = centerOf(rect)
  const root = document.documentElement
  root.style.setProperty('--room-ripple-x', `${origin.x}px`)
  root.style.setProperty('--room-ripple-y', `${origin.y}px`)
  root.style.setProperty(
    '--room-ripple-radius',
    `${rippleRadius(origin, window.innerWidth, window.innerHeight)}px`,
  )
}

function clearRoomTransition(kind: RouteTransition['kind']) {
  const root = document.documentElement
  if (root.dataset.routeTransition !== kind) return
  delete root.dataset.routeTransition
  root.style.removeProperty('--room-ripple-x')
  root.style.removeProperty('--room-ripple-y')
  root.style.removeProperty('--room-ripple-radius')
}

/**
 * The app only needs browser history, links, redirects, and a location value.
 * Keeping that small surface local avoids shipping a data/RSC router for a
 * handful of static SPA routes.
 */
export function BrowserRouter({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState(readLocation)
  const locationRef = useRef(location)
  const fallbackSeq = useRef(0)
  locationRef.current = location
  /**
   * Monotonic navigation counter. A slow chunk load must not let an earlier
   * click commit after a newer one — last-clicked wins, not last-settled.
   */
  const navSeq = useRef(0)

  // Tells the stylesheet to stand down `.route-fade`, so a route never plays a
  // cross-fade and a slide-up at the same time. Set from JS rather than hard-
  // coded in the CSS because it is a browser capability, not a design choice.
  useEffect(() => {
    if (canViewTransition()) document.documentElement.dataset.viewTransitions = 'on'
  }, [])

  /**
   * Commit a location change, cross-fading if the browser can. `flushSync` is
   * required: `startViewTransition` snapshots the DOM the moment its callback
   * returns, so the update has to be synchronous or it captures the old tree
   * twice and nothing appears to animate.
   */
  const commit = useCallback(
    (apply: () => void, transition?: RouteTransition) => {
      const doc = document as ViewTransitionCapableDocument
      if (!doc.startViewTransition || prefersReducedMotion()) {
        if (!transition) {
          apply()
          return
        }
        const fallback = ++fallbackSeq.current
        document.documentElement.dataset.routeFallback = transition.kind
        apply()
        window.setTimeout(() => {
          if (fallback !== fallbackSeq.current) return
          delete document.documentElement.dataset.routeFallback
        }, ROOM_FALLBACK_MS)
        return
      }
      if (!transition) {
        doc.startViewTransition(() => flushSync(apply))
        return
      }

      configureRoomTransition(transition)
      const canvasReady = waitForRouteCanvas()
      const viewTransition = doc.startViewTransition(async () => {
        flushSync(apply)
        // The reverse ripple ends at the pill's actual incoming position,
        // including responsive and activity-rail layout shifts.
        if (transition.kind === 'room-close') configureCloseOrigin()
        await canvasReady
      })
      void viewTransition.finished
        .catch(() => {
          // A newer navigation can legitimately skip an in-flight transition.
        })
        .finally(() => clearRoomTransition(transition.kind))
    },
    [],
  )

  useEffect(() => {
    const onPopState = () => {
      // Back should feel identical to a click, chunk preload included.
      const target = readLocation()
      const transition = roomTransitionBetween(
        locationRef.current.pathname,
        target.pathname,
        launcherRect(),
      )
      const seq = ++navSeq.current
      void settleRoute(target.pathname).then(() => {
        if (seq !== navSeq.current) return
        commit(() => setLocation(target), transition)
      })
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [commit])

  const navigate = useCallback(
    (to: string, options: NavigateOptions = {}) => {
      const url = new URL(to, window.location.href)
      if (url.origin !== window.location.origin) {
        window.location.assign(url.href)
        return
      }

      const next = `${url.pathname}${url.search}${url.hash}`
      const transition =
        options.transition ??
        roomTransitionBetween(locationRef.current.pathname, url.pathname, launcherRect())
      // The history entry is written inside the transition alongside the render
      // so the address bar and the pixels change together — pushing first would
      // leave the URL pointing at a page not yet on screen for the whole
      // duration of the chunk fetch.
      const seq = ++navSeq.current
      void settleRoute(url.pathname).then(() => {
        // A newer navigation started while this chunk loaded — it wins.
        if (seq !== navSeq.current) return
        commit(
          () => {
            if (options.replace) window.history.replaceState(null, '', next)
            else window.history.pushState(null, '', next)
            setLocation(readLocation())
          },
          transition,
        )
      })
    },
    [commit],
  )

  const value = useMemo(() => ({ location, navigate }), [location, navigate])
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>
}

function useRouter(): RouterValue {
  const value = useContext(RouterContext)
  if (!value) throw new Error('Router hooks must be used inside BrowserRouter')
  return value
}

export function useLocation(): Location {
  return useRouter().location
}

export function useNavigate(): RouterValue['navigate'] {
  return useRouter().navigate
}

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & {
  to: string
  transition?: RouteTransition | ((event: MouseEvent<HTMLAnchorElement>) => RouteTransition)
}

export function Link({
  to,
  onClick,
  target,
  transition,
  children,
  ...props
}: LinkProps) {
  const navigate = useNavigate()

  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (target && target !== '_self') ||
      props.download
    ) {
      return
    }

    const url = new URL(to, window.location.href)
    if (url.origin !== window.location.origin) return
    event.preventDefault()
    navigate(to, {
      transition:
        typeof transition === 'function' ? transition(event) : transition,
    })
  }

  return (
    <a {...props} href={to} target={target} onClick={follow}>
      {children}
    </a>
  )
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const navigate = useNavigate()

  useEffect(() => {
    navigate(to, { replace })
  }, [navigate, replace, to])

  return null
}
