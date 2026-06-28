export default function ModelMetrics({ levelInfo, modelHistory = [] }) {
  const totalPredictions = modelHistory.length
  const correct = modelHistory.filter(h =>
    (h.signal === 'BUY'  && h.actual_outcome === 'up') ||
    (h.signal === 'SELL' && h.actual_outcome === 'down')
  ).length
  const accuracy = totalPredictions > 0 ? correct / totalPredictions : null

  const rows = [
    { label: 'Rolling Accuracy', value: accuracy != null ? `${(accuracy * 100).toFixed(1)}%` : '—' },
    { label: 'Bars Learned',     value: levelInfo?.bars_learned ?? '—' },
    { label: 'Current Streak',   value: levelInfo?.streak ?? '—' },
    { label: 'Total Predictions',value: totalPredictions || '—' },
  ]

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {rows.map(({ label, value }) => (
        <div key={label} style={{
          background: 'var(--surface-3)', borderRadius: 8, padding: '8px 12px',
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginBottom: 3 }}>{label}</div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>{value}</div>
        </div>
      ))}
    </div>
  )
}
