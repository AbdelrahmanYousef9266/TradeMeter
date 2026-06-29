import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NTConnectFlow from '../components/auth/NTConnectFlow'
import { getNTToken, getNTStatus, getMe } from '../services/api'
import useStore from '../store'

export default function Connect() {
  const navigate              = useNavigate()
  const setUser               = useStore(s => s.setUser)
  const [tokenData, setTokenData] = useState(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)

  // Fetch (or re-fetch) the NT token once on mount
  useEffect(() => {
    getNTToken()
      .then(res => setTokenData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Poll /auth/nt-status every 3 seconds
  useEffect(() => {
    const poll = () => {
      getNTStatus()
        .then(res => {
          const isConnected = res.data.connected ?? false
          setConnected(isConnected)

          if (isConnected) {
            // Refresh Zustand user so Dashboard sees nt_connected=true
            getMe()
              .then(r => setUser(r.data))
              .catch(() => {})
          }
        })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [setUser])

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
        tokenData={tokenData}
        connected={connected}
        onContinue={() => navigate('/dashboard')}
      />
    </div>
  )
}
