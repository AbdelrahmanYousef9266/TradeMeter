import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts'

export default function VolumeBar({ data = [], height = 60 }) {
  if (!data.length) return null

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 0, right: 10, bottom: 0, left: 0 }}>
        <XAxis dataKey="timeLabel" hide />
        <YAxis hide />
        <Tooltip
          cursor={false}
          content={({ active, payload }) => {
            if (!active || !payload?.[0]) return null
            return (
              <div style={{
                background: 'var(--surface-2)', border: '0.5px solid var(--border)',
                borderRadius: 6, padding: '4px 8px', fontSize: 11,
                color: 'var(--text-secondary)',
              }}>
                Vol: {payload[0].value?.toLocaleString()}
              </div>
            )
          }}
        />
        <Bar
          dataKey="volume"
          maxBarSize={10}
          isAnimationActive={false}
          fill="var(--text-secondary)"
          opacity={0.35}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
