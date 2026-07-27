import { Suspense, useEffect, useState } from 'react'
import { api } from './api'
import { ModeProvider, useMode } from './mode'
import { useGlobalHotkey } from './hooks/useGlobalHotkey'
import { Link, Navigate, useLocation } from './router'
import { live } from './live'
import PageSkeleton from './components/PageSkeleton'
import {
  Conversation,
  Dashboard,
  Face,
  Identity,
  Operations,
  Pet,
  Settings,
  Setup,
  normalizePath,
} from './routes'

const NAV = [
  { to: '/', label: 'Talk' },
  { to: '/face', label: 'Face' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/operations', label: 'Operations' },
  { to: '/identity', label: 'Identity' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  return (
    <ModeProvider>
      <Shell />
    </ModeProvider>
  )
}

function Shell() {
  const [ready, setReady] = useState<boolean | null>(null)
  const loc = useLocation()
  const isTalk = loc.pathname === '/'
  const isSetup = loc.pathname.startsWith('/setup')
  const isFace = loc.pathname.startsWith('/face')
  const isPet = loc.pathname.startsWith('/pet')
  const { toggleMode } = useMode()

  // Chat/voice is a whole-app switch, so it stays reachable mid-sentence in the
  // composer — hence the intercept, which also eats the space that would land.
  useGlobalHotkey('shift+space', toggleMode, { allowInInput: true, preventDefault: true })

  useEffect(() => {
    api
      .identity()
      .then((d) => setReady(!!d.ready))
      // A hub blip must not throw a configured app back into the setup
      // wizard — only fail closed when we never knew better.
      .catch(() => setReady((r) => (r === null ? false : r)))
  }, [loc.pathname])

  useEffect(() => {
    api.resourceProfile().then((profile) => {
      document.documentElement.dataset.resourceProfile = profile.name || 'balanced'
    }).catch(() => {
      document.documentElement.dataset.resourceProfile = 'balanced'
    })
    live.start()
  }, [])

  if (ready === null) {
    return (
      <div className="boot">
        <div className="boot-inner">
          <span className="boot-word">Rau</span>
          <span className="boot-bar">
            <i />
          </span>
          <span className="muted">waking up</span>
        </div>
      </div>
    )
  }

  if (!ready && !isSetup && !isPet) {
    return <Navigate to="/setup" replace />
  }

  // The room owns the whole viewport — no shell chrome around it.
  if (isFace) {
    return (
      <Suspense fallback={<PageSkeleton pathname="/face" />}>
        <Face />
      </Suspense>
    )
  }

  // Desktop pet: transparent shell, no app chrome.
  if (isPet) {
    return (
      <Suspense fallback={null}>
        <Pet />
      </Suspense>
    )
  }

  return (
    <div className={`app-shell ${isTalk ? 'talk-mode' : ''}`}>
      {!isTalk && !isSetup && (
        <header className="topbar utility-bar">
          <Link to="/" className="brand">
            <i className="brand-dot" />
            Rau
          </Link>
          <nav className="nav">
            {NAV.map((n) => (
              <Link key={n.to} to={n.to} className={loc.pathname === n.to ? 'active' : ''}>
                <span>{n.label}</span>
              </Link>
            ))}
          </nav>
        </header>
      )}

      <main className={`main ${isTalk ? 'main-talk' : ''}`}>
        {/* keyed on path so each route replays its entrance */}
        <div key={loc.pathname} className={isSetup ? undefined : 'route-fade'}>
          {/* The fallback keeps the shell — topbar, nav, page frame — and only
              stands in for the route's own body, so a chunk fetch never wipes
              the chrome the user is already looking at. */}
          <Suspense fallback={<PageSkeleton pathname={loc.pathname} />}>
            <RoutePage pathname={loc.pathname} onSetupDone={() => setReady(true)} />
          </Suspense>
        </div>
      </main>

      {isTalk && ready && (
        <Link to="/dashboard" className="dash-corner" title="Dashboard" aria-label="Open dashboard">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
            <rect x="1.5" y="1.5" width="5" height="5" rx="1.2" />
            <rect x="9.5" y="1.5" width="5" height="5" rx="1.2" />
            <rect x="1.5" y="9.5" width="5" height="5" rx="1.2" />
            <rect x="9.5" y="9.5" width="5" height="5" rx="1.2" />
          </svg>
        </Link>
      )}
    </div>
  )
}

function RoutePage({
  pathname,
  onSetupDone,
}: {
  pathname: string
  onSetupDone: () => void
}) {
  const path = normalizePath(pathname)
  switch (path) {
    case '/':
      return <Conversation />
    case '/face':
      return <Face />
    case '/pet':
      return <Pet />
    case '/dashboard':
      return <Dashboard />
    case '/operations':
      return <Operations />
    case '/setup':
      return <Setup onDone={onSetupDone} />
    case '/identity':
      return <Identity />
    case '/settings':
      return <Settings />
    default:
      return null
  }
}
