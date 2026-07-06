import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { usePredictions } from '../hooks/usePredictions'
import Leaderboard   from '../components/dashboard/Leaderboard'
import ModelCard      from '../components/dashboard/ModelCard'
import LSTMCard       from '../components/dashboard/LSTMCard'
import TrainingMode   from '../components/dashboard/TrainingMode'
import TradeSignalPanel from '../components/dashboard/TradeSignalPanel'
import LevelUpToast    from '../components/dashboard/LevelUpToast'
import LiveChart      from '../components/chart/LiveChart'
import useStore       from '../store'
import { logout as apiLogout, getNTStatus, getMe } from '../services/api'

const MODEL_ORDER = [
  'scalper', 'momentum', 'mean_reversion', 'breakout',
  'conservative', 'aggressive', 'volume', 'contrarian', 'personal', 'lstm',
]

// Persistent NT indicator. Polls the REAL NT status (/auth/nt-status) rather than
// the store's ntConnected flag, which the WebSocket flips true on open regardless
// of whether NinjaTrader is actually streaming. When offline it is a one-click
// pill to /connect; connecting there flips it to "NT Live" on the next poll —
// never forced.
function NTStatusPill() {
  const setUser = useStore(s => s.setUser)
  const [connected, setConnected] = useState(null)   // null = unknown (first load)

  useEffect(() => {
    let active = true
    const poll = () => getNTStatus()
      .then(res => {
        if (!active) return
        const isConn = res.data?.connected ?? false
        setConnected(prev => {
          // On a fresh connect, refresh the store user so it reflects nt_connected.
          if (isConn && prev === false) getMe().then(r => setUser(r.data)).catch(() => {})
          return isConn
        })
      })
      .catch(() => {})
    poll()
    const id = setInterval(poll, 10000)
    return () => { active = false; clearInterval(id) }
  }, [setUser])

  if (connected) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--text-success)', display: 'inline-block' }} />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>NT Live</span>
      </div>
    )
  }

  return (
    <Link
      to="/connect"
      title="NinjaTrader is not connected — click to set it up"
      style={{
        display: 'flex', alignItems: 'center', gap: 6, textDecoration: 'none',
        fontSize: 12, color: 'var(--text-secondary)',
        border: '0.5px solid var(--border)', borderRadius: 999, padding: '2px 10px',
      }}
    >
      <span style={{
        width: 7, height: 7, borderRadius: '50%', background: 'var(--text-danger)',
        animation: 'pulse-dot 1.6s ease-in-out infinite', display: 'inline-block',
      }} />
      NT offline · Connect
    </Link>
  )
}

export default function Dashboard() {
  // The live WebSocket is owned by AuthenticatedLayout (App.jsx) so it persists
  // across page navigation. Dashboard only pulls the initial prediction snapshot.
  usePredictions()

  const navigate = useNavigate()
  const { modelSignals, modelLevels, barHistory, user } = useStore()

  // Post-login landing: show the Connect choice screen ONCE per session if NT is
  // not connected. It is a one-shot (sessionStorage) decision, NOT a guard — after
  // this, the dashboard is freely reachable with NT off (the header pill lets you
  // connect later). A connected user is never redirected.
  useEffect(() => {
    if (!user) return
    if (sessionStorage.getItem('tm_login_landing')) return
    sessionStorage.setItem('tm_login_landing', '1')
    if (!user.nt_connected) navigate('/connect', { replace: true })
  }, [user, navigate])

  const handleLogout = async () => {
    await apiLogout().catch(() => {})
    window.location.href = '/login'
  }

  return (
    <div style={{ padding: '14px 16px', maxWidth: 1400, margin: '0 auto' }}>

      {/* Header */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 14, paddingBottom: 12,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <span style={{ fontSize: 16, fontWeight: 500 }}>TradeMeter</span>
        <nav style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <NTStatusPill />
          <Link to="/champion-challenger" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            ⚔️ C/C
          </Link>
          <Link to="/data" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            Data
          </Link>
          <Link to="/settings" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            Settings
          </Link>
          {user?.email && (
            <span
              onClick={handleLogout}
              style={{ fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}
            >
              Sign out
            </span>
          )}
        </nav>
      </header>

      {/* Training Mode control + banner */}
      <TrainingMode />

      {/* One clear, actionable trade plan from the leading model */}
      <div style={{ marginBottom: 12 }}>
        <TradeSignalPanel />
      </div>

      {/* Live chart */}
      <LiveChart bars={barHistory} style={{ marginBottom: 12 }} />

      {/* Leaderboard */}
      <Leaderboard style={{ marginBottom: 12 }} />

      {/* 3-column model grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 10,
      }}>
        {MODEL_ORDER.map(name => (
          name === 'lstm' ? (
            <LSTMCard
              key={name}
              signal={modelSignals[name]}
              levelInfo={modelLevels[name]}
            />
          ) : (
            <ModelCard key={name} modelName={name} />
          )
        ))}
      </div>

      {/* Single coalescing level-up / CC-promotion toast — fixed bottom-right */}
      <LevelUpToast />
    </div>
  )
}
