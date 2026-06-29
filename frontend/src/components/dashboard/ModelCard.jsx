import { useRef, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

const RANK_COLORS = {
  Rookie: '#6b7280', Apprentice: '#185FA5', Pro: '#0F6E56',
  Elite: '#534AB7', Expert: '#854F0B', Master: '#993C1D',
}

const MODEL_META = {
  scalper:        { label: 'Scalper',         style: 'Ultra short-term' },
  momentum:       { label: 'Momentum',        style: 'Trend follower'   },
  mean_reversion: { label: 'Mean Reversion',  style: 'Fades extremes'   },
  breakout:       { label: 'Breakout Hunter', style: 'Breakout entries' },
  conservative:   { label: 'Conservative',    style: 'Low risk'         },
  aggressive:     { label: 'Aggressive',      style: 'High risk'        },
  volume:         { label: 'Volume',          style: 'Order flow'       },
  contrarian:     { label: 'Contrarian',      style: 'Bets against crowd'},
  personal:       { label: 'You',             style: 'Hybrid · Model 9' },
}

const SIGNAL_COLORS = {
  BUY:  { text: 'var(--text-success)', bg: 'var(--bg-success)' },
  SELL: { text: 'var(--text-danger)',  bg: 'var(--bg-danger)'  },
  HOLD: { text: 'var(--text-warning)', bg: 'var(--bg-warning)' },
}

function XpBar({ pct, color }) {
  return (
    <div style={{ height: 4, background: 'var(--surface-3)', borderRadius: 2, overflow: 'hidden', flex: 1 }}>
      <div style={{
        height: '100%', width: `${Math.min((pct ?? 0) * 100, 100)}%`,
        background: color, borderRadius: 2,
        transition: 'width 0.5s ease',
      }} />
    </div>
  )
}

export default function ModelCard({ modelName, signal, levelInfo }) {
  const meta      = MODEL_META[modelName] || { label: modelName, style: '' }
  const rank      = levelInfo?.rank || 'Rookie'
  const rankColor = RANK_COLORS[rank] || RANK_COLORS.Rookie
  const isPersonal = modelName === 'personal'
  const sigData   = signal ? SIGNAL_COLORS[signal.signal] || SIGNAL_COLORS.HOLD : null
  const streak    = levelInfo?.streak ?? 0

  // Flash border on new signal
  const prevSignalRef = useRef(null)
  const [flashing, setFlashing] = useState(false)
  useEffect(() => {
    if (signal?.signal && signal.signal !== prevSignalRef.current) {
      prevSignalRef.current = signal.signal
      setFlashing(true)
      const t = setTimeout(() => setFlashing(false), 700)
      return () => clearTimeout(t)
    }
  }, [signal?.signal])

  return (
    <div
      id={`model-card-${modelName}`}
      style={{
        background: 'var(--surface-2)',
        border: `0.5px solid ${flashing ? 'var(--accent)' : isPersonal ? `${rankColor}55` : 'var(--border)'}`,
        borderRadius: 12,
        padding: '12px 14px',
        display: 'flex', flexDirection: 'column', gap: 10,
        transition: 'border-color 0.3s',
        boxShadow: flashing ? '0 0 0 1.5px var(--accent)' : 'none',
      }}
    >
      {/* Row 1: name + rank badge */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Avatar */}
          <div style={{
            width: 28, height: 28, borderRadius: 7, flexShrink: 0,
            background: `${rankColor}22`, border: `1px solid ${rankColor}44`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 500, color: rankColor,
          }}>
            {meta.label[0]}
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>
              {meta.label}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{meta.style}</div>
          </div>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 500, padding: '2px 7px', borderRadius: 5,
          background: `${rankColor}22`, color: rankColor, flexShrink: 0,
        }}>
          {rank}
        </span>
      </div>

      {/* Row 2: signal + level progress */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {sigData ? (
          <span style={{
            fontSize: 12, fontWeight: 500, padding: '3px 9px', borderRadius: 6,
            background: sigData.bg, color: sigData.text, flexShrink: 0,
          }}>
            {signal.signal} {Math.round((signal.confidence ?? 0) * 100)}%
          </span>
        ) : (
          <span style={{
            fontSize: 12, padding: '3px 9px', borderRadius: 6,
            background: 'var(--surface-3)', color: 'var(--text-secondary)', flexShrink: 0,
          }}>
            —
          </span>
        )}

        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text-secondary)', flexShrink: 0 }}>
            Lv {levelInfo?.level ?? 1}
          </span>
          <XpBar pct={levelInfo?.xp_progress_pct} color={rankColor} />
          <span style={{ fontSize: 10, color: 'var(--text-secondary)', flexShrink: 0 }}>
            {Math.round((levelInfo?.xp_progress_pct ?? 0) * 100)}%
          </span>
        </div>
      </div>

      {/* Row 3: metrics */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 4, paddingTop: 8,
        borderTop: '1px solid var(--border-subtle)',
      }}>
        {[
          { label: 'Target',  value: signal?.predicted_high ? signal.predicted_high.toFixed(1) : '—' },
          { label: 'Dir↑',    value: signal?.direction_up   ? `${Math.round(signal.direction_up * 100)}%` : '—' },
          {
            label: 'Streak',
            value: streak > 0 ? `${streak > 4 ? '🔥' : ''}${streak}` : '0',
            color: streak >= 5 ? 'var(--text-success)' : undefined,
          },
          { label: 'Bars',    value: levelInfo?.bars_learned ?? '—' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 2 }}>{label}</div>
            <div style={{ fontSize: 12, color: color || 'var(--text-primary)' }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Row 4: tune link + CC indicator */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        paddingTop: 6, borderTop: '1px solid var(--border-subtle)',
      }}>
        <Link
          to={`/models/${modelName}`}
          style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--accent)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
        >
          Tune behavior ↗
        </Link>
        {!isPersonal && (
          <Link
            to="/champion-challenger"
            style={{ fontSize: 10, color: 'var(--text-tertiary)', opacity: 0.7 }}
            title="View Champion/Challenger status"
          >
            ⚔️ C/C
          </Link>
        )}
      </div>
    </div>
  )
}
