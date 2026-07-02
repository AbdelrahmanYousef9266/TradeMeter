import { useState, useEffect, useMemo } from 'react'
import useStore from '../store'
import { getLSTMStatus } from '../services/api'
import LeaderboardRace from '../components/LeaderboardRace'
import ArchitectureDiagram from '../components/ArchitectureDiagram'

const MODEL_META = {
  momentum:       { label: 'Momentum',       abbr: 'MO', color: '#1D9E75' },
  breakout:       { label: 'Breakout',       abbr: 'BR', color: '#BA7517' },
  volume:         { label: 'Volume',         abbr: 'VO', color: '#7F77DD' },
  personal:       { label: 'You',            abbr: 'YO', color: '#378ADD' },
  mean_reversion: { label: 'Mean Reversion', abbr: 'MR', color: '#D85A30' },
  aggressive:     { label: 'Aggressive',     abbr: 'AG', color: '#E24B4A' },
  conservative:   { label: 'Conservative',   abbr: 'CO', color: '#639922' },
  scalper:        { label: 'Scalper',        abbr: 'SC', color: '#3B82C4' },
  contrarian:     { label: 'Contrarian',     abbr: 'CN', color: '#D4537E' },
  lstm:           { label: 'Deep LSTM',      abbr: 'DL', color: '#534AB7' },
}
const MODEL_NAMES = Object.keys(MODEL_META)

