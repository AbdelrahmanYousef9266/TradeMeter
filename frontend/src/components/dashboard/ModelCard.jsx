import { Link } from 'react-router-dom'
import useStore from '../../store'

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
  lstm:           { label: 'Deep LSTM',       style: 'Sequence patterns · Model 11' },
}

const RANK_COLORS = {
  Rookie:     'var(--text-muted)',
  Apprentice: '#3B82C4',
  Pro:        '#1D9E75',
  Elite:      '#7F77DD',
  Expert:     '#BA7517',
  Master:     '#D85A30',
}

export default function ModelCard({ modelName }) {
  const { modelSignals, modelLevels, modelPnl } = useStore()

  const signal = modelSignals[modelName] || {}
  const level  = modelLevels[modelName] || {}
  const pnl    = modelPnl[modelName] || {}

  const meta = MODEL_META[modelName] || { label: modelName, style: '' }
  const isPersonal = modelName === 'personal'
  const isLSTM = modelName === 'lstm'

  const sig = signal.signal || '—'
  const conf = signal.confidence ? Math.round(signal.confidence * 100) : null
  const target = signal.predicted_high ? signal.predicted_high.toFixed(2) : '—'

  const lvl = level.level ?? 1
  const rank = level.rank ?? 'Rookie'
  const xpPct = level.xp_progress_pct ?? 0
  const streak = level.streak ?? 0
  const barsLearned = level.bars_learned ?? 0

  const pnlPoints = pnl.points ?? 0
  const pnlDollars = pnl.dollars ?? 0
  const wins = pnl.wins ?? 0
  const losses = pnl.losses ?? 0
  const openTrades = pnl.open ?? 0

  const pnlColor = pnlPoints > 0 ? 'var(--text-success)'
                 : pnlPoints < 0 ? 'var(--text-danger)'
                 : 'var(--text-muted)'

  const sigBg = sig === 'BUY' ? 'var(--bg-success)'
              : sig === 'SELL' ? 'var(--bg-danger)'
              : 'var(--surface-1)'
  const sigColor = sig === 'BUY' ? 'var(--text-success)'
                 : sig === 'SELL' ? 'var(--text-danger)'
                 : 'var(--text-muted)'

  return (
    <div style={{
      background: 'var(--surface-2)',
      border: isPersonal ? '2px solid var(--border-accent)' : '0.5px solid var(--border)',
      borderRadius: '12px',
      padding: '14px 16px',
    }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'10px' }}>
        <div style={{
          width:'32px', height:'32px', borderRadius:'50%',
          background:'var(--surface-1)', display:'flex',
          alignItems:'center', justifyContent:'center',
          fontSize:'11px', fontWeight:500, color:'var(--text-primary)', flexShrink:0
        }}>
          {meta.label.slice(0,2).toUpperCase()}
        </div>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontSize:'13px', fontWeight:500, color:'var(--text-primary)' }}>{meta.label}</div>
          <div style={{ fontSize:'11px', color:'var(--text-muted)' }}>{meta.style}</div>
        </div>
        <span style={{
          fontSize:'10px', fontWeight:500, padding:'2px 8px',
          borderRadius:'20px', background:'var(--surface-1)',
          color: RANK_COLORS[rank] || 'var(--text-muted)', whiteSpace:'nowrap'
        }}>{rank}</span>
      </div>

      {/* Signal row */}
      <div style={{ display:'flex', alignItems:'center', gap:'6px', marginBottom:'10px' }}>
        <span style={{
          fontSize:'12px', fontWeight:500, padding:'3px 10px',
          borderRadius:'var(--radius)', background:sigBg, color:sigColor
        }}>
          {sig === 'BUY' ? '▲' : sig === 'SELL' ? '▼' : '—'} {sig}{conf !== null ? ` ${conf}%` : ''}
        </span>
        <span style={{ fontSize:'11px', color:'var(--text-muted)', marginLeft:'auto' }}>
          Target {target}
        </span>
      </div>

      {/* P&L block — the key stream feature */}
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        background:'var(--surface-1)', borderRadius:'var(--radius)',
        padding:'8px 10px', marginBottom:'10px'
      }}>
        <div style={{ textAlign:'center', flex:1 }}>
          <span style={{ fontSize:'15px', fontWeight:500, color:pnlColor, display:'block' }}>
            {pnlPoints > 0 ? '+' : ''}{pnlPoints} pts
          </span>
          <span style={{ fontSize:'10px', color:'var(--text-muted)' }}>Session P&L</span>
        </div>
        <div style={{ width:'1px', height:'28px', background:'var(--border)' }}/>
        <div style={{ textAlign:'center', flex:1 }}>
          <span style={{ fontSize:'15px', fontWeight:500, color:pnlColor, display:'block' }}>
            {pnlDollars > 0 ? '+' : ''}${pnlDollars}
          </span>
          <span style={{ fontSize:'10px', color:'var(--text-muted)' }}>Dollars</span>
        </div>
        <div style={{ width:'1px', height:'28px', background:'var(--border)' }}/>
        <div style={{ textAlign:'center', flex:1 }}>
          <span style={{ fontSize:'15px', fontWeight:500, color:'var(--text-primary)', display:'block' }}>
            {wins}/{losses}
          </span>
          <span style={{ fontSize:'10px', color:'var(--text-muted)' }}>W/L</span>
        </div>
      </div>

      {/* Open trades / blend info */}
      <div style={{ fontSize:'11px', color:'var(--text-muted)', marginBottom:'10px', textAlign:'center' }}>
        {isPersonal
          ? (level.blend ? `Blend: ${level.blend}` : 'Hybrid ensemble')
          : openTrades > 0
            ? `${openTrades} open trade${openTrades > 1 ? 's' : ''}`
            : 'No open trades'}
      </div>

      {/* XP bar */}
      {!isLSTM && (
        <>
          <div style={{ display:'flex', alignItems:'center', gap:'6px', marginBottom:'10px' }}>
            <span style={{ fontSize:'11px', color:'var(--text-muted)', whiteSpace:'nowrap' }}>Lv {lvl}</span>
            <div style={{ flex:1, height:'4px', background:'var(--surface-1)', borderRadius:'2px', overflow:'hidden' }}>
              <div style={{
                height:'4px', borderRadius:'2px',
                width:`${Math.round(xpPct * 100)}%`,
                background:'var(--fill-accent)', transition:'width 0.3s ease'
              }}/>
            </div>
            <span style={{ fontSize:'11px', color: streak >= 5 ? 'var(--text-success)' : 'var(--text-muted)', whiteSpace:'nowrap' }}>
              {streak >= 5 ? `🔥 ${streak}` : `${streak}`}
            </span>
          </div>

          {/* Stats row */}
          <div style={{ display:'flex', justifyContent:'space-between', fontSize:'10px', color:'var(--text-muted)', marginBottom:'10px' }}>
            <span>{barsLearned.toLocaleString()} bars learned</span>
            <span>{wins + losses > 0 ? `${Math.round(wins / (wins + losses) * 100)}% win rate` : 'No trades yet'}</span>
          </div>
        </>
      )}

      {/* Tune button — SPA navigation via <Link> (a plain <a href> would full-reload
          the app and tear down the persistent WebSocket) */}
      {isLSTM ? (
        <span style={{
          display:'block', textAlign:'center', fontSize:'11px',
          padding:'6px', borderRadius:'var(--radius)',
          border:'0.5px solid var(--border-strong)', color:'var(--text-muted)'
        }}>
          Batch trained
        </span>
      ) : (
        <Link to={`/models/${modelName}`} style={{
          display:'block', textAlign:'center', fontSize:'11px',
          padding:'6px', borderRadius:'var(--radius)',
          border:'0.5px solid var(--border-strong)',
          color:'var(--text-secondary)', textDecoration:'none'
        }}>
          {isPersonal ? 'Customize me ↗' : 'Tune behavior ↗'}
        </Link>
      )}
    </div>
  )
}
