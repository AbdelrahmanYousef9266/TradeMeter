import { useState, useEffect, useCallback } from 'react'
import { getLSTMStatus, trainLSTM } from '../../services/api'

const ACCENT = '#1E8E6B'   // deep-learning green

function timeAgo(iso) {
  if (!iso) return null
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60)    return `${secs}s ago`
  if (secs < 3600)  return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

export default function LSTMCard({ signal, levelInfo }) {
  const [status,   setStatus]   = useState(null)
  const [training, setTraining] = useState(false)
  const [result,   setResult]   = useState(null)
  const [error,    setError]    = useState(null)

  const fetchStatus = useCallback(() => {
    getLSTMStatus()
      .then(r => setStatus(r.data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchStatus()
    const t = setInterval(fetchStatus, 30_000)
    return () => clearInterval(t)
  }, [fetchStatus])

  const handleTrain = async () => {
    setTraining(true)
    setError(null)
    setResult(null)
    try {
      const r = await trainLSTM()
      setResult(r.data)
      if (!r.data.success) setError(r.data.message || 'Training could not start')
      fetchStatus()
    } catch (e) {
      setError('Training failed — see server logs')
    } finally {
      setTraining(false)
    }
  }

  const dormant   = status ? status.is_dormant : true
  const isTrained = status?.is_trained
  const bars      = status?.bars_available ?? 0
  const needed    = status?.bars_needed ?? 2000
  const pct       = Math.max(0, Math.min(100, status?.progress_pct ?? 0))   // clamp 0–100
  const sigData   = signal && !dormant ? signal : null

  return (
    <div
      id="model-card-lstm"
      style={{
        background: 'var(--surface-2)',
        border: `0.5px solid ${dormant ? 'var(--border)' : `${ACCENT}55`}`,
        borderRadius: 12, padding: '12px 14px',
        display: 'flex', flexDirection: 'column', gap: 10,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7, flexShrink: 0,
            background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
          }}>
            🧬
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>Deep LSTM</div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>Sequence patterns · Model 11</div>
          </div>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 500, padding: '2px 7px', borderRadius: 5,
          background: dormant ? 'var(--surface-3)' : `${ACCENT}22`,
          color: dormant ? 'var(--text-secondary)' : ACCENT, flexShrink: 0,
        }}>
          {dormant ? 'Dormant' : isTrained ? 'Active' : 'Untrained'}
        </span>
      </div>

      {dormant ? (
        /* ── Dormant: collecting data ─────────────────────────────────── */
        <>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            🧬 Collecting data — {bars.toLocaleString()} / {needed.toLocaleString()} bars
          </div>
          <div style={{ height: 4, background: 'var(--surface-3)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${pct}%`, background: ACCENT,
              borderRadius: 2, transition: 'width 0.5s ease',
            }} />
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            {Math.max(0, needed - bars).toLocaleString()} more bars until activation
          </div>
          <button
            disabled
            style={{
              fontSize: 11, padding: '4px 10px', borderRadius: 6, alignSelf: 'flex-end',
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--text-tertiary)', cursor: 'not-allowed', opacity: 0.6,
            }}
          >
            Train now
          </button>
        </>
      ) : (
        /* ── Active: live signal + training meta ──────────────────────── */
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {sigData ? (
              <span style={{
                fontSize: 12, fontWeight: 500, padding: '3px 9px', borderRadius: 6, flexShrink: 0,
                background: sigData.signal === 'BUY' ? 'var(--bg-success)'
                          : sigData.signal === 'SELL' ? 'var(--bg-danger)' : 'var(--bg-warning)',
                color:      sigData.signal === 'BUY' ? 'var(--text-success)'
                          : sigData.signal === 'SELL' ? 'var(--text-danger)' : 'var(--text-warning)',
              }}>
                {sigData.signal} {Math.round((sigData.confidence ?? 0) * 100)}%
              </span>
            ) : (
              <span style={{
                fontSize: 12, padding: '3px 9px', borderRadius: 6,
                background: 'var(--surface-3)', color: 'var(--text-secondary)',
              }}>—</span>
            )}
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              Lv {levelInfo?.level ?? 1}
            </span>
          </div>

          <div style={{
            fontSize: 11, color: 'var(--text-secondary)', paddingTop: 8,
            borderTop: '1px solid var(--border-subtle)', lineHeight: 1.5,
          }}>
            {isTrained ? (
              <>
                Last trained: {timeAgo(status.last_trained) || '—'}
                {status.train_accuracy != null && (
                  <> · Val acc: {(status.train_accuracy * 100).toFixed(1)}%</>
                )}
                {status.train_samples != null && (
                  <> · {status.train_samples.toLocaleString()} samples</>
                )}
              </>
            ) : (
              <>Enough data — not yet trained. Click below to train.</>
            )}
          </div>

          {result?.success && (
            <div style={{ fontSize: 11, color: 'var(--text-success)' }}>
              ✓ Trained — val accuracy {(result.val_accuracy * 100).toFixed(1)}% on {result.train_samples.toLocaleString()} samples
            </div>
          )}
          {error && (
            <div style={{ fontSize: 11, color: 'var(--text-danger)' }}>{error}</div>
          )}

          <button
            onClick={handleTrain}
            disabled={training}
            style={{
              fontSize: 11, padding: '4px 10px', borderRadius: 6, alignSelf: 'flex-end',
              background: training ? 'var(--surface-3)' : 'transparent',
              border: `1px solid ${ACCENT}66`, color: ACCENT,
              cursor: training ? 'wait' : 'pointer',
            }}
          >
            {training ? 'Training… (up to a minute)' : isTrained ? 'Retrain' : 'Train now'}
          </button>
        </>
      )}
    </div>
  )
}
