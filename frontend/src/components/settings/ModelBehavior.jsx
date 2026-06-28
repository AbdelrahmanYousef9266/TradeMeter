const RANK_ORDER = ['Rookie', 'Apprentice', 'Pro', 'Elite', 'Expert', 'Master']

function rankGte(a, b) {
  return RANK_ORDER.indexOf(a) >= RANK_ORDER.indexOf(b)
}

const SETTING_META = {
  min_confidence:          { label: 'Min Confidence',           type: 'slider', min: 0.50, max: 0.95, step: 0.01, requiredRank: 'Apprentice' },
  max_signals_per_session: { label: 'Max Signals / Session',    type: 'slider', min: 1,    max: 60,   step: 1,    requiredRank: 'Apprentice' },
  signal_mode:             { label: 'Signal Mode',              type: 'radio',  options: ['aggressive', 'balanced', 'conservative'], requiredRank: 'Pro' },
  learning_rate:           { label: 'Learning Rate',            type: 'slider', min: 0.001, max: 0.5,  step: 0.001, requiredRank: 'Expert' },
  target_multiplier:       { label: 'Target Multiplier',        type: 'slider', min: 1.0,  max: 4.0,  step: 0.1,   requiredRank: 'Expert' },
  volume_spike_threshold:  { label: 'Volume Spike Threshold',   type: 'slider', min: 1.0,  max: 5.0,  step: 0.1,   requiredRank: 'Pro' },
  consensus_threshold:     { label: 'Consensus Threshold',      type: 'slider', min: 3,    max: 7,    step: 1,     requiredRank: 'Pro' },
  rsi_oversold:            { label: 'RSI Oversold',             type: 'slider', min: 15,   max: 40,   step: 1,     requiredRank: 'Apprentice' },
  rsi_overbought:          { label: 'RSI Overbought',           type: 'slider', min: 60,   max: 85,   step: 1,     requiredRank: 'Apprentice' },
}

const inputStyle = {
  width: '100%', padding: '6px 10px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--surface-3)',
  color: 'var(--text-primary)',
}

export default function ModelBehavior({ settings = {}, localVals = {}, rank = 'Rookie', onChange }) {
  if (!settings || Object.keys(settings).length === 0) {
    return <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>No configurable settings.</p>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {Object.entries(settings).map(([key, meta]) => {
        const isLocked  = meta.locked
        const settMeta  = SETTING_META[key]
        const val       = localVals[key] ?? meta.value
        const reqRank   = meta.requires_rank

        return (
          <div key={key} style={{ opacity: isLocked ? 0.55 : 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                {settMeta?.label || key.replace(/_/g, ' ')}
              </label>
              {isLocked && (
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                  🔒 Reach {reqRank}
                </span>
              )}
            </div>

            {settMeta?.type === 'radio' ? (
              <div style={{ display: 'flex', gap: 8 }}>
                {settMeta.options.map(opt => {
                  const active = val === opt
                  return (
                    <button
                      key={opt}
                      disabled={isLocked}
                      onClick={() => !isLocked && onChange(key, opt)}
                      style={{
                        padding: '4px 12px', borderRadius: 6, fontSize: 12,
                        background: active ? 'var(--accent-dim)' : 'var(--surface-3)',
                        color:      active ? 'var(--accent)'     : 'var(--text-secondary)',
                        border:     active ? '1px solid var(--accent)' : '1px solid var(--border)',
                        cursor: isLocked ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {opt}
                    </button>
                  )
                })}
              </div>
            ) : settMeta?.type === 'slider' ? (
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <input
                  type="range"
                  min={settMeta.min}
                  max={settMeta.max}
                  step={settMeta.step}
                  value={val}
                  disabled={isLocked}
                  onChange={e => !isLocked && onChange(key, parseFloat(e.target.value))}
                  style={{ flex: 1, accentColor: 'var(--accent)' }}
                />
                <span style={{ fontSize: 12, color: 'var(--text-primary)', minWidth: 36, textAlign: 'right' }}>
                  {typeof val === 'number' ? val.toFixed(2) : val}
                </span>
              </div>
            ) : (
              <input
                type="text"
                value={val ?? ''}
                disabled={isLocked}
                onChange={e => !isLocked && onChange(key, e.target.value)}
                style={{ ...inputStyle, cursor: isLocked ? 'not-allowed' : 'text' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
