import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getCCStatus, forceEvaluation } from '../services/api'

const MODEL_LABELS = {
  scalper:        'Scalper',
  momentum:       'Momentum',
  mean_reversion: 'Mean Reversion',
  breakout:       'Breakout Hunter',
  conservative:   'Conservative',
  aggressive:     'Aggressive',
  volume:         'Volume',
  contrarian:     'Contrarian',
}

function ParamDiff({ oldParams = {}, newParams = {} }) {
  const changed = Object.keys(newParams).filter(
    k => typeof newParams[k] === 'number' && newParams[k] !== oldParams[k]
  )
  if (!changed.length) return null
  return (
    <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {changed.map(k => (
        <span key={k} style={{
          fontSize: 10, padding: '1px 5px', borderRadius: 4,
          background: 'var(--surface-3)', color: 'var(--text-secondary)',
        }}>
          {k}: {typeof oldParams[k] === 'number' ? oldParams[k].toFixed(3) : oldParams[k]}
          {' → '}
          {typeof newParams[k] === 'number' ? newParams[k].toFixed(3) : newParams[k]}
        </span>
      ))}
    </div>
  )
}

function VersionBlock({ data, color, label }) {
  if (!data) return null
  return (
    <div style={{
      background: 'var(--surface-3)', borderRadius: 8, padding: '8px 10px',
      border: `1px solid ${color}33`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 500, color }}>{label}</span>
        <span style={{ fontSize: 11, color: data.pnl_points >= 0 ? 'var(--text-success)' : 'var(--text-danger)' }}>
          {data.pnl_points >= 0 ? '+' : ''}{data.pnl_points} pts
        </span>
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--text-secondary)' }}>
        <span>Trades: {data.trade_count}</span>
        <span>Win%: {Math.round(data.win_rate * 100)}%</span>
        <span>Bars: {data.bars_evaluated}</span>
      </div>
      <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {Object.entries(data.params || {}).filter(([, v]) => typeof v === 'number').map(([k, v]) => (
          <span key={k} style={{
            fontSize: 10, padding: '1px 5px', borderRadius: 4,
            background: 'var(--surface-2)', color: 'var(--text-tertiary)',
          }}>
            {k}: {v.toFixed ? v.toFixed(3) : v}
          </span>
        ))}
      </div>
    </div>
  )
}

function CCModelCard({ modelName, status, onForceEval }) {
  const label = MODEL_LABELS[modelName] || modelName
  const c     = status?.champion
  const ch    = status?.challenger
  const challengerLeading = ch && c && ch.pnl_points > c.pnl_points
  const barsLeft = status?.bars_until_eval ?? 0
  const total = (c?.pnl_points ?? 0) + Math.abs(ch?.pnl_points ?? 0) || 1
  const champPct = Math.max(0, Math.min(100,
    ((c?.pnl_points ?? 0) / total) * 100
  ))

  return (
    <div style={{
      background: 'var(--surface-2)',
      border: `0.5px solid ${challengerLeading ? '#534AB7' : 'var(--border)'}`,
      borderRadius: 12, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {challengerLeading && (
            <span style={{ fontSize: 10, color: '#534AB7', fontWeight: 500 }}>⚔️ Challenger leading</span>
          )}
          <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
            eval in {barsLeft} bars
          </span>
        </div>
      </div>

      {/* Champion block */}
      <VersionBlock data={c}  color="var(--text-success)" label="🏆 Champion" />

      {/* Progress bar */}
      <div style={{ height: 4, background: 'var(--surface-3)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${champPct}%`,
          background: 'var(--text-success)', borderRadius: 2,
          transition: 'width 0.4s ease',
        }} />
      </div>

      {/* Challenger block */}
      <VersionBlock data={ch} color="#534AB7" label="⚔️ Challenger" />

      {/* Force eval button */}
      <button
        onClick={() => onForceEval(modelName)}
        style={{
          fontSize: 11, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
          background: 'transparent', border: '1px solid var(--border)',
          color: 'var(--text-secondary)', alignSelf: 'flex-end',
        }}
        onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent)'}
        onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
      >
        Force evaluation
      </button>
    </div>
  )
}

function PromotionHistoryItem({ entry, modelName }) {
  const label = MODEL_LABELS[modelName] || modelName
  const didPromote = entry.winner === 'challenger'
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10, padding: '8px 0',
      borderBottom: '1px solid var(--border-subtle)',
    }}>
      <span style={{ fontSize: 13, flexShrink: 0 }}>{didPromote ? '⚔️' : '🏆'}</span>
      <div>
        <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)' }}>
          {label} — {didPromote ? 'Challenger promoted' : 'Champion retained'}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          Champion {entry.champion_pnl >= 0 ? '+' : ''}{entry.champion_pnl} pts
          {' vs '}
          Challenger {entry.challenger_pnl >= 0 ? '+' : ''}{entry.challenger_pnl} pts
          {' · '}{entry.bars_evaluated} bars
        </div>
        <ParamDiff oldParams={entry.old_params} newParams={entry.new_params} />
      </div>
    </div>
  )
}

const MODEL_ORDER = [
  'scalper', 'momentum', 'mean_reversion', 'breakout',
  'conservative', 'aggressive', 'volume', 'contrarian',
]

export default function ChampionChallenger() {
  const [ccStatus, setCcStatus] = useState({})
  const [loading,  setLoading]  = useState(true)
  const [forcing,  setForcing]  = useState(null)

  const fetchStatus = useCallback(() => {
    getCCStatus()
      .then(r => { setCcStatus(r.data || {}); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchStatus()
    const interval = setInterval(fetchStatus, 30_000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  const handleForceEval = async (name) => {
    setForcing(name)
    try {
      await forceEvaluation(name)
      await fetchStatus()
    } finally {
      setForcing(null)
    }
  }

  // Collect all promotion history across all models
  const allPromotions = MODEL_ORDER.flatMap(name =>
    (ccStatus[name]?.promotion_history || []).map(e => ({ ...e, modelName: name }))
  ).sort((a, b) => (b.bars_evaluated || 0) - (a.bars_evaluated || 0))

  return (
    <div style={{ padding: '14px 16px', maxWidth: 1200, margin: '0 auto' }}>
      {/* Header */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20, paddingBottom: 12,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 500 }}>⚔️ Champion / Challenger</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
            Each model runs two versions. Every 100 bars the better P&L wins.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <Link to="/dashboard" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            ← Dashboard
          </Link>
        </div>
      </header>

      {loading ? (
        <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 40, fontSize: 13 }}>
          Loading CC status…
        </div>
      ) : Object.keys(ccStatus).length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 40, fontSize: 13 }}>
          No data yet — CC data appears after the first 50 bars warm up and predictions start.
        </div>
      ) : (
        <>
          {/* 3-column model grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 32 }}>
            {MODEL_ORDER.map(name => (
              <CCModelCard
                key={name}
                modelName={name}
                status={ccStatus[name]}
                onForceEval={forcing ? () => {} : handleForceEval}
              />
            ))}
          </div>

          {/* Promotion history */}
          {allPromotions.length > 0 && (
            <div style={{
              background: 'var(--surface-2)', borderRadius: 12, padding: '14px 16px',
              border: '0.5px solid var(--border)',
            }}>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 12 }}>
                Promotion History
              </div>
              {allPromotions.slice(0, 20).map((entry, i) => (
                <PromotionHistoryItem key={i} entry={entry} modelName={entry.modelName} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
