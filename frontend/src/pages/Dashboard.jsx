import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { usePredictions } from '../hooks/usePredictions'
import Leaderboard   from '../components/dashboard/Leaderboard'
import ModelCard      from '../components/dashboard/ModelCard'
import LSTMCard       from '../components/dashboard/LSTMCard'
import TrainingMode   from '../components/dashboard/TrainingMode'
import IngestionControl from '../components/dashboard/IngestionControl'
import TradeSignalPanel from '../components/dashboard/TradeSignalPanel'
import LevelUpToast    from '../components/dashboard/LevelUpToast'
import LiveChart      from '../components/chart/LiveChart'
import useStore, { modelKey } from '../store'
import { logout as apiLogout, getNTStatus, getMe } from '../services/api'

// The 9 online personality models run on BOTH timeframes; lstm is 5-min only.
const ONLINE_MODELS = [
  'scalper', 'momentum', 'mean_reversion', 'breakout',
  'conservative', 'aggressive', 'volume', 'contrarian', 'personal',
]

// Model groups per timeframe. 5-min is the primary (trading) series → shown first;
// 1-min is context. 10 (5-min incl. lstm) + 9 (1-min) = 19 competitors.
const MODEL_GROUPS = [
  { timeframe: '5min', label: '5-Minute · Primary (trading timeframe)', accent: '#1D9E75',
    models: [...ONLINE_MODELS, 'lstm'] },
  { timeframe: '1min', label: '1-Minute · Context', accent: '#7F77DD',
    models: [...ONLINE_MODELS] },
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
          <Link to="/stream/afk" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            📺 Stream
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

      {/* Ingestion arm gate — decides when strategy bars enter the pipeline */}
      <IngestionControl />

      {/* Training Mode control + banner */}
      <TrainingMode />

      {/* One clear, actionable trade plan from the leading model */}
      <div style={{ marginBottom: 12 }}>
        <TradeSignalPanel />
      </div>

      {/* Chart timeframe toggle + live chart */}
      <ChartTimeframeToggle />
      <LiveChart bars={barHistory} style={{ marginBottom: 12 }} />

      {/* Leaderboard (all 19 models, both timeframes, tagged) */}
      <Leaderboard style={{ marginBottom: 12 }} />

      {/* Model grid — grouped by timeframe, 5-min primary first */}
      {MODEL_GROUPS.map(group => (
        <div key={group.timeframe} style={{ marginBottom: 16 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, margin: '4px 2px 10px',
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%', background: group.accent, flexShrink: 0,
            }} />
            <span style={{
              fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)',
              textTransform: 'uppercase', letterSpacing: '0.06em',
            }}>{group.label}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
            {group.models.map(name => (
              name === 'lstm' ? (
                <LSTMCard
                  key={modelKey(name, group.timeframe)}
                  signal={modelSignals[modelKey(name, group.timeframe)]}
                  levelInfo={modelLevels[modelKey(name, group.timeframe)]}
                />
              ) : (
                <ModelCard key={modelKey(name, group.timeframe)}
                           modelName={name} timeframe={group.timeframe} />
              )
            ))}
          </div>
        </div>
      ))}

      {/* Single coalescing level-up / CC-promotion toast — fixed bottom-right */}
      <LevelUpToast />
    </div>
  )
}

// Chart timeframe selector — the chart renders one series at a time (both stream).
function ChartTimeframeToggle() {
  const chartTimeframe    = useStore(s => s.chartTimeframe)
  const setChartTimeframe = useStore(s => s.setChartTimeframe)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: '0.04em' }}>
        Chart timeframe
      </span>
      <div style={{ display: 'flex', gap: 2, background: 'var(--surface-3)', borderRadius: 7, padding: 2 }}>
        {[['5min', '5m'], ['1min', '1m']].map(([tf, label]) => (
          <button
            key={tf}
            onClick={() => chartTimeframe !== tf && setChartTimeframe(tf)}
            style={{
              padding: '3px 12px', borderRadius: 5, fontSize: 11, border: 'none', cursor: 'pointer',
              background: chartTimeframe === tf ? 'var(--accent)' : 'transparent',
              color:      chartTimeframe === tf ? '#fff' : 'var(--text-secondary)',
              fontWeight: chartTimeframe === tf ? 500 : 400,
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
