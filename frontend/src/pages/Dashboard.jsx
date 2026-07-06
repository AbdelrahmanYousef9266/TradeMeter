import { useEffect } from 'react'
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
import { logout as apiLogout } from '../services/api'

const MODEL_ORDER = [
  'scalper', 'momentum', 'mean_reversion', 'breakout',
  'conservative', 'aggressive', 'volume', 'contrarian', 'personal', 'lstm',
]

function NTStatusBadge() {
  const ntConnected = useStore(s => s.ntConnected)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%',
        background: ntConnected ? 'var(--text-success)' : 'var(--text-danger)',
        animation: ntConnected ? 'none' : 'pulse-dot 1.6s ease-in-out infinite',
        display: 'inline-block',
      }} />
      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
        {ntConnected ? 'NT Live' : 'Disconnected'}
      </span>
    </div>
  )
}

export default function Dashboard() {
  // The live WebSocket is owned by AuthenticatedLayout (App.jsx) so it persists
  // across page navigation. Dashboard only pulls the initial prediction snapshot.
  usePredictions()

  const navigate = useNavigate()
  const { modelSignals, modelLevels, barHistory, user } = useStore()

  useEffect(() => {
    if (user && !user.nt_connected) {
      navigate('/connect', { replace: true })
    }
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
          <NTStatusBadge />
          <Link to="/champion-challenger" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            ⚔️ C/C
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
