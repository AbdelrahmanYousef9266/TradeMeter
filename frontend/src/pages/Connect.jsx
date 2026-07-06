import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NTConnectFlow from '../components/auth/NTConnectFlow'
import { getNTToken, resetNTToken, getNTStatus, getMe } from '../services/api'
import useStore from '../store'

export default function Connect() {
  const navigate              = useNavigate()
  const setUser               = useStore(s => s.setUser)
  const [tokenData, setTokenData] = useState(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [resetting, setResetting] = useState(false)

  // Fetch (or re-fetch) the NT token once on mount
  useEffect(() => {
    getNTToken()
      .then(res => setTokenData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Rotate the token — the response carries the new plaintext ONCE, so we drop
  // it straight into state to show it in full with the copy button.
  const handleReset = () => {
    setResetting(true)
    resetNTToken()
      .then(res => setTokenData(res.data))
      .catch(() => {})
      .finally(() => setResetting(false))
  }

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
      <div style={{ marginBottom: 28, textAlign: 'center' }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, marginBottom: 6 }}>Connect NinjaTrader</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13, maxWidth: 380 }}>
          Optional — stream live market data from NinjaTrader 8. You can also skip
          this and explore the dashboard with your existing data.
        </p>
      </div>

      <NTConnectFlow
        tokenData={tokenData}
        connected={connected}
        resetting={resetting}
        onReset={handleReset}
        onContinue={() => navigate('/dashboard')}
      />

      {/* Skip: NT connection is not required to use the dashboard. */}
      {!connected && (
        <>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12,
            width: '100%', maxWidth: 420, margin: '24px 0 20px',
            color: 'var(--text-tertiary)', fontSize: 12,
          }}>
            <div style={{ flex: 1, height: 1, background: 'var(--border-subtle)' }} />
            or
            <div style={{ flex: 1, height: 1, background: 'var(--border-subtle)' }} />
          </div>

          <button
            onClick={() => navigate('/dashboard')}
            style={{
              display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
              fontSize: 14, fontWeight: 500, padding: '11px 22px', borderRadius: 10,
              background: 'var(--surface-2)', color: 'var(--text-primary)',
              border: '0.5px solid var(--border)',
            }}
          >
            Go to Dashboard →
          </button>
          <p style={{ marginTop: 10, fontSize: 11, color: 'var(--text-tertiary)', textAlign: 'center', maxWidth: 340 }}>
            Levels, P&amp;L history, data coverage and LSTM status all work without a
            live connection. Connect anytime from the header.
          </p>
        </>
      )}
    </div>
  )
}
