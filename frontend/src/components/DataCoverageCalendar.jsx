import { useEffect, useState, useMemo } from 'react'
import { getDataCoverage } from '../services/api'

export default function DataCoverageCalendar() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getDataCoverage()
      .then(res => { setData(res.data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const { weeks, maxBars } = useMemo(() => {
    if (!data || !data.days || data.days.length === 0) {
      return { weeks: [], maxBars: 1 }
    }

    const barsByDate = {}
    data.days.forEach(d => { barsByDate[d.date] = d.bars })
    const maxBars = Math.max(...data.days.map(d => d.bars), 1)
    const trainedSet = new Set(data.trained_days || [])

    // Build a continuous range from first to last day.
    // All date math is done in UTC so the week grid stays aligned regardless of
    // the viewer's local timezone (dates from the API are UTC-day buckets).
    const start = new Date(data.days[0].date + 'T00:00:00Z')
    const end   = new Date(data.days[data.days.length - 1].date + 'T00:00:00Z')

    // Align start to the Sunday of its week
    const cur = new Date(start)
    cur.setUTCDate(cur.getUTCDate() - cur.getUTCDay())

    const weeks = []
    while (cur <= end) {
      const week = []
      for (let i = 0; i < 7; i++) {
        const iso = cur.toISOString().slice(0, 10)
        week.push({
          date: iso,
          bars: barsByDate[iso] ?? 0,
          trained: trainedSet.has(iso),
          inRange: cur >= start && cur <= end,
        })
        cur.setUTCDate(cur.getUTCDate() + 1)
      }
      weeks.push(week)
    }
    return { weeks, maxBars }
  }, [data])

  if (loading) return <div style={{ fontSize:'13px', color:'var(--text-muted)' }}>Loading coverage…</div>
  if (!data || data.days?.length === 0) {
    return <div style={{ fontSize:'13px', color:'var(--text-muted)' }}>No data collected yet. Connect NinjaTrader and start streaming bars.</div>
  }

  const intensity = (bars) => {
    if (bars === 0) return 'var(--surface-1)'
    const ratio = bars / maxBars
    if (ratio > 0.75) return '#1D9E75'
    if (ratio > 0.5)  return '#1D9E75cc'
    if (ratio > 0.25) return '#1D9E75aa'
    return '#1D9E7566'
  }

  return (
    <div>
      {/* Summary stats */}
      <div style={{ display:'flex', gap:'24px', marginBottom:'20px', flexWrap:'wrap' }}>
        <Stat value={data.total_days} label="Days collected" />
        <Stat value={data.total_bars.toLocaleString()} label="Total bars" />
        <Stat value={(data.trained_days?.length ?? 0)} label="Days LSTM trained" />
        <Stat value={data.instrument} label="Instrument" />
      </div>

      {/* Calendar heatmap */}
      <div style={{ display:'flex', gap:'3px', overflowX:'auto', paddingBottom:'8px' }}>
        {weeks.map((week, wi) => (
          <div key={wi} style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
            {week.map((day, di) => (
              <div
                key={di}
                title={day.inRange
                  ? `${day.date} · ${day.bars.toLocaleString()} bars${day.trained ? ' · LSTM trained' : ''}`
                  : ''}
                style={{
                  width:'14px', height:'14px', borderRadius:'3px',
                  background: day.inRange ? intensity(day.bars) : 'transparent',
                  boxShadow: day.trained ? '0 0 0 1.5px var(--text-primary)' : 'none',
                }}
              />
            ))}
          </div>
        ))}
      </div>

      {/* Legend */}
      <div style={{ display:'flex', alignItems:'center', gap:'6px', marginTop:'16px', fontSize:'11px', color:'var(--text-muted)' }}>
        <span>Less</span>
        <div style={{ width:'12px', height:'12px', borderRadius:'3px', background:'var(--surface-1)' }} />
        <div style={{ width:'12px', height:'12px', borderRadius:'3px', background:'#1D9E7566' }} />
        <div style={{ width:'12px', height:'12px', borderRadius:'3px', background:'#1D9E75aa' }} />
        <div style={{ width:'12px', height:'12px', borderRadius:'3px', background:'#1D9E75' }} />
        <span>More</span>
        <span style={{ marginLeft:'16px' }}>·</span>
        <div style={{ width:'12px', height:'12px', borderRadius:'3px', background:'var(--surface-2)', boxShadow:'0 0 0 1.5px var(--text-primary)' }} />
        <span>LSTM trained that day</span>
      </div>
    </div>
  )
}

function Stat({ value, label }) {
  return (
    <div>
      <div style={{ fontSize:'20px', fontWeight:600, color:'var(--text-primary)' }}>{value}</div>
      <div style={{ fontSize:'11px', color:'var(--text-muted)' }}>{label}</div>
    </div>
  )
}