export default function AfkStream() {
  const { modelSignals, modelLevels, modelPnl, currentBar, ntConnected } = useStore()

  // LSTM collection status — polled from the existing /models/lstm/status endpoint
  const [lstmStatus, setLstmStatus] = useState(null)

  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const res = await getLSTMStatus()
        if (active) setLstmStatus(res.data)
      } catch (e) {
        // silent — LSTM status is non-critical for the stream
      }
    }
    poll()
    const interval = setInterval(poll, 5000)  // poll every 5 seconds
    return () => { active = false; clearInterval(interval) }
  }, [])

  // Session stats
  const stats = useMemo(() => {
    let totalPnl = 0, totalWins = 0, totalLosses = 0, maxBars = 0
    MODEL_NAMES.forEach(name => {
      const p = modelPnl[name] || {}
      const l = modelLevels[name] || {}
      totalPnl += p.points ?? 0
      totalWins += p.wins ?? 0
      totalLosses += p.losses ?? 0
      maxBars = Math.max(maxBars, l.bars_learned ?? 0)
    })
    const winRate = (totalWins + totalLosses) > 0
      ? Math.round(totalWins / (totalWins + totalLosses) * 100) : 0
    return { totalPnl, totalWins, totalLosses, maxBars, winRate }
  }, [modelPnl, modelLevels])

  const price = currentBar?.close ?? null

  return (
    <div style={{
      width: '100vw', height: '100vh', overflow: 'hidden',
      background: 'var(--surface-0, #0e0f11)',
      padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      color: 'var(--text-primary)', boxSizing: 'border-box',
    }}>
      {/* ── Header ── */}
      <div style={{
        height: '52px', flexShrink: 0,
        background: 'var(--surface-2)', borderRadius: '10px',
        border: '0.5px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 18px',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <span style={{ fontSize: '18px', fontWeight: 600, letterSpacing: '-0.02em' }}>TradeMeter</span>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Live ML · 11 models learning in real time</span>
        </div>
        <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
          <Stat label="MES" value={price ? price.toFixed(2) : '—'} />
          <Stat label="Combined P&L" value={`${stats.totalPnl > 0 ? '+' : ''}${stats.totalPnl.toFixed(1)}`}
                color={stats.totalPnl > 0 ? 'var(--text-success)' : stats.totalPnl < 0 ? 'var(--text-danger)' : undefined} />
          <Stat label="Bars today" value={stats.maxBars.toLocaleString()} />
          <Stat label="Win rate" value={`${stats.winRate}%`} />
          <Stat label="Trades" value={`${stats.totalWins + stats.totalLosses}`} />
          {lstmStatus && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: '140px' }}>
              {lstmStatus.is_trained ? (
                // State 3: Active
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-success)' }}>
                  <span>🧬 LSTM Active</span>
                  {lstmStatus.train_accuracy != null && (
                    <span style={{ color: 'var(--text-muted)' }}>{Math.round(lstmStatus.train_accuracy * 100)}% acc</span>
                  )}
                </div>
              ) : lstmStatus.is_dormant ? (
                // State 1: Collecting
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: 'var(--text-muted)' }}>
                    <span>🧬 LSTM collecting</span>
                    <span>{lstmStatus.bars_available?.toLocaleString()} / {lstmStatus.bars_needed?.toLocaleString()}</span>
                  </div>
                  <div style={{ height: '5px', background: 'var(--surface-1)', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      height: '5px', borderRadius: '3px',
                      width: `${lstmStatus.progress_pct ?? 0}%`,
                      background: '#534AB7',
                      transition: 'width 0.5s ease',
                    }}/>
                  </div>
                </>
              ) : (
                // State 2: Ready to train
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#534AB7' }}>
                  <span>🧬 LSTM ready to train</span>
                  <span style={{ color: 'var(--text-muted)' }}>{lstmStatus.bars_available?.toLocaleString()} bars</span>
                </div>
              )}
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px',
            color: ntConnected ? 'var(--text-success)' : 'var(--text-muted)' }}>
            <span style={{
              width: '8px', height: '8px', borderRadius: '50%',
              background: ntConnected ? 'var(--text-success)' : 'var(--text-muted)',
              animation: ntConnected ? 'afk-pulse 2s infinite' : 'none'
            }}/>
            {ntConnected ? 'Live' : 'Waiting'}
          </div>
        </div>
      </div>

      {/* ── Body: left grid + right column ── */}
      <div style={{ flex: 1, display: 'flex', gap: '10px', minHeight: 0 }}>

        {/* Left: model grid (hero) */}
        <div style={{ flex: 1.7, display: 'flex', flexDirection: 'column', gap: '6px', minHeight: 0 }}>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', paddingLeft: '2px' }}>
            11 models · live signals &amp; session P&L
          </div>
          <div style={{
            flex: 1, display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            gridTemplateRows: 'repeat(2, 1fr)',
            gap: '8px', minHeight: 0,
          }}>
            {MODEL_NAMES.map(name => (
              <AfkModelCell
                key={name}
                name={name}
                meta={MODEL_META[name]}
                signal={modelSignals[name] || {}}
                level={modelLevels[name] || {}}
                pnl={modelPnl[name] || {}}
                lstmStatus={name === 'lstm' ? lstmStatus : null}
              />
            ))}
          </div>
        </div>

        {/* Right: race + architecture */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minHeight: 0 }}>
          <div style={{
            background: 'var(--surface-2)', border: '0.5px solid var(--border)',
            borderRadius: '10px', padding: '12px', overflow: 'hidden', flexShrink: 0,
          }}>
            <LeaderboardRace compact />
          </div>
          <div style={{
            flex: 1, background: 'var(--surface-2)', border: '0.5px solid var(--border)',
            borderRadius: '10px', padding: '12px', overflow: 'hidden',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <ArchitectureDiagram compact />
          </div>
        </div>
      </div>

      <style>{`
        @keyframes afk-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        @keyframes afk-flash { 0%{background:var(--surface-2)} 50%{background:var(--surface-1)} 100%{background:var(--surface-2)} }
        @keyframes afk-collect { 0%,100%{opacity:0.7} 50%{opacity:1} }
        .lstm-collecting { animation: afk-collect 2s ease-in-out infinite; }
      `}</style>
    </div>
  )
}

function Stat({ label, value, color }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '15px', fontWeight: 600, color: color || 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{label}</div>
    </div>
  )
}

