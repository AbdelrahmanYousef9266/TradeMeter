import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import useStore from './store'
import api from './services/api'
import Login                from './pages/Login'
import Connect              from './pages/Connect'
import Dashboard            from './pages/Dashboard'
import Settings             from './pages/Settings'
import ModelSettings        from './pages/ModelSettings'
import ChampionChallenger   from './pages/ChampionChallenger'

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
    </BrowserRouter>
  )
}

export default App
