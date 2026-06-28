import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import NTConnectFlow from '../components/auth/NTConnectFlow'
import { getNTToken, getNTStatus } from '../services/api'

export default function Connect() {
  const navigate = useNavigate()
  const [token, setToken]       = useState(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    getNTToken()
      .then(res => setToken(res.data.token || res.data.prefix))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Poll /auth/nt-status every 3 seconds
  useEffect(() => {
    const poll = () => {
      getNTStatus()
        .then(res => setConnected(res.data.connected ?? false))
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  if (loading) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--text-secondary)' }}>Loading...</span>
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '32px 16px',
    }}>
      <div style={{ marginBottom: 32, textAlign: 'center' }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, marginBottom: 6 }}>Connect NinjaTrader</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
          One-time setup to stream live market data
        </p>
      </div>

      <NTConnectFlow
        token={token}
        connected={connected}
        onContinue={() => navigate('/dashboard')}
      />
    </div>
  )
}