function AfkModelCell({ name, meta, signal, level, pnl, lstmStatus }) {
  const isLSTM = name === 'lstm'
  const lstmState = isLSTM && lstmStatus
    ? (lstmStatus.is_trained ? 'active' : lstmStatus.is_dormant ? 'collecting' : 'ready')
    : null

  const sig = signal.signal || '—'
  const conf = signal.confidence ? Math.round(signal.confidence * 100) : null
  const pnlPoints = pnl.points ?? 0
  const pnlColor = pnlPoints > 0 ? 'var(--text-success)' : pnlPoints < 0 ? 'var(--text-danger)' : 'var(--text-muted)'
  const lvl = level.level ?? 1
  const rank = level.rank ?? 'Rookie'
  const xpPct = level.xp_progress_pct ?? 0
  const streak = level.streak ?? 0

  const sigColor = sig === 'BUY' ? 'var(--text-success)' : sig === 'SELL' ? 'var(--text-danger)' : 'var(--text-muted)'
  const sigBg = sig === 'BUY' ? 'var(--bg-success)' : sig === 'SELL' ? 'var(--bg-danger)' : 'var(--surface-1)'

  return (
    <div style={{
      background: 'var(--surface-2)', border: '0.5px solid var(--border)',
      borderRadius: '10px', padding: '10px',
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      minHeight: 0,
    }}>
      {/* Top: avatar + name */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
        <div style={{
          width: '26px', height: '26px', borderRadius: '7px', flexShrink: 0,
          background: meta.color + '22', color: meta.color,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '10px', fontWeight: 600,
        }}>{meta.abbr}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: '12px', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {meta.label}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
            {lstmState === 'collecting' ? 'Neural net · warming up'
             : lstmState === 'ready' ? 'Neural net · ready to train'
             : `${rank} · Lv ${lvl}`}
          </div>
        </div>
      </div>

      {lstmState === 'collecting' ? (
        /* State 1: Collecting — show collection progress instead of signal/P&L */
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '6px' }}>
          <div className="lstm-collecting" style={{ fontSize: '11px', color: '#534AB7', fontWeight: 500 }}>
            🧬 Collecting data
          </div>
          <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
            {lstmStatus.bars_available?.toLocaleString()}
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 400 }}>
              {' '}/ {lstmStatus.bars_needed?.toLocaleString()}
            </span>
          </div>
          <div style={{ height: '5px', background: 'var(--surface-1)', borderRadius: '3px', overflow: 'hidden' }}>
            <div style={{
              height: '5px', borderRadius: '3px',
              width: `${lstmStatus.progress_pct ?? 0}%`,
              background: '#534AB7',
              transition: 'width 0.5s ease',
            }}/>
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
            {(lstmStatus.bars_needed - lstmStatus.bars_available)?.toLocaleString()} bars until activation
          </div>
        </div>
      ) : lstmState === 'ready' ? (
        /* State 2: Ready to train — enough data collected, awaiting training */
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '6px' }}>
          <div className="lstm-collecting" style={{ fontSize: '11px', color: '#534AB7', fontWeight: 500 }}>
            🧬 Ready to train
          </div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {lstmStatus.bars_available?.toLocaleString()}
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 400 }}> bars ready</span>
          </div>
          <div style={{ height: '5px', background: 'var(--surface-1)', borderRadius: '3px', overflow: 'hidden' }}>
            <div style={{ height: '5px', borderRadius: '3px', width: '100%', background: '#534AB7' }}/>
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>Training on next nightly cycle</div>
        </div>
      ) : (
        <>
          {/* Signal */}
          <div style={{
            display: 'inline-block', alignSelf: 'flex-start',
            fontSize: '11px', fontWeight: 600, padding: '2px 8px',
            borderRadius: '6px', background: sigBg, color: sigColor, marginBottom: '6px',
          }}>
            {sig === 'BUY' ? '▲' : sig === 'SELL' ? '▼' : '—'} {sig}{conf !== null ? ` ${conf}%` : ''}
          </div>

          {/* P&L — big */}
          <div style={{
            fontSize: '20px', fontWeight: 700, color: pnlColor,
            fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em',
          }}>
            {pnlPoints > 0 ? '+' : ''}{pnlPoints.toFixed(1)}
          </div>
          <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '6px' }}>
            session pts · {pnl.wins ?? 0}W {pnl.losses ?? 0}L
          </div>

          {/* XP bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <div style={{ flex: 1, height: '3px', background: 'var(--surface-1)', borderRadius: '2px', overflow: 'hidden' }}>
              <div style={{
                height: '3px', borderRadius: '2px',
                width: `${Math.round(xpPct * 100)}%`, background: meta.color,
                transition: 'width 0.5s ease',
              }}/>
            </div>
            {streak >= 3 && <span style={{ fontSize: '9px', color: 'var(--text-success)' }}>🔥{streak}</span>}
          </div>
        </>
      )}
    </div>
  )
}
