import { useEffect, useState } from 'react'
import useStore from '../store'
import ArchitectureDiagram from '../components/ArchitectureDiagram'
import LeaderboardRace from '../components/LeaderboardRace'

const MODEL_META = {
  scalper:        { label: 'Scalper',         style: 'Ultra short-term',  color: '#3B82C4' },
  momentum:       { label: 'Momentum',        style: 'Trend follower',    color: '#1D9E75' },
  mean_reversion: { label: 'Mean Reversion',  style: 'Fades extremes',    color: '#D85A30' },
  breakout:       { label: 'Breakout Hunter', style: 'Breakout entries',  color: '#BA7517' },
  conservative:   { label: 'Conservative',    style: 'Low risk',          color: '#639922' },
  aggressive:     { label: 'Aggressive',      style: 'High risk',         color: '#E24B4A' },
  volume:         { label: 'Volume',          style: 'Order flow',        color: '#7F77DD' },
  contrarian:     { label: 'Contrarian',      style: 'Against the crowd', color: '#D4537E' },
  personal:       { label: 'You (Model 9)',   style: 'Hybrid ensemble',   color: '#1D9E75' },
  lstm:           { label: 'Deep LSTM',       style: 'Neural sequences',  color: '#534AB7' },
}

const MODEL_ORDER = [
  'momentum','breakout','volume','scalper','mean_reversion',
  'aggressive','conservative','contrarian','personal','lstm'
]

