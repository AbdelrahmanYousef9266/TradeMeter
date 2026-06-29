import {
  ComposedChart, Bar, Line, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import useStore from '../../store'

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// Custom candlestick shape — uses `background` prop (full chart area bounds)
// and a domain closure to compute wicks in SVG coords.
function makeCandleShape(domainMin, domainMax) {
  return function CandleShape(props) {
    const { x, width, payload, background } = props
    if (!payload || !background || !background.height) return null

    const { open, close, high, low } = payload
    if ([open, close, high, low].some(v => v == null)) return null

    const pRange = domainMax - domainMin
    if (pRange === 0) return null

    const toY = (price) =>
      background.y + background.height * (1 - (price - domainMin) / pRange)

    const isUp    = close >= open
    const clrKey  = isUp ? 'var(--text-success)' : 'var(--text-danger)'
    const midX    = x + width / 2
    const bodyY1  = toY(Math.max(open, close))
    const bodyY2  = toY(Math.min(open, close))
    const wickTop = toY(high)
    const wickBot = toY(low)
    const bodyH   = Math.max(bodyY2 - bodyY1, 1.5)
    const bWidth  = Math.max(width - 2, 1)

    return (
      <g>
        {/* High-low wick */}
        <line
          x1={midX} y1={wickTop} x2={midX} y2={wickBot}
          style={{ stroke: clrKey }} strokeWidth={1}
        />
        {/* Body */}
        <rect
          x={x + 1} y={bodyY1}
          width={bWidth} height={bodyH}
          style={{ fill: clrKey }}
        />
      </g>
    )
  }
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.[0]) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: 'var(--surface-2)', border: '0.5px solid var(--border)',
      borderRadius: 8, padding: '8px 12px', fontSize: 12,
    }}>
      <p style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>{d.timeLabel}</p>
      {['open', 'high', 'low', 'close'].map(k => (
        <p key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span style={{ color: 'var(--text-secondary)', textTransform: 'uppercase' }}>{k}</span>
          <span style={{ color: 'var(--text-primary)' }}>{d[k]?.toFixed(2)}</span>
        </p>
      ))}
    </div>
  )
}

