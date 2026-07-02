import { useEffect, useState, Component } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate, Outlet } from 'react-router-dom'
import useStore from './store'
import api from './services/api'
import { useWebSocket } from './hooks/useWebSocket'
import { useHydrate } from './hooks/useHydrate'
import Login                from './pages/Login'
import Connect              from './pages/Connect'
import Dashboard            from './pages/Dashboard'
import StreamDashboard      from './pages/StreamDashboard'
import AfkStream            from './pages/AfkStream'
import Settings             from './pages/Settings'
import ModelSettings        from './pages/ModelSettings'
import ChampionChallenger   from './pages/ChampionChallenger'

class ErrorBoundary extends Component {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary] Uncaught error:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', height: '100vh', gap: 16,
          color: 'var(--text-secondary)', fontFamily: 'monospace',
        }}>
          <div style={{ fontSize: 13 }}>Something went wrong in TradeMeter.</div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)', maxWidth: 400, textAlign: 'center' }}>
            {this.state.error?.message}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              fontSize: 12, padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
            }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function Protected({ children }) {
  const { user, setUser } = useStore()
  const navigate           = useNavigate()
  const [checking, setChecking] = useState(!user)
  const [authed,   setAuthed]   = useState(!!user)

  useEffect(() => {
    if (user) {
      setAuthed(true)
      setChecking(false)
      return
    }
    api.get('/auth/me')
      .then(res => {
        setUser(res.data)
        setAuthed(true)
        setChecking(false)
      })
      .catch(err => {
        console.error('Auth check failed:', err)
        setChecking(false)   // ← was missing; caused the infinite "Loading..."
        navigate('/login', { replace: true })
      })
  }, [])

  if (checking) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Loading...</span>
      </div>
    )
  }

  if (!authed) return null

  return children
}

/**
 * Layout for the whole authenticated area. Mounts ONCE when you enter any
 * protected page and stays mounted as you navigate between child routes
 * (Dashboard ↔ CC ↔ Settings), so the single live WebSocket persists across
 * navigation and only tears down on full logout.
 */
function AuthenticatedLayout() {
  const user = useStore(s => s.user)
  useWebSocket(!!user)   // ONE WebSocket for the entire authenticated area
  useHydrate()           // hydrate warmup/connection + chart history on load
  return <Outlet />      // child routes render here; the WS stays mounted
}

function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Routes>
          {/* Public — no auth check */}
          <Route path="/login" element={<Login />} />

          {/* Protected area — one auth check + one WebSocket shared by all children */}
          <Route element={<Protected><AuthenticatedLayout /></Protected>}>
            <Route path="/connect" element={<Connect />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/stream" element={<StreamDashboard />} />
            <Route path="/stream/afk" element={<AfkStream />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/models/:modelName" element={<ModelSettings />} />
            <Route path="/champion-challenger" element={<ChampionChallenger />} />
          </Route>

          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  )
}

export default App
