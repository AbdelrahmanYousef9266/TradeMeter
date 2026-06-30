import { useEffect, useState, Component } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import useStore from './store'
import api from './services/api'
import Login                from './pages/Login'
import Connect              from './pages/Connect'
import Dashboard            from './pages/Dashboard'
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

function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Routes>
          {/* Public — no auth check */}
          <Route path="/login" element={<Login />} />

          {/* Protected routes */}
          <Route path="/connect" element={<Protected><Connect /></Protected>} />
          <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
          <Route path="/settings" element={<Protected><Settings /></Protected>} />
          <Route path="/models/:modelName" element={<Protected><ModelSettings /></Protected>} />
          <Route path="/champion-challenger" element={<Protected><ChampionChallenger /></Protected>} />

          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  )
}

export default App
