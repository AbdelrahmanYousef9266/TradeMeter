import { useEffect, useState, useCallback } from 'react'
import { startTraining, stopTraining, getTrainingStatus, flushQueue } from '../../services/api'

// Distinct purple accent so training mode is never confused with live (green).
const ACCENT = '#7c5cff'

/**
 * Training Mode control + banner.
 *
 * Toggles the per-user backend flag that bypasses the live monotonic watermark
 * and isolates replayed historical data (is_training). While active it shows a
 * loud banner with a live counter of bars/sessions ingested this run, the depth
 * of the shared ingestion queue, and a "Flush queue" escape hatch for a stuck
 * or unwanted import.
 */
export default function TrainingMode() {
  const [training, setTraining] = useState(false)
  const [bars, setBars]         = useState(0)
  const [sessions, setSessions] = useState(0)
  const [queued, setQueued]     = useState(0)
  const [busy, setBusy]         = useState(false)
  const [flushing, setFlushing] = useState(false)

  const applyStatus = useCallback((d) => {
    if (!d) return
    setTraining(!!d.training)
    setBars(d.bars_ingested ?? 0)
    setSessions(d.sessions_ingested ?? 0)
    setQueued(d.queue_pending ?? 0)
  }, [])

  // Hydrate once, then poll while active OR while anything is still queued, so
  // the counter climbs during an import and the depth indicator drains to 0.
  useEffect(() => {
    getTrainingStatus().then(r => applyStatus(r.data)).catch(() => {})
  }, [applyStatus])

  useEffect(() => {
    if (!training && queued === 0) return
    const id = setInterval(() => {
      getTrainingStatus().then(r => applyStatus(r.data)).catch(() => {})
    }, 2000)
    return () => clearInterval(id)
  }, [training, queued, applyStatus])

  const toggle = async () => {
    if (busy) return
    setBusy(true)
    try {
      const res = training ? await stopTraining() : await startTraining()
      applyStatus(res.data)
    } catch {
      /* leave state as-is on failure */
    } finally {
      setBusy(false)
    }
  }

  const handleFlush = async () => {
    if (flushing) return
    if (!window.confirm('Discard queued bars? They are re-importable via gap-fill.')) return
    setFlushing(true)
    try {
      await flushQueue()
      setQueued(0)
    } catch {
      /* ignore */
    } finally {
      setFlushing(false)
    }
  }

  // Processed / total for the progress line while bars are still draining.
  const total = bars + queued

  return (
    <div style={{ marginBottom: 12 }}>
      {training && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, marginBottom: 8, padding: '10px 14px', borderRadius: 10,
          background: `${ACCENT}1a`, border: `1px solid ${ACCENT}66`,
          borderLeft: `3px solid ${ACCENT}`, flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: 13, color: ACCENT, fontWeight: 500 }}>
            🎓 TRAINING MODE — replaying historical data, learning enabled, live watermark paused
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
            {queued > 0
              ? `Processing ${bars.toLocaleString()} / ${total.toLocaleString()} · ${queued.toLocaleString()} queued`
              : `${bars.toLocaleString()} bars · ${sessions} session${sessions === 1 ? '' : 's'} this run`}
          </span>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button
          onClick={toggle}
          disabled={busy}
          style={{
            fontSize: 12, padding: '6px 14px', borderRadius: 8, cursor: busy ? 'not-allowed' : 'pointer',
            fontWeight: 500,
            color: training ? '#fff' : ACCENT,
            background: training ? ACCENT : 'transparent',
            border: `1px solid ${ACCENT}${training ? '' : '66'}`,
          }}
        >
          {busy ? '…' : training ? '⏹ Stop Training' : '🎓 Start Training'}
        </button>

        {/* Queue depth + flush — shown whenever bars are queued (even after stop). */}
        {queued > 0 && (
          <>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
              ~{queued.toLocaleString()} bars queued
            </span>
            <button
              onClick={handleFlush}
              disabled={flushing}
              style={{
                fontSize: 11, padding: '5px 12px', borderRadius: 8,
                cursor: flushing ? 'not-allowed' : 'pointer',
                color: 'var(--text-danger)', background: 'transparent',
                border: '1px solid var(--text-danger)66',
              }}
            >
              {flushing ? 'Flushing…' : '🗑 Flush queue'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
