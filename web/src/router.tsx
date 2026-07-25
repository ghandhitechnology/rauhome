/* oxlint-disable react/only-export-components -- the provider and its tiny hook API belong together */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from 'react'

export type Location = {
  pathname: string
  search: string
  hash: string
}

type NavigateOptions = {
  replace?: boolean
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

/**
 * The app only needs browser history, links, redirects, and a location value.
 * Keeping that small surface local avoids shipping a data/RSC router for a
 * handful of static SPA routes.
 */
export function BrowserRouter({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState(readLocation)

  useEffect(() => {
    const onPopState = () => setLocation(readLocation())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = useCallback((to: string, options: NavigateOptions = {}) => {
    const url = new URL(to, window.location.href)
    if (url.origin !== window.location.origin) {
      window.location.assign(url.href)
      return
    }

    const next = `${url.pathname}${url.search}${url.hash}`
    if (options.replace) window.history.replaceState(null, '', next)
    else window.history.pushState(null, '', next)
    setLocation(readLocation())
  }, [])

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
}

export function Link({ to, onClick, target, children, ...props }: LinkProps) {
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
    navigate(to)
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
