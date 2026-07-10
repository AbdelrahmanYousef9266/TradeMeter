import { useState } from 'react'
import useStore from '../../store'

const MODEL_LABELS = {
  scalper:        'Scalper',
  momentum:       'Momentum',
  mean_reversion: 'Mean Rev',
  breakout:       'Breakout',
  conservative:   'Conserv.',
  aggressive:     'Aggressive',
  volume:         'Volume',
  contrarian:     'Contrarian',
  personal:       'Secret',
}

const RANK_COLORS = {
  Rookie:     '#6b7280',
  Apprentice: '#185FA5',
  Pro:        '#0F6E56',
  Elite:      '#534AB7',
  Expert:     '#854F0B',
  Master:     '#993C1D',
}

const MEDALS = ['🥇', '🥈', '🥉']

const TF_META = {
  '5min': { label: '5m', color: '#1D9E75' },
  '1min': { label: '1m', color: '#7F77DD' },
}

// Store maps are keyed by the composite id "name:timeframe" (Phase 2).
function splitKey(key) {
  const idx = key.lastIndexOf(':')
  return idx === -1 ? [key, '5min'] : [key.slice(0, idx), key.slice(idx + 1)]
}

export default function Leaderboard({ style = {} }) {
  const [mode, setMode] = useState('levels')
  const { modelSignals, modelLevels } = useStore()

  // Levels ranking — all 19 models across both timeframes, tagged.
  const levelRanking = Object.entries(modelLevels)
    .map(([key, info]) => {
      const [name, tf] = splitKey(key)
      return {
        id:     key,
        name,
        timeframe: tf,
        label:  MODEL_LABELS[name] || name,
        level:  info?.level        ?? 1,
        rank:   info?.rank         ?? 'Rookie',
        xp:     info?.xp           ?? 0,
        xpPct:  info?.xp_progress_pct ?? 0,
      }
    })
    .sort((a, b) => b.level - a.level || b.xp - a.xp)

  // P&L / accuracy ranking — built from live signals across both timeframes.
  const pnlRanking = Object.entries(modelSignals)
    .map(([key, sig]) => {
      const [name, tf] = splitKey(key)
      return {
        id:         key,
        name,
        timeframe:  tf,
        label:      MODEL_LABELS[name] || name,
        signal:     sig?.signal     ?? 'HOLD',
        confidence: sig?.confidence ?? 0,
      }
    })
    .sort((a, b) => b.confidence - a.confidence)

  const ranking = mode === 'levels' ? levelRanking : pnlRanking
  const hasData  = ranking.length > 0

  return (
    <div style={{
      background: 'var(--surface-2)', border: '0.5px solid var(--border)',
      borderRadius: 12, padding: '10px 14px',
      ...style,
    }}>
      {/* Header + tab toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Leaderboard
        </span>
        <div style={{ display: 'flex', gap: 2, background: 'var(--surface-3)', borderRadius: 7, padding: 2 }}>
          {[['levels', 'Levels'], ['pnl', 'Accuracy']].map(([m, label]) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                padding: '3px 10px', borderRadius: 5, fontSize: 11,
                background: mode === m ? 'var(--accent)' : 'transparent',
                color:      mode === m ? '#fff' : 'var(--text-secondary)',
                fontWeight: mode === m ? 500 : 400,
                border: 'none', cursor: 'pointer',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {!hasData ? (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)', textAlign: 'center', padding: '6px 0', margin: 0 }}>
          {mode === 'levels' ? 'Loading level data…' : 'Waiting for predictions…'}
        </p>
      ) : (
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4, scrollbarWidth: 'thin' }}>
          {ranking.map((item, i) => {
            const rankColor = RANK_COLORS[item.rank] || RANK_COLORS.Rookie
            const tf = TF_META[item.timeframe] || TF_META['5min']
            return (
              <div
                key={item.id}
                onClick={() => {
                  document.getElementById(`model-card-${item.id}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                }}
                style={{
                  flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8,
                  padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
                  background: 'var(--surface-3)', border: '0.5px solid var(--border)',
                  minWidth: 140, transition: 'border-color 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent)'}
                onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
              >
                <span style={{ fontSize: 13 }}>{MEDALS[i] || `#${i + 1}`}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    whiteSpace: 'nowrap', overflow: 'hidden',
                  }}>
                    <span style={{
                      fontSize: 11, fontWeight: 500, color: 'var(--text-primary)',
                      overflow: 'hidden', textOverflow: 'ellipsis',
                    }}>{item.label}</span>
                    <span style={{
                      fontSize: 9, fontWeight: 700, padding: '0 4px', borderRadius: 3,
                      background: `${tf.color}22`, color: tf.color, flexShrink: 0,
                    }}>{tf.label}</span>
                  </div>
                  {mode === 'levels' ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ fontSize: 11, color: 'var(--text-primary)' }}>
                        Lv {item.level}
                      </span>
                      <span style={{
                        fontSize: 10, padding: '0 5px', borderRadius: 4,
                        background: `${rankColor}22`, color: rankColor,
                      }}>
                        {item.rank}
                      </span>
                    </div>
                  ) : (
                    <div style={{ fontSize: 11, color: item.confidence >= 0.65 ? 'var(--text-success)' : 'var(--text-secondary)' }}>
                      {Math.round(item.confidence * 100)}% conf
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
