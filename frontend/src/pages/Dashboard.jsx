import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { usePredictions } from '../hooks/usePredictions'
import Leaderboard   from '../components/dashboard/Leaderboard'
import ModelCard      from '../components/dashboard/ModelCard'
import LSTMCard       from '../components/dashboard/LSTMCard'
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

function LevelUpToast({ event, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000)
    return () => clearTimeout(t)
  }, [onDismiss])

  // CC Promotion toast
  if (event.display_type === 'cc_promotion') {
    const didPromote = event.winner === 'challenger'
    return (
      <div
        onClick={onDismiss}
        style={{
          background: 'var(--surface-2)',
          border: '1px solid #534AB755',
          borderLeft: '3px solid #534AB7',
          borderRadius: 10,
          padding: '10px 14px',
          minWidth: 260,
          cursor: 'pointer',
          animation: 'slide-in 0.25s ease-out',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
          <span style={{ fontSize: 14 }}>{didPromote ? '⚔️' : '🏆'}</span>
          <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
            {event.model_name.replace(/_/g, ' ')}
            {didPromote ? ' — Challenger promoted!' : ' — Champion retained'}
          </span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Champion {event.champion_pnl >= 0 ? '+' : ''}{event.champion_pnl} pts
          {' vs '}
          Challenger {event.challenger_pnl >= 0 ? '+' : ''}{event.challenger_pnl} pts
        </div>
      </div>
    )
  }

  // Level-up toast (default)
  const RANK_COLORS = {
    Rookie: '#6b7280', Apprentice: '#185FA5', Pro: '#0F6E56',
    Elite: '#534AB7', Expert: '#854F0B', Master: '#993C1D',
  }
  const rankColor = RANK_COLORS[event.new_rank] || '#6b7280'

  return (
    <div
      onClick={onDismiss}
      style={{
        background: 'var(--surface-2)',
        border: `1px solid ${rankColor}55`,
        borderLeft: `3px solid ${rankColor}`,
        borderRadius: 10,
        padding: '10px 14px',
        minWidth: 260,
        cursor: 'pointer',
        animation: 'slide-in 0.25s ease-out',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
        <span style={{ fontSize: 14 }}>⬆</span>
        <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
          {event.model_name.replace(/_/g, ' ')} reached Level {event.new_level}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 500, padding: '1px 6px', borderRadius: 4,
          background: `${rankColor}22`, color: rankColor,
        }}>
          {event.new_rank}
        </span>
      </div>
      {event.unlocked && (
        <div style={{ fontSize: 12, color: 'var(--text-success)' }}>
          + {event.unlocked} unlocked
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  // The live WebSocket is owned by AuthenticatedLayout (App.jsx) so it persists
  // across page navigation. Dashboard only pulls the initial prediction snapshot.
  usePredictions()

  const navigate = useNavigate()
  const { modelSignals, modelLevels, levelUpQueue, barHistory, dismissLevelUp, user } = useStore()

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

      {/* Level-up toast stack — fixed bottom-right */}
      {levelUpQueue.length > 0 && (
        <div style={{
          position: 'fixed', bottom: 20, right: 20,
          display: 'flex', flexDirection: 'column-reverse', gap: 8,
          zIndex: 1000,
        }}>
          {levelUpQueue.map(event => (
            <LevelUpToast
              key={event.id}
              event={event}
              onDismiss={() => dismissLevelUp(event.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
