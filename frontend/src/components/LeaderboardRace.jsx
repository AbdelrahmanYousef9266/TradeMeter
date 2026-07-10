import useStore from '../store'

const MODEL_META = {
  scalper:        { label: 'Scalper',        abbr: 'SC', color: '#3B82C4' },
  momentum:       { label: 'Momentum',       abbr: 'MO', color: '#1D9E75' },
  mean_reversion: { label: 'Mean Reversion', abbr: 'MR', color: '#D85A30' },
  breakout:       { label: 'Breakout',       abbr: 'BR', color: '#BA7517' },
  conservative:   { label: 'Conservative',   abbr: 'CO', color: '#639922' },
  aggressive:     { label: 'Aggressive',     abbr: 'AG', color: '#E24B4A' },
  volume:         { label: 'Volume',         abbr: 'VO', color: '#7F77DD' },
  contrarian:     { label: 'Contrarian',     abbr: 'CN', color: '#D4537E' },
  personal:       { label: 'Secret',         abbr: 'SE', color: '#378ADD' },
  lstm:           { label: 'Deep LSTM',      abbr: 'DL', color: '#534AB7' },
}

const MODEL_NAMES = Object.keys(MODEL_META)
export default function LeaderboardRace({ compact = false }) {
  const { modelPnl } = useStore()

  const ROW_HEIGHT = compact ? 30 : 44   // smaller rows in compact (AFK) mode

  // Build a stable list of models with their current P&L (primary 5-min series).
  const models = MODEL_NAMES.map(name => ({
    name,
    meta: MODEL_META[name],
    pnl: modelPnl[`${name}:5min`]?.points ?? 0,
    wins: modelPnl[`${name}:5min`]?.wins ?? 0,
    losses: modelPnl[`${name}:5min`]?.losses ?? 0,
  }))

  // Sort by P&L descending to get current ranking
  const ranked = [...models].sort((a, b) => b.pnl - a.pnl)

  // Compute the rank (Y position) of each model by name
  const rankByName = {}
  ranked.forEach((m, i) => { rankByName[m.name] = i })

  // Max absolute P&L for bar scaling
  const maxAbs = Math.max(...models.map(m => Math.abs(m.pnl)), 1)

  return (
    <div style={{ width: '100%', height: compact ? '100%' : 'auto', display: 'flex', flexDirection: 'column' }}>
      {!compact && (
        <>
          <div style={{
            fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)',
            marginBottom: '4px'
          }}>
            Leaderboard race
          </div>
          <div style={{
            fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px'
          }}>
            Models ranked by session P&L — they slide as ranks change
          </div>
        </>
      )}
      {compact && (
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', flexShrink: 0 }}>
          Leaderboard race
        </div>
      )}

      {/* Track — height fits all rows */}
      <div style={{ position: 'relative', height: `${MODEL_NAMES.length * ROW_HEIGHT}px`, flexShrink: 0 }}>
        {models.map(m => {
          const rank = rankByName[m.name]
          const pct = Math.max((Math.abs(m.pnl) / maxAbs) * 100, 3)
          const isLeader = rank === 0 && m.pnl > 0
          const pnlColor = m.pnl > 0 ? 'var(--text-success)'
                         : m.pnl < 0 ? 'var(--text-danger)'
                         : 'var(--text-muted)'

          return (
            <div
              key={m.name}
              style={{
                position: 'absolute', left: 0, right: 0, height: `${ROW_HEIGHT - 4}px`,
                display: 'flex', alignItems: 'center', gap: compact ? '6px' : '10px',
                transform: `translateY(${rank * ROW_HEIGHT}px)`,
                transition: 'transform 0.9s cubic-bezier(0.4,0,0.2,1)',
                willChange: 'transform',
                padding: '0 4px',
                borderRadius: '8px',
                background: isLeader ? 'var(--bg-success)' : 'transparent',
              }}
            >
              {/* Rank number */}
              <span style={{
                width: compact ? '16px' : '24px', textAlign: 'center',
                fontSize: compact ? '11px' : '14px', fontWeight: 500,
                color: isLeader ? 'var(--text-success)' : 'var(--text-muted)', flexShrink: 0,
              }}>
                {rank + 1}
              </span>

              {/* Medal for top 3 — hidden in compact to save space */}
              {!compact && (
                <span style={{ width: '18px', fontSize: '13px', flexShrink: 0 }}>
                  {rank < 3 && m.pnl > 0 ? ['🥇','🥈','🥉'][rank] : ''}
                </span>
              )}

              {/* Avatar */}
              <div style={{
                width: compact ? '20px' : '28px', height: compact ? '20px' : '28px',
                borderRadius: compact ? '6px' : '8px', flexShrink: 0,
                background: m.meta.color + '22', color: m.meta.color,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: compact ? '8px' : '10px', fontWeight: 600,
              }}>
                {m.meta.abbr}
              </div>

              {/* Name */}
              <span style={{
                fontSize: compact ? '11px' : '13px', fontWeight: 500, color: 'var(--text-primary)',
                width: compact ? '78px' : '110px', flexShrink: 0, whiteSpace: 'nowrap',
                overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {m.meta.label}
              </span>

              {/* P&L bar */}
              <div style={{
                flex: 1, height: compact ? '14px' : '22px', background: 'var(--surface-1)',
                borderRadius: '6px', overflow: 'hidden',
              }}>
                <div style={{
                  height: compact ? '14px' : '22px', borderRadius: '6px',
                  width: `${pct}%`, background: m.meta.color,
                  opacity: m.pnl >= 0 ? 1 : 0.4,
                  transition: 'width 0.9s cubic-bezier(0.4,0,0.2,1)',
                }}/>
              </div>

              {/* W/L — hidden in compact */}
              {!compact && (
                <span style={{
                  fontSize: '11px', color: 'var(--text-muted)', width: '48px',
                  textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums',
                }}>
                  {m.wins}W {m.losses}L
                </span>
              )}

              {/* P&L value */}
              <span style={{
                fontSize: compact ? '11px' : '14px', fontWeight: 600,
                width: compact ? '48px' : '64px', textAlign: 'right',
                flexShrink: 0, color: pnlColor, fontVariantNumeric: 'tabular-nums',
                transition: 'color 0.3s',
              }}>
                {m.pnl > 0 ? '+' : ''}{m.pnl.toFixed(1)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