export default function LiveChart({ bars = [], style = {} }) {
  const settings = useStore(s => s.settings)
  const warmup   = useStore(s => s.warmup)
  const { ema9, ema21, ema50 } = settings.indicators

  // ── Empty states ─────────────────────────────────────────────────────────

  if (!warmup.ntConnected && bars.length === 0) {
    return (
      <div style={{
        background: 'var(--surface-2)', border: '0.5px solid var(--border)',
        borderRadius: 12, height: 380, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 10, ...style,
      }}>
        <span style={{ fontSize: 26 }}>📡</span>
        <p style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)', margin: 0 }}>
          Waiting for NinjaTrader
        </p>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: 0 }}>
          {import.meta.env.VITE_MOCK_WS === 'true'
            ? 'Mock mode active — bars arrive every 2s'
            : 'Enable TradeMeterFeed strategy on your chart'}
        </p>
      </div>
    )
  }

  if (warmup.ntConnected && warmup.isWarmingUp) {
    const pct      = Math.min(Math.round((warmup.barsReceived / warmup.barsNeeded) * 100), 100)
    const barsLeft = Math.max(warmup.barsNeeded - warmup.barsReceived, 0)
    return (
      <div style={{
        background: 'var(--surface-2)', border: '0.5px solid var(--border)',
        borderRadius: 12, height: 380, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 16, ...style,
      }}>
        <span style={{ fontSize: 26 }}>🧠</span>
        <p style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)', margin: 0 }}>
          Warming up — collecting historical bars
        </p>

        <div style={{ width: 280 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            fontSize: 12, color: 'var(--text-muted)', marginBottom: 6,
          }}>
            <span>{warmup.barsReceived} bars received</span>
            <span>{warmup.barsNeeded} needed</span>
          </div>
          <div style={{
            height: 8, background: 'var(--surface-1)',
            borderRadius: 4, overflow: 'hidden',
          }}>
            <div style={{
              height: 8, width: `${pct}%`,
              background: 'var(--accent)',
              borderRadius: 4, transition: 'width 0.3s ease',
            }} />
          </div>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, textAlign: 'center' }}>
            {barsLeft > 0
              ? `${barsLeft} more bar${barsLeft === 1 ? '' : 's'} until predictions start`
              : 'Starting predictions now…'}
          </p>
        </div>

        <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0 }}>
          💡 Speed up NinjaTrader playback to reach 50 bars faster
        </p>
      </div>
    )
  }

  // ── Chart data ────────────────────────────────────────────────────────────

  const chartData = bars.map(b => ({
    timeLabel:    formatTime(b.time),
    open:         b.open,
    high:         b.high,
    low:          b.low,
    close:        b.close,
    volume:       b.volume,
    ema_9:        b.features?.ema_9,
    ema_21:       b.features?.ema_21,
    ema_50:       b.features?.ema_50,
    // dataKey for the Bar — use full [low, high] range so Recharts sizes bars correctly
    priceRange:   b.low != null && b.high != null ? [b.low, b.high] : null,
  })).filter(d => d.priceRange)

  if (chartData.length === 0) {
    return (
      <div style={{
        background: 'var(--surface-2)', border: '0.5px solid var(--border)',
        borderRadius: 12, height: 380, display: 'flex', alignItems: 'center',
        justifyContent: 'center', ...style,
      }}>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
          Connected — waiting for first bar close…
        </p>
      </div>
    )
  }

  const allLows  = chartData.map(d => d.low)
  const allHighs = chartData.map(d => d.high)
  const yMin     = Math.min(...allLows)  * 0.9996
  const yMax     = Math.max(...allHighs) * 1.0004

  const CandleShape = makeCandleShape(yMin, yMax)

  return (
    <div style={{
      background: 'var(--surface-2)', border: '0.5px solid var(--border)',
      borderRadius: 12, overflow: 'hidden', ...style,
    }}>
      {/* Price chart */}
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={chartData} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border-subtle)"
            strokeOpacity={0.5}
            vertical={false}
          />
          <XAxis
            dataKey="timeLabel"
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            axisLine={{ stroke: 'var(--border)' }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={40}
          />
          <YAxis
            domain={[yMin, yMax]}
            tick={{ fill: 'var(--text-secondary)', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={v => v.toFixed(1)}
            width={52}
            orientation="right"
          />
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'var(--border)', strokeWidth: 1 }} />

          {/* Candles — Bar renders the priceRange extent; shape draws wicks + body */}
          <Bar
            dataKey="priceRange"
            shape={<CandleShape />}
            isAnimationActive={false}
            maxBarSize={12}
          />

          {/* EMA overlays */}
          {ema9  && <Line dataKey="ema_9"  stroke="#3b82f6" strokeWidth={1.2} dot={false} isAnimationActive={false} connectNulls />}
          {ema21 && <Line dataKey="ema_21" stroke="#f97316" strokeWidth={1.2} dot={false} isAnimationActive={false} connectNulls />}
          {ema50 && <Line dataKey="ema_50" stroke="#ef4444" strokeWidth={1.2} dot={false} isAnimationActive={false} connectNulls />}
        </ComposedChart>
      </ResponsiveContainer>

      {/* Volume strip */}
      <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 2 }}>
        <ResponsiveContainer width="100%" height={60}>
          <ComposedChart data={chartData} margin={{ top: 0, right: 10, bottom: 4, left: 0 }}>
            <XAxis dataKey="timeLabel" hide />
            <YAxis hide />
            <Bar
              dataKey="volume"
              maxBarSize={12}
              isAnimationActive={false}
              fill="var(--text-secondary)"
              opacity={0.35}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
