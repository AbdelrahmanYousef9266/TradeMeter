import { useEffect, useState, useCallback } from 'react'
import { getPromotionPreview, promoteOfflineToLive } from '../../services/api'

const PURPLE = '#7c5cff'
const GREEN  = '#1D9E75'
const RED    = '#E24B4A'

const MODEL_LABELS = {
  scalper: 'Scalper', momentum: 'Momentum', mean_reversion: 'Mean Reversion',
  breakout: 'Breakout', conservative: 'Conservative', aggressive: 'Aggressive',
  volume: 'Volume', contrarian: 'Contrarian', personal: 'Secret', lstm: 'Deep LSTM',
}

/**
 * Promotion UI — the ONLY path from offline-trained weights to live trading.
 *
 * Shows a per-model comparison (offline vs live bars_learned + simulated P&L /
 * win-rate from GET /models/promotion-preview) so the operator can judge whether
 * the offline training is actually better before committing. Promoting copies
 * the offline weights into the live models (live levels/XP unchanged) via POST
 * /models/promote {confirm:"PROMOTE"}. Nothing is ever promoted automatically.
 */
export default function PromotionModal({ onClose }) {
  const [timeframe, setTimeframe] = useState('all')
  const [preview, setPreview]     = useState(null)
  const [loading, setLoading]     = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy]           = useState(false)
  const [result, setResult]       = useState(null)
  const [error, setError]         = useState(null)

  const load = useCallback((tf) => {
    setLoading(true); setError(null)
    getPromotionPreview(tf)
      .then(r => setPreview(r.data))
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load(timeframe) }, [timeframe, load])

  const doPromote = async () => {
    setBusy(true); setError(null)
    try {
      const r = await promoteOfflineToLive(timeframe)
      setResult(r.data)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false); setConfirming(false)
    }
  }

  const rows = preview?.models || []
  const promotable = preview?.offline_exists

  return (
    <Backdrop onClose={onClose}>
      <div style={{
        width: 'min(760px, 94vw)', maxHeight: '88vh', overflow: 'auto',
        background: 'var(--surface-1, #16181d)', borderRadius: 14,
        border: `1px solid ${PURPLE}55`, borderTop: `3px solid ${PURPLE}`,
        padding: '20px 22px',
      }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)' }}>
              Promote offline → live
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>
              Copy the history-trained (offline) weights into your live models. Compare first.
            </div>
          </div>
          <button onClick={onClose} style={closeBtn}>✕</button>
        </div>

        {/* Timeframe selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '16px 0 10px' }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: '0.04em' }}>Promote</span>
          <div style={{ display: 'flex', gap: 2, background: 'var(--surface-3)', borderRadius: 7, padding: 2 }}>
            {[['all', 'All'], ['5min', '5-min'], ['1min', '1-min']].map(([v, label]) => (
              <button key={v} onClick={() => { setResult(null); setTimeframe(v) }} style={{
                padding: '4px 14px', borderRadius: 5, fontSize: 11, border: 'none', cursor: 'pointer',
                background: timeframe === v ? PURPLE : 'transparent',
                color: timeframe === v ? '#fff' : 'var(--text-secondary)',
                fontWeight: timeframe === v ? 600 : 400,
              }}>{label}</button>
            ))}
          </div>
        </div>

        {/* Body */}
        {loading ? (
          <Note>Loading comparison…</Note>
        ) : error && !result ? (
          <Note color={RED}>{String(error)}</Note>
        ) : result ? (
          <SuccessView result={result} />
        ) : !promotable ? (
          <Note>
            No offline-trained models yet. Switch to <b>Offline mode</b>, import history, then come back here.
          </Note>
        ) : (
          <ComparisonTable rows={rows} />
        )}

        {/* Footer / confirm */}
        {!result && promotable && !loading && (
          <div style={{ marginTop: 18, borderTop: '1px solid var(--border-subtle, #ffffff12)', paddingTop: 14 }}>
            {confirming ? (
              <div style={{
                background: `${RED}14`, border: `1px solid ${RED}55`, borderRadius: 10, padding: '12px 14px',
              }}>
                <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 600, marginBottom: 4 }}>
                  This affects live trading.
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                  This copies the offline-trained weights into your live models
                  ({timeframe === 'all' ? 'all timeframes' : timeframe}). Live levels/XP are
                  unchanged. The live pipeline reloads and trades on the new weights from the next bar.
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button onClick={doPromote} disabled={busy} style={{ ...primaryBtn(RED), opacity: busy ? 0.6 : 1 }}>
                    {busy ? 'Promoting…' : 'Yes, promote to live'}
                  </button>
                  <button onClick={() => setConfirming(false)} disabled={busy} style={ghostBtn}>Cancel</button>
                </div>
              </div>
            ) : (
              <button onClick={() => setConfirming(true)} style={primaryBtn(PURPLE)}>
                ⬆ Promote {timeframe === 'all' ? 'all' : timeframe} to live…
              </button>
            )}
          </div>
        )}
      </div>
    </Backdrop>
  )
}

