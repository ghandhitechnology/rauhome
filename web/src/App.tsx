import { Navigate, Route, Routes, useLocation, Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from './api'
import { ModeProvider, useMode } from './mode'
import { useGlobalHotkey } from './hooks/useGlobalHotkey'
import Setup from './pages/Setup'
import Conversation from './pages/Conversation'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Identity from './pages/Identity'
import Face from './pages/Face'

const NAV = [
  { to: '/', label: 'Talk' },
  { to: '/face', label: 'Face' },
  { to: '/dashboard', label: 'Dashboard' },
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
  const { toggleMode } = useMode()

  // Chat/voice is a whole-app switch, so it stays reachable mid-sentence in the
  // composer — hence the intercept, which also eats the space that would land.
  useGlobalHotkey('shift+space', toggleMode, { allowInInput: true, preventDefault: true })

  useEffect(() => {
    api
      .identity()
      .then((d) => setReady(!!d.ready))
      .catch(() => setReady(false))
  }, [loc.pathname])

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

  if (!ready && !isSetup) {
    return <Navigate to="/setup" replace />
  }

  // The room owns the whole viewport — no shell chrome around it.
  if (isFace) {
    return <Face />
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
          <Routes location={loc}>
            <Route path="/" element={<Conversation />} />
            <Route path="/face" element={<Face />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/setup" element={<Setup onDone={() => setReady(true)} />} />
            <Route path="/identity" element={<Identity />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
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
