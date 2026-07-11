import { useEffect, useState, useCallback } from 'react'
import useStore from '../../store'
import { getMode, setModeLive, setModeOffline } from '../../services/api'
import PromotionModal from './PromotionModal'

const GREEN  = '#1D9E75'
const PURPLE = '#7c5cff'
const RED    = '#E24B4A'

/**
 * MODE indicator + switch — replaces the old TrainingMode banner.
 *
 * Shows exactly one state (🟢 LIVE / 📚 OFFLINE), the ingestion queue depth, and
 * a switch control. Switching requires a drained queue (backend returns 409
 * otherwise); when blocked we surface a "flush & switch" action. The intended
 * workflow (OFFLINE → import → review → promote → LIVE) is shown inline, and the
 * "Promote offline → live" entry point lives here too.
 *
 * The ingestion Arm/Disarm gate is a SEPARATE, orthogonal control (IngestionControl)
 * — this only decides which KIND of bars (live vs historical) are accepted.
 */
export default function ModeBanner() {
  const mode      = useStore(s => s.mode)
  const setMode   = useStore(s => s.setMode)
  const offlineP  = useStore(s => s.offlineProgress)

  const [queue, setQueue]     = useState(0)
  const [canSwitch, setCanSwitch] = useState(true)
  const [counters, setCounters]   = useState({ bars_ingested: 0, sessions_ingested: 0 })
  const [blocker, setBlocker] = useState(null)   // { target, pending } when a switch is blocked
  const [busy, setBusy]       = useState(false)
  const [showPromote, setShowPromote] = useState(false)

  const apply = useCallback((d) => {
    if (!d) return
    if (d.mode) setMode(d.mode)
    setQueue(Math.max(0, d.queue_pending ?? 0))
    if (typeof d.can_switch === 'boolean') setCanSwitch(d.can_switch)
    setCounters({ bars_ingested: d.bars_ingested ?? 0, sessions_ingested: d.sessions_ingested ?? 0 })
  }, [setMode])

  // Poll mode/queue — faster while OFFLINE or while anything is queued.
  useEffect(() => { getMode().then(r => apply(r.data)).catch(() => {}) }, [apply])
  useEffect(() => {
    const fast = mode === 'offline' || queue > 0
    const id = setInterval(() => getMode().then(r => apply(r.data)).catch(() => {}), fast ? 2000 : 6000)
    return () => clearInterval(id)
  }, [mode, queue, apply])

  const isOffline = mode === 'offline'
  const target = isOffline ? 'live' : 'offline'

  const doSwitch = async (flush) => {
    setBusy(true)
    try {
      const call = target === 'offline' ? setModeOffline : setModeLive
      const res = await call(flush)
      apply(res.data)
      setBlocker(null)
    } catch (e) {
      if (e.response?.status === 409) {
        const d = e.response.data?.detail || {}
        setBlocker({ target, pending: d.queue_pending ?? queue })
      }
    } finally {
      setBusy(false)
    }
  }

  const accent = isOffline ? PURPLE : GREEN
  const processed = offlineP?.processed ?? 0

  return (
    <div style={{ marginBottom: 12 }}>
      {/* Banner */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        padding: '12px 16px', borderRadius: 12, flexWrap: 'wrap',
        background: `${accent}14`, border: `1px solid ${accent}55`, borderLeft: `4px solid ${accent}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
          <span style={{
            width: 11, height: 11, borderRadius: '50%', background: accent, flexShrink: 0,
            boxShadow: `0 0 0 4px ${accent}22`,
            animation: isOffline ? 'mode-pulse 1.6s ease-in-out infinite' : 'none',
          }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: accent, letterSpacing: '0.02em' }}>
              {isOffline ? '📚 OFFLINE MODE' : '🟢 LIVE MODE'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 1 }}>
              {isOffline
                ? 'Training on history · live models untouched'
                : 'Trading live · models predicting on real bars'}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Queue / progress readout */}
          <span style={{ fontSize: 11.5, color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
            {isOffline && (processed > 0 || queue > 0)
              ? `${processed.toLocaleString()} processed · ${queue.toLocaleString()} queued`
              : `${queue.toLocaleString()} bars queued`}
          </span>

          {/* Promote entry point */}
          <button onClick={() => setShowPromote(true)} style={pill(PURPLE, isOffline)}>
            ⬆ Promote offline → live
          </button>

          {/* Switch */}
          <button onClick={() => doSwitch(false)} disabled={busy} style={{
            ...pill(target === 'offline' ? PURPLE : GREEN, true), opacity: busy ? 0.6 : 1,
          }}>
            {busy ? '…' : target === 'offline' ? '📚 Switch to Offline' : '🟢 Switch to Live'}
          </button>
        </div>
      </div>

      {/* Drain blocker */}
      {blocker && (
        <div style={{
          marginTop: 8, padding: '10px 14px', borderRadius: 10,
          background: `${RED}14`, border: `1px solid ${RED}55`,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            {blocker.pending.toLocaleString()} bar(s) still queued — switching now would mix historical
            and live data. Flush the queue to switch to <b style={{ color: 'var(--text-primary)' }}>{blocker.target}</b>?
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => doSwitch(true)} disabled={busy} style={pill(RED, true)}>
              🗑 Flush & switch
            </button>
            <button onClick={() => setBlocker(null)} disabled={busy} style={pill('var(--border)', false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Workflow hint */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '7px 2px 0', letterSpacing: '0.02em' }}>
        Workflow: <b style={{ color: PURPLE }}>OFFLINE</b> → import history → review preview →
        <b style={{ color: PURPLE }}> promote</b> → <b style={{ color: GREEN }}>LIVE</b>
        {counters.sessions_ingested > 0 && isOffline &&
          ` · ${counters.sessions_ingested} session(s) this run`}
      </div>

      {showPromote && <PromotionModal onClose={() => setShowPromote(false)} />}

      <style>{`@keyframes mode-pulse { 0%,100%{opacity:1} 50%{opacity:.4} }`}</style>
    </div>
  )
}

function pill(color, filled) {
  return {
    fontSize: 11.5, padding: '6px 12px', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap',
    fontWeight: 600,
    color: filled ? '#fff' : color,
    background: filled ? color : 'transparent',
    border: `1px solid ${color}${filled ? '' : '66'}`,
  }
}
