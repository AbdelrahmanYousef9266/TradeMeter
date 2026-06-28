const BAR_TYPES = ['1min', '3min', '5min', 'tick']

const label = {
  display: 'block', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6,
}

export default function StrategyConfig({ settings = {}, onChange }) {
  const update = (key, val) => onChange({ ...settings, [key]: val })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <label style={label}>Instrument</label>
        <input
          type="text"
          value={settings.instrument || ''}
          onChange={e => update('instrument', e.target.value)}
          placeholder="e.g. MES 03-25"
          style={{ width: '100%' }}
        />
      </div>

      <div>
        <label style={label}>Bar Type</label>
        <div style={{ display: 'flex', gap: 8 }}>
          {BAR_TYPES.map(bt => {
            const active = settings.barType === bt
            return (
              <button
                key={bt}
                onClick={() => update('barType', bt)}
                style={{
                  padding: '5px 12px', borderRadius: 7, fontSize: 12,
                  background: active ? 'var(--accent-dim)' : 'var(--surface-3)',
                  color:      active ? 'var(--accent)'     : 'var(--text-secondary)',
                  border:     active ? '1px solid var(--accent)' : '1px solid var(--border)',
                  fontWeight: active ? 500 : 400,
                }}
              >
                {bt}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
