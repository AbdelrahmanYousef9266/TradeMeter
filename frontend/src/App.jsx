import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import useStore from './store'
import { getMe } from './services/api'
import Login        from './pages/Login'
import Connect      from './pages/Connect'
import Dashboard    from './pages/Dashboard'
import Settings     from './pages/Settings'
import ModelSettings from './pages/ModelSettings'

function App() {
  const { user, setUser } = useStore()
  const [authChecked, setAuthChecked] = useState(false)

  useEffect(() => {
    getMe()
      .then(res => setUser(res.data))
      .catch(() => {})
      .finally(() => setAuthChecked(true))
  }, [])

  if (!authChecked) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Loading...</span>
      </div>
    )
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route path="/connect" element={
          user ? <Connect /> : <Navigate to="/login" replace />
        } />

        <Route path="/dashboard" element={
          user ? <Dashboard /> : <Navigate to="/login" replace />
        } />

        <Route path="/settings" element={
          user ? <Settings /> : <Navigate to="/login" replace />
        } />

        <Route path="/models/:modelName" element={
          user ? <ModelSettings /> : <Navigate to="/login" replace />
        } />

        <Route path="/" element={
          user ? <Navigate to="/dashboard" replace /> : <Navigate to="/login" replace />
        } />
      </Routes>
    </BrowserRouter>
  )
}

export default App
