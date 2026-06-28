const INDICATORS = [
  { key: 'rsi',         label: 'RSI (14)'     },
  { key: 'ema9',        label: 'EMA (9)'      },
  { key: 'ema21',       label: 'EMA (21)'     },
  { key: 'ema50',       label: 'EMA (50)'     },
  { key: 'macd',        label: 'MACD'         },
  { key: 'atr',         label: 'ATR (14)'     },
  { key: 'volumeDelta', label: 'Volume Delta' },
]

export default function IndicatorToggles({ indicators = {}, onChange }) {
  const toggle = (key) => onChange({ ...indicators, [key]: !indicators[key] })

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {INDICATORS.map(({ key, label }) => {
        const on = !!indicators[key]
        return (
          <button
            key={key}
            onClick={() => toggle(key)}
            style={{
              padding: '5px 12px', borderRadius: 7, fontSize: 12,
              background: on ? 'var(--accent-dim)' : 'var(--surface-3)',
              color:      on ? 'var(--accent)'     : 'var(--text-secondary)',
              border:     on ? '1px solid var(--accent)' : '1px solid var(--border)',
              fontWeight: on ? 500 : 400,
            }}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
