import { useState, useEffect } from 'react'
import useStore from '../../store'
import { getLeaderboardPnl, getLeaderboardLvl } from '../../services/api'

const RANK_COLORS = {
  Rookie: '#6b7280', Apprentice: '#185FA5', Pro: '#0F6E56',
  Elite: '#534AB7', Expert: '#854F0B', Master: '#993C1D',
}

const MEDALS = ['🥇', '🥈', '🥉']

export default function Leaderboard({ style = {} }) {
  const [mode, setMode] = useState('pnl')
  const { leaderboardPnl, leaderboardLevels, setLeaderboardPnl, setLeaderboardLevels, modelLevels } = useStore()

  useEffect(() => {
    getLeaderboardPnl()
      .then(res => setLeaderboardPnl(res.data))
      .catch(() => {})

    getLeaderboardLvl()
      .then(res => setLeaderboardLevels(res.data))
      .catch(() => {})
  }, [])

  // Merge WS-live level data into leaderboard entries
  const levelRows = leaderboardLevels.length
    ? leaderboardLevels.map(row => ({
        ...row,
        ...(modelLevels[row.model_name] || {}),
      }))
    : Object.entries(modelLevels).map(([name, info]) => ({
        model_name: name, ...info,
      })).sort((a, b) => (b.level ?? 0) - (a.level ?? 0) || (b.xp ?? 0) - (a.xp ?? 0))

  const rows = mode === 'pnl' ? leaderboardPnl : levelRows

  const fmtName = (n) => n?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  return (
    <div style={{
      background: 'var(--surface-2)', border: '0.5px solid var(--border)',
      borderRadius: 12, padding: '10px 14px',
      ...style,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Leaderboard
        </span>
        <div style={{
          display: 'flex', gap: 2,
          background: 'var(--surface-3)', borderRadius: 7, padding: 2,
        }}>
          {[['pnl', 'Accuracy'], ['levels', 'Levels']].map(([m, label]) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                padding: '3px 10px', borderRadius: 5, fontSize: 11,
                background: mode === m ? 'var(--accent)' : 'transparent',
                color: mode === m ? '#fff' : 'var(--text-secondary)',
                fontWeight: mode === m ? 500 : 400,
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)', textAlign: 'center', padding: '6px 0' }}>
          Waiting for data…
        </p>
      ) : (
        <div style={{
          display: 'flex', gap: 8, overflowX: 'auto',
          paddingBottom: 4, scrollbarWidth: 'thin',
        }}>
          {rows.map((row, i) => {
            const name  = row.model_name
            const rank  = row.rank || modelLevels[name]?.rank || 'Rookie'
            const color = RANK_COLORS[rank] || RANK_COLORS.Rookie

            return (
              <div
                key={name}
                onClick={() => {
                  const el = document.getElementById(`model-card-${name}`)
                  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                }}
                style={{
                  flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8,
                  padding: '6px 12px', borderRadius: 8, cursor: 'pointer',
                  background: 'var(--surface-3)', border: '0.5px solid var(--border)',
                  minWidth: 130,
                  transition: 'border-color 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent)'}
                onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
              >
                <span style={{ fontSize: 13 }}>{MEDALS[i] || `#${i + 1}`}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {fmtName(name)}
                  </div>
                  {mode === 'pnl' ? (
                    <div style={{ fontSize: 11, color: (row.accuracy_today ?? 0) >= 0.5 ? 'var(--text-success)' : 'var(--text-danger)' }}>
                      {row.accuracy_today != null
                        ? `${(row.accuracy_today * 100).toFixed(1)}% acc`
                        : '—'}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ fontSize: 11, color: 'var(--text-primary)' }}>
                        Lv {row.level ?? (modelLevels[name]?.level ?? '—')}
                      </span>
                      <span style={{
                        fontSize: 10, padding: '0 5px', borderRadius: 4,
                        background: `${color}22`, color,
                      }}>
                        {rank}
                      </span>
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
