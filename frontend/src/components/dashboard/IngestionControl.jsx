import { useEffect, useState, useCallback } from 'react'
import { armIngestion, disarmIngestion, getIngestionStatus, getNTStatus } from '../../services/api'

// Green accent — arming controls the LIVE pipeline (distinct from training's purple).
const ACCENT = '#10b981'

/**
 * Ingestion arm-gate control + banner.
 *
 * Enabling the NinjaTrader strategy immediately streams bars over TCP. This gate
 * decides WHEN those bars enter the pipeline. While DISARMED (the default) every
 * incoming bar is refused at the backend TCP intake — never queued, never stored —
 * so a connected strategy doesn't stack the queue. Arming opens the gate.
 *
 * Recommended bulk-import sequence made obvious in the UI:
 *   1. enable the strategy in NinjaTrader (bars refused, nothing stacks),
 *   2. Start Training (if importing history),
 *   3. Arm Ingestion → bars flow.
 * Disarm offers a flush so stopping also clears anything queued.
 */
export default function IngestionControl() {
  const [armed, setArmed]     = useState(false)
  const [queued, setQueued]   = useState(0)
  const [ntConn, setNtConn]   = useState(false)
  const [busy, setBusy]       = useState(false)

  const applyStatus = useCallback((d) => {
    if (!d) return
    setArmed(!!d.armed)
    setQueued(d.queue_pending ?? 0)
  }, [])

  // Hydrate once, then poll: armed flag + queue depth, and the REAL NT connection
  // so we can nudge the user to arm once the strategy is connected.
  useEffect(() => {
    getIngestionStatus().then(r => applyStatus(r.data)).catch(() => {})
  }, [applyStatus])

  useEffect(() => {
    let active = true
    const poll = () => {
      getIngestionStatus().then(r => active && applyStatus(r.data)).catch(() => {})
      getNTStatus().then(r => active && setNtConn(r.data?.connected ?? false)).catch(() => {})
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { active = false; clearInterval(id) }
  }, [applyStatus])

  const arm = async () => {
    if (busy) return
    setBusy(true)
    try {
      const res = await armIngestion()
      applyStatus(res.data)
    } catch { /* leave state as-is */ } finally { setBusy(false) }
  }

  const disarm = async (flush) => {
    if (busy) return
    setBusy(true)
    try {
      const res = await disarmIngestion(flush)
      applyStatus(res.data)
    } catch { /* leave state as-is */ } finally { setBusy(false) }
  }

  const bannerColor = armed ? ACCENT : 'var(--text-warning, #d9a441)'

  return (
    <div style={{ marginBottom: 12 }}>
      {/* Status banner — always shown so the gate state is never ambiguous. */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, marginBottom: 8, padding: '10px 14px', borderRadius: 10,
        background: `${bannerColor}1a`, border: `1px solid ${bannerColor}66`,
        borderLeft: `3px solid ${bannerColor}`, flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 13, color: bannerColor, fontWeight: 500 }}>
          {armed
            ? '● Ingesting — strategy bars are flowing into the pipeline'
            : '⏸ Ingestion paused — strategy bars are being refused. Press Arm to begin.'}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
          {armed
            ? `${queued.toLocaleString()} queued`
            : queued > 0 ? `${queued.toLocaleString()} still queued` : 'queue at 0'}
        </span>
      </div>

      {/* Hint: strategy is connected but ingestion is disarmed → tell them to arm. */}
      {!armed && ntConn && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
          NinjaTrader connected. Arm ingestion when ready to receive bars.
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {armed ? (
          <>
            <button
              onClick={() => disarm(false)}
              disabled={busy}
              style={btnStyle(false, busy)}
            >
              {busy ? '…' : '⏸ Disarm Ingestion'}
            </button>
            {queued > 0 && (
              <button
                onClick={() => {
                  if (!window.confirm('Disarm and discard queued bars? They are re-importable via gap-fill.')) return
                  disarm(true)
                }}
                disabled={busy}
                style={{
                  fontSize: 11, padding: '5px 12px', borderRadius: 8,
                  cursor: busy ? 'not-allowed' : 'pointer',
                  color: 'var(--text-danger)', background: 'transparent',
                  border: '1px solid var(--text-danger)66',
                }}
              >
                ⏹ Disarm & flush queue
              </button>
            )}
          </>
        ) : (
          <button onClick={arm} disabled={busy} style={btnStyle(true, busy)}>
            {busy ? '…' : '▶ Arm Ingestion'}
          </button>
        )}
      </div>
    </div>
  )
}

function btnStyle(isArm, busy) {
  return {
    fontSize: 12, padding: '6px 14px', borderRadius: 8,
    cursor: busy ? 'not-allowed' : 'pointer', fontWeight: 500,
    color: isArm ? '#fff' : ACCENT,
    background: isArm ? ACCENT : 'transparent',
    border: `1px solid ${ACCENT}${isArm ? '' : '66'}`,
  }
}
