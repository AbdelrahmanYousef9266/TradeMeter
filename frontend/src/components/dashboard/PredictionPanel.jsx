const SIGNAL_COLORS = {
  BUY:  { text: 'var(--text-success)', bg: 'var(--bg-success)' },
  SELL: { text: 'var(--text-danger)',  bg: 'var(--bg-danger)'  },
  HOLD: { text: 'var(--text-warning)', bg: 'var(--bg-warning)' },
}

export default function PredictionPanel({ signal, modelName }) {
  if (!signal) {
    return (
      <div style={{
        background: 'var(--surface-3)', borderRadius: 10, padding: '12px 14px',
        color: 'var(--text-secondary)', fontSize: 12, textAlign: 'center',
      }}>
        No prediction yet
      </div>
    )
  }

  const { signal: sig, confidence, direction_up, predicted_high, predicted_low } = signal
  const colors = SIGNAL_COLORS[sig] || SIGNAL_COLORS.HOLD
  const upPct  = Math.round((direction_up ?? 0.5) * 100)

  return (
    <div style={{
      background: 'var(--surface-3)', borderRadius: 10, padding: '12px 14px',
    }}>
      {/* Signal badge */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{
          fontSize: 13, fontWeight: 500, padding: '3px 10px', borderRadius: 6,
          background: colors.bg, color: colors.text,
        }}>
          {sig} {Math.round((confidence ?? 0) * 100)}%
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          {modelName?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
        </span>
      </div>

      {/* Direction bar */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4 }}>
          <span>↓ {100 - upPct}%</span>
          <span>↑ {upPct}%</span>
        </div>
        <div style={{ height: 6, background: 'var(--bg-danger)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${upPct}%`,
            background: 'var(--text-success)', borderRadius: 3,
          }} />
        </div>
      </div>

      {/* Targets */}
      {(predicted_high || predicted_low) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 10, marginBottom: 2 }}>Target High</div>
            <div style={{ color: 'var(--text-success)' }}>{predicted_high?.toFixed(2) ?? '—'}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: 'var(--text-secondary)', fontSize: 10, marginBottom: 2 }}>Target Low</div>
            <div style={{ color: 'var(--text-danger)' }}>{predicted_low?.toFixed(2) ?? '—'}</div>
          </div>
        </div>
      )}
    </div>
  )
}
