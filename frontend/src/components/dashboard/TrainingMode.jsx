import { useEffect, useState, useCallback } from 'react'
import { startTraining, stopTraining, getTrainingStatus } from '../../services/api'

// Distinct purple accent so training mode is never confused with live (green).
const ACCENT = '#7c5cff'

/**
 * Training Mode control + banner.
 *
 * Toggles the per-user backend flag that bypasses the live monotonic watermark
 * and isolates replayed historical data (is_training). While active it shows a
 * loud banner and a live counter of bars/sessions ingested this run.
 */
export default function TrainingMode() {
  const [training, setTraining] = useState(false)
  const [bars, setBars]         = useState(0)
  const [sessions, setSessions] = useState(0)
  const [busy, setBusy]         = useState(false)

  const applyStatus = useCallback((d) => {
    if (!d) return
    setTraining(!!d.training)
    setBars(d.bars_ingested ?? 0)
    setSessions(d.sessions_ingested ?? 0)
  }, [])

  // Hydrate once, then poll while active so the counter climbs during replay.
  useEffect(() => {
    getTrainingStatus().then(r => applyStatus(r.data)).catch(() => {})
  }, [applyStatus])

  useEffect(() => {
    if (!training) return
    const id = setInterval(() => {
      getTrainingStatus().then(r => applyStatus(r.data)).catch(() => {})
    }, 2000)
    return () => clearInterval(id)
  }, [training, applyStatus])

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

  return (
    <div style={{ marginBottom: 12 }}>
      {training && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, marginBottom: 8, padding: '10px 14px', borderRadius: 10,
          background: `${ACCENT}1a`, border: `1px solid ${ACCENT}66`,
          borderLeft: `3px solid ${ACCENT}`,
        }}>
          <span style={{ fontSize: 13, color: ACCENT, fontWeight: 500 }}>
            🎓 TRAINING MODE — replaying historical data, learning enabled, live watermark paused
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
            {bars.toLocaleString()} bars · {sessions} session{sessions === 1 ? '' : 's'} this run
          </span>
        </div>
      )}

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
    </div>
  )
}