function ComparisonTable({ rows }) {
  if (!rows.length) return <Note>No models to compare.</Note>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ color: 'var(--text-muted)', textAlign: 'right' }}>
            <th style={{ ...th, textAlign: 'left' }}>Model</th>
            <th style={th}>TF</th>
            <th style={th} title="Bars the offline copy learned this run">Offline bars</th>
            <th style={th} title="Bars the live model has learned">Live bars</th>
            <th style={th}>Offline P&L</th>
            <th style={th}>Live P&L</th>
            <th style={th}>Offline W/L</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(m => {
            const better = (m.offline?.pnl_points ?? 0) > (m.live?.pnl_points ?? 0)
            return (
              <tr key={m.id} style={{ borderTop: '1px solid var(--border-subtle, #ffffff10)' }}>
                <td style={{ ...td, textAlign: 'left', color: 'var(--text-primary)' }}>
                  {MODEL_LABELS[m.model_name] || m.model_name}
                  {!m.offline_ready && <span style={{ color: 'var(--text-muted)', fontSize: 10 }}> · no offline</span>}
                </td>
                <td style={td}>{m.timeframe}</td>
                <td style={{ ...td, color: PURPLE, fontWeight: 600 }}>{fmt(m.offline?.bars_learned)}</td>
                <td style={td}>{fmt(m.live?.bars_learned)}</td>
                <td style={{ ...td, color: pnlColor(m.offline?.pnl_points) }}>{fmtP(m.offline?.pnl_points)}</td>
                <td style={{ ...td, color: pnlColor(m.live?.pnl_points) }}>{fmtP(m.live?.pnl_points)}</td>
                <td style={{ ...td, color: better ? GREEN : 'var(--text-secondary)' }}>
                  {m.offline?.wins ?? 0}/{m.offline?.losses ?? 0}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 8 }}>
        P&L / win-rate are this-session simulated stats and only appear for pipelines currently in memory.
        Bars-learned is the durable signal of how much each side trained.
      </div>
    </div>
  )
}

function SuccessView({ result }) {
  const per = result.models_promoted || {}
  return (
    <div style={{
      marginTop: 6, background: `${GREEN}14`, border: `1px solid ${GREEN}55`,
      borderRadius: 10, padding: '14px 16px',
    }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: GREEN }}>
        {result.promoted ? '✓ Promoted to live' : 'Nothing to promote'}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6, lineHeight: 1.5 }}>
        {result.message}
      </div>
      {Object.keys(per).length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
          {Object.entries(per).map(([tf, n]) => (
            <span key={tf} style={{ marginRight: 12 }}>{tf}: <b style={{ color: 'var(--text-secondary)' }}>{n}</b> model(s)</span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── bits ──────────────────────────────────────────────────────────────────
function Backdrop({ children, onClose }) {
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: '#000a', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
    }}>{children}</div>
  )
}
function Note({ children, color }) {
  return <div style={{ fontSize: 13, color: color || 'var(--text-secondary)', padding: '18px 4px', lineHeight: 1.6 }}>{children}</div>
}
const th = { padding: '6px 8px', fontWeight: 500, whiteSpace: 'nowrap' }
const td = { padding: '7px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }
const closeBtn = { background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 16, cursor: 'pointer' }
const ghostBtn = { fontSize: 12, padding: '8px 14px', borderRadius: 8, cursor: 'pointer', color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border)' }
const primaryBtn = (c) => ({ fontSize: 12, padding: '8px 16px', borderRadius: 8, cursor: 'pointer', color: '#fff', background: c, border: 'none', fontWeight: 600 })
const fmt  = (n) => (n ?? 0).toLocaleString()
const fmtP = (n) => `${(n ?? 0) >= 0 ? '+' : ''}${(n ?? 0).toFixed(1)}`
const pnlColor = (n) => (n ?? 0) > 0 ? GREEN : (n ?? 0) < 0 ? RED : 'var(--text-secondary)'