export default function StreamDashboard() {
  const { modelSignals, modelLevels, modelPnl, currentBar, ntConnected } = useStore()
  const [showArch, setShowArch] = useState(false)
  const [view, setView] = useState('grid')  // 'grid' | 'race' | 'both'

  // Build ranked model list by session P&L (for the leaderboard ordering)
  const ranked = MODEL_ORDER
    .map(name => ({
      name,
      meta: MODEL_META[name],
      signal: modelSignals[name] || {},
      level: modelLevels[name] || {},
      pnl: modelPnl[name] || {},
    }))
    .sort((a, b) => (b.pnl.points ?? 0) - (a.pnl.points ?? 0))

  const totalPnl = ranked.reduce((sum, m) => sum + (m.pnl.points ?? 0), 0)
  const price = currentBar?.close ?? null

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg, #0e0f11)',
      padding: '24px 32px',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      color: 'var(--text-primary)',
    }}>
      {/* ── Top bar ── */}
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        marginBottom:'24px', paddingBottom:'16px',
        borderBottom:'0.5px solid var(--border)'
      }}>
        <div style={{ display:'flex', alignItems:'baseline', gap:'12px' }}>
          <span style={{ fontSize:'22px', fontWeight:600, letterSpacing:'-0.02em' }}>TradeMeter</span>
          <span style={{ fontSize:'13px', color:'var(--text-muted)' }}>Live ML Trading · 11 Models Learning</span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:'20px' }}>
          {price && (
            <div style={{ textAlign:'right' }}>
              <div style={{ fontSize:'11px', color:'var(--text-muted)' }}>MES</div>
              <div style={{ fontSize:'18px', fontWeight:600, fontVariantNumeric:'tabular-nums' }}>
                {price.toFixed(2)}
              </div>
            </div>
          )}
          <div style={{ textAlign:'right' }}>
            <div style={{ fontSize:'11px', color:'var(--text-muted)' }}>Combined P&L</div>
            <div style={{
              fontSize:'18px', fontWeight:600, fontVariantNumeric:'tabular-nums',
              color: totalPnl > 0 ? 'var(--text-success)' : totalPnl < 0 ? 'var(--text-danger)' : 'var(--text-muted)'
            }}>
              {totalPnl > 0 ? '+' : ''}{totalPnl.toFixed(1)} pts
            </div>
          </div>
          <div style={{ display:'flex', gap:'4px', border:'0.5px solid var(--border-strong)', borderRadius:'var(--radius)', overflow:'hidden' }}>
            {[['grid','Grid'],['race','Race'],['both','Both']].map(([v,label]) => (
              <button key={v} onClick={() => setView(v)} style={{
                fontSize:'12px', padding:'6px 12px', border:'none', cursor:'pointer',
                background: view === v ? 'var(--bg-accent, var(--accent-dim))' : 'transparent',
                color: view === v ? 'var(--text-accent, var(--accent))' : 'var(--text-secondary)',
              }}>{label}</button>
            ))}
          </div>
          <button
            onClick={() => setShowArch(!showArch)}
            style={{
              fontSize:'12px', padding:'6px 12px', borderRadius:'var(--radius)',
              background:'transparent', border:'0.5px solid var(--border-strong)',
              color:'var(--text-secondary)', cursor:'pointer'
            }}
          >
            {showArch ? 'Hide' : 'How it works'}
          </button>
          <div style={{
            display:'flex', alignItems:'center', gap:'6px',
            fontSize:'12px', color: ntConnected ? 'var(--text-success)' : 'var(--text-muted)'
          }}>
            <span style={{
              width:'8px', height:'8px', borderRadius:'50%',
              background: ntConnected ? 'var(--text-success)' : 'var(--text-muted)',
              animation: ntConnected ? 'pulse 2s infinite' : 'none'
            }}/>
            {ntConnected ? 'Live' : 'Waiting'}
          </div>
        </div>
      </div>

      {/* ── Model grid — 5 columns × 2 rows for the 10 models ── */}
      {(view === 'grid' || view === 'both') && (
        <div style={{
          display:'grid',
          gridTemplateColumns:'repeat(5, 1fr)',
          gap:'12px',
        }}>
          {ranked.map((m, i) => (
            <StreamCard key={m.name} model={m} rank={i} />
          ))}
        </div>
      )}

      {/* ── Leaderboard race — rows slide as P&L rank changes ── */}
      {(view === 'race' || view === 'both') && (
        <div style={{
          marginTop: view === 'both' ? '24px' : '0',
          padding: '20px', background: 'var(--surface-2)',
          borderRadius: '14px', border: '0.5px solid var(--border)'
        }}>
          <LeaderboardRace />
        </div>
      )}

      {/* ── "How it works" architecture panel (toggle) ── */}
      {showArch && (
        <div style={{
          marginTop:'24px', padding:'24px',
          background:'var(--surface-2)', borderRadius:'14px',
          border:'0.5px solid var(--border)'
        }}>
          <ArchitectureDiagram />
        </div>
      )}

      {/* keyframes */}
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        @keyframes flash { 0%{background:var(--surface-2)} 50%{background:var(--surface-3, #1a1d21)} 100%{background:var(--surface-2)} }
        @keyframes slideUp { from{opacity:0; transform:translateY(4px)} to{opacity:1; transform:translateY(0)} }
        @keyframes countPop { 0%{transform:scale(1)} 40%{transform:scale(1.08)} 100%{transform:scale(1)} }
        .stream-card { transition: transform 0.4s ease, border-color 0.3s ease; }
        .stream-pnl { transition: color 0.3s ease; }
      `}</style>
    </div>
  )
}

// ── Individual model card ──
function StreamCard({ model, rank }) {
  const { meta, signal, level, pnl } = model
  const [flash, setFlash] = useState(false)
  const [prevSignal, setPrevSignal] = useState(signal.signal)

  // Flash the card border when the signal changes
  useEffect(() => {
    if (signal.signal && signal.signal !== prevSignal) {
      setFlash(true)
      setPrevSignal(signal.signal)
      const t = setTimeout(() => setFlash(false), 600)
      return () => clearTimeout(t)
    }
  }, [signal.signal])

  const sig = signal.signal || '—'
  const conf = signal.confidence ? Math.round(signal.confidence * 100) : null
  const pnlPoints = pnl.points ?? 0
  const pnlColor = pnlPoints > 0 ? 'var(--text-success)' : pnlPoints < 0 ? 'var(--text-danger)' : 'var(--text-muted)'
  const lvl = level.level ?? 1
  const rank_name = level.rank ?? 'Rookie'
  const xpPct = level.xp_progress_pct ?? 0
  const streak = level.streak ?? 0

  const sigColor = sig === 'BUY' ? 'var(--text-success)' : sig === 'SELL' ? 'var(--text-danger)' : 'var(--text-muted)'
  const sigBg = sig === 'BUY' ? 'var(--bg-success)' : sig === 'SELL' ? 'var(--bg-danger)' : 'var(--surface-1)'

  const isLeader = rank === 0 && pnlPoints > 0

  return (
    <div className="stream-card" style={{
      background:'var(--surface-2)',
      border: isLeader
        ? '1.5px solid var(--border-success, var(--text-success))'
        : flash ? `1.5px solid ${meta.color}` : '0.5px solid var(--border)',
      borderRadius:'14px',
      padding:'14px',
      position:'relative',
      animation: flash ? 'flash 0.6s ease' : 'none',
    }}>
      {/* Rank medal for top 3 */}
      {rank < 3 && pnlPoints > 0 && (
        <div style={{
          position:'absolute', top:'10px', right:'12px',
          fontSize:'14px'
        }}>
          {['🥇','🥈','🥉'][rank]}
        </div>
      )}

      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'12px' }}>
        <div style={{
          width:'28px', height:'28px', borderRadius:'8px',
          background: meta.color + '22', color: meta.color,
          display:'flex', alignItems:'center', justifyContent:'center',
          fontSize:'11px', fontWeight:600, flexShrink:0
        }}>
          {meta.label.slice(0,2).toUpperCase()}
        </div>
        <div style={{ minWidth:0 }}>
          <div style={{ fontSize:'13px', fontWeight:600, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>
            {meta.label}
          </div>
          <div style={{ fontSize:'10px', color:'var(--text-muted)' }}>{meta.style}</div>
        </div>
      </div>

      {/* Signal */}
      <div style={{
        display:'inline-flex', alignItems:'center', gap:'4px',
        fontSize:'12px', fontWeight:600, padding:'4px 10px',
        borderRadius:'8px', background:sigBg, color:sigColor,
        marginBottom:'12px'
      }}>
        {sig === 'BUY' ? '▲' : sig === 'SELL' ? '▼' : '—'} {sig}{conf !== null ? ` ${conf}%` : ''}
      </div>

      {/* P&L — big and prominent */}
      <div className="stream-pnl" key={pnlPoints} style={{
        fontSize:'24px', fontWeight:700, color:pnlColor,
        fontVariantNumeric:'tabular-nums', letterSpacing:'-0.02em',
        marginBottom:'2px', animation:'countPop 0.3s ease'
      }}>
        {pnlPoints > 0 ? '+' : ''}{pnlPoints.toFixed(1)}
      </div>
      <div style={{ fontSize:'10px', color:'var(--text-muted)', marginBottom:'12px' }}>
        session points · {pnl.wins ?? 0}W {pnl.losses ?? 0}L
      </div>

      {/* Level bar */}
      <div style={{ display:'flex', alignItems:'center', gap:'6px', marginBottom:'6px' }}>
        <span style={{ fontSize:'10px', color:'var(--text-muted)', minWidth:'34px' }}>Lv {lvl}</span>
        <div style={{ flex:1, height:'4px', background:'var(--surface-1)', borderRadius:'2px', overflow:'hidden' }}>
          <div style={{
            height:'4px', borderRadius:'2px',
            width:`${Math.round(xpPct * 100)}%`,
            background: meta.color,
            transition:'width 0.5s ease'
          }}/>
        </div>
        {streak >= 3 && (
          <span style={{ fontSize:'10px', color:'var(--text-success)' }}>🔥{streak}</span>
        )}
      </div>

      {/* Rank name */}
      <div style={{ fontSize:'10px', color:'var(--text-muted)' }}>{rank_name}</div>
    </div>
  )
}
