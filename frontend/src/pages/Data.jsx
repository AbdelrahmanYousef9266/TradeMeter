import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { getDataSummary, getDataDays } from '../services/api'

// Completeness thresholds (bars/day). A near-full RTH session is ~390 1-min bars;
// the backend calls a day "complete" at >= 370. We reuse the same buckets here.
const FULL_DAY   = 370
const PARTIAL_DAY = 200
const EXPECTED_TRADING_DAYS = 21   // ≈ weekdays per month, minus holidays (approx.)

const GREEN  = '#1D9E75'
const AMBER  = '#E0912F'
const RED    = '#E24B4A'
const PURPLE = '#8b5cf6'   // training marker (matches the AFK "REPLAY" accent)

const card = {
  background: 'var(--surface-2)',
  border: '0.5px solid var(--border)',
  borderRadius: 12,
  padding: '14px 16px',
}

// Color by a bars-per-day figure (used for both the month bar and day cells).
function completenessColor(bars) {
  if (bars >= FULL_DAY)    return GREEN
  if (bars >= PARTIAL_DAY) return AMBER
  return RED
}

function monthLabel(ym) {
  const [y, m] = ym.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('en-US', {
    month: 'long', year: 'numeric', timeZone: 'UTC',
  })
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}

function fmtTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

// Build a Sun→Sat calendar grid for one month, joined with the day data map.
function buildMonthWeeks(ym, daysMap) {
  const [y, m] = ym.split('-').map(Number)
  const first = new Date(Date.UTC(y, m - 1, 1))
  const last  = new Date(Date.UTC(y, m, 0))
  const cur = new Date(first)
  cur.setUTCDate(cur.getUTCDate() - cur.getUTCDay())   // back to Sunday

  const cells = []
  while (cur <= last || cells.length % 7 !== 0) {
    const iso = cur.toISOString().slice(0, 10)
    const dow = cur.getUTCDay()
    cells.push({
      date:    iso,
      dayNum:  cur.getUTCDate(),
      inMonth: cur.getUTCMonth() === m - 1,
      weekend: dow === 0 || dow === 6,
      day:     daysMap[iso] || null,
    })
    cur.setUTCDate(cur.getUTCDate() + 1)
  }
  return cells
}

export default function Data() {
  const [summary, setSummary]   = useState(null)
  const [loading, setLoading]   = useState(true)
  const [expanded, setExpanded] = useState(null)          // month string or null
  const [daysByMonth, setDaysByMonth] = useState({})      // { 'YYYY-MM': {days, ...} }
  const expandedRef = useRef(null)
  expandedRef.current = expanded

  const fetchDays = useCallback((month) => {
    getDataDays(month)
      .then(res => setDaysByMonth(prev => ({ ...prev, [month]: res.data })))
      .catch(() => {})
  }, [])

  const refresh = useCallback(() => {
    getDataSummary()
      .then(res => { setSummary(res.data); setLoading(false) })
      .catch(() => setLoading(false))
    // Keep the open month fresh during an active import.
    if (expandedRef.current) fetchDays(expandedRef.current)
  }, [fetchDays])

  // Initial load + 30s auto-refresh (updates live during an import).
  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 30000)
    return () => clearInterval(id)
  }, [refresh])

  const toggleMonth = (month) => {
    if (expanded === month) { setExpanded(null); return }
    setExpanded(month)
    if (!daysByMonth[month]) fetchDays(month)
  }

  const header = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
      <Link to="/dashboard" style={{ color: 'var(--text-secondary)', fontSize: 13 }}>← Dashboard</Link>
      <h1 style={{ fontSize: 17, fontWeight: 500 }}>Data</h1>
    </div>
  )

  if (loading) {
    return (
      <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 16px' }}>
        {header}
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Loading data inventory…</div>
      </div>
    )
  }

  const hasData = summary && summary.total_raw_rows > 0

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 16px' }}>
      {header}

      {!hasData ? (
        <div style={{ ...card, textAlign: 'center', padding: '40px 16px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 28, marginBottom: 8 }}>📭</div>
          <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 4 }}>No market data yet</div>
          <div style={{ fontSize: 12 }}>Connect NinjaTrader or run a training import to start collecting bars.</div>
        </div>
      ) : (
        <>
          <SummaryRow summary={summary} />
          <MonthsTable
            summary={summary}
            expanded={expanded}
            daysByMonth={daysByMonth}
            onToggle={toggleMonth}
          />
          <Legend />
        </>
      )}
    </div>
  )
}

// ── Summary stats row ───────────────────────────────────────────────────────

function SummaryRow({ summary }) {
  const totalDays = (summary.months || []).reduce((s, m) => s + m.days, 0)
  const rangeText = summary.date_range?.min
    ? `${fmtDate(summary.date_range.min)} → ${fmtDate(summary.date_range.max)}`
    : '—'
  return (
    <div style={{ ...card, marginBottom: 12, display: 'flex', gap: 28, flexWrap: 'wrap' }}>
      <Stat value={summary.total_bars.toLocaleString()} label="Unique bars" />
      <Stat value={totalDays.toLocaleString()} label="Days covered" />
      <Stat value={rangeText} label="Date range" small />
      <Stat
        value={<><span style={{ color: GREEN }}>{summary.live_bars.toLocaleString()}</span>
          <span style={{ color: 'var(--text-muted)' }}> / </span>
          <span style={{ color: PURPLE }}>{summary.training_bars.toLocaleString()}</span></>}
        label="Live / Training"
      />
      <Stat value={`${summary.storage_estimate_mb} MB`} label="Est. storage" />
      <Stat value={summary.instrument || '—'} label="Instrument" />
    </div>
  )
}

function Stat({ value, label, small }) {
  return (
    <div>
      <div style={{ fontSize: small ? 13 : 20, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.5 }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{label}</div>
    </div>
  )
}

// ── Months table ────────────────────────────────────────────────────────────

function MonthsTable({ summary, expanded, daysByMonth, onToggle }) {
  const months = [...(summary.months || [])].reverse()   // newest first
  return (
    <div style={{ ...card, marginBottom: 12, padding: 0, overflow: 'hidden' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: '1.4fr 0.9fr 0.8fr 0.9fr 1.4fr 1fr',
        gap: 8, padding: '10px 16px', fontSize: 10, fontWeight: 600,
        letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-muted)',
        borderBottom: '0.5px solid var(--border)',
      }}>
        <span>Month</span><span>Days</span><span>Bars</span><span>Avg/day</span>
        <span>Completeness</span><span>Type</span>
      </div>

      {months.map(m => {
        const avg = m.days > 0 ? Math.round(m.bars / m.days) : 0
        const color = completenessColor(avg)
        const isOpen = expanded === m.month
        return (
          <div key={m.month}>
            <div
              onClick={() => onToggle(m.month)}
              style={{
                display: 'grid', gridTemplateColumns: '1.4fr 0.9fr 0.8fr 0.9fr 1.4fr 1fr',
                gap: 8, padding: '11px 16px', alignItems: 'center', cursor: 'pointer',
                fontSize: 13, borderBottom: '0.5px solid var(--border-subtle)',
                background: isOpen ? 'var(--surface-1)' : 'transparent',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: 'var(--text-muted)', fontSize: 10, width: 8 }}>{isOpen ? '▾' : '▸'}</span>
                {monthLabel(m.month)}
              </span>
              <span style={{ color: 'var(--text-secondary)' }}>{m.days} / {EXPECTED_TRADING_DAYS}</span>
              <span style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>{m.bars.toLocaleString()}</span>
              <span style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>{avg.toLocaleString()}</span>
              <CompletenessBar avg={avg} color={color} />
              <span style={{ display: 'flex', gap: 4 }}>
                {m.live_bars > 0     && <Badge color={GREEN}  text="live" />}
                {m.training_bars > 0 && <Badge color={PURPLE} text="train" />}
              </span>
            </div>

            {isOpen && (
              <div style={{ padding: '12px 16px 16px', background: 'var(--surface-1)', borderBottom: '0.5px solid var(--border-subtle)' }}>
                <MonthDayGrid month={m.month} data={daysByMonth[m.month]} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function CompletenessBar({ avg, color }) {
  const pct = Math.min(100, Math.round((avg / 390) * 100))
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'var(--surface-0)', overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
    </div>
  )
}

function Badge({ color, text }) {
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 600, padding: '1px 6px', borderRadius: 4,
      background: `${color}22`, color, letterSpacing: '0.03em',
    }}>{text}</span>
  )
}

// ── Per-month day grid (drill-down) ─────────────────────────────────────────

const WEEKDAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

function MonthDayGrid({ month, data }) {
  if (!data) return <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading days…</div>

  const daysMap = {}
  ;(data.days || []).forEach(d => { daysMap[d.date] = d })
  const cells = buildMonthWeeks(month, daysMap)

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4, maxWidth: 320 }}>
        {WEEKDAY_LABELS.map((w, i) => (
          <div key={i} style={{ fontSize: 9, textAlign: 'center', color: 'var(--text-muted)', paddingBottom: 2 }}>{w}</div>
        ))}
        {cells.map((c, i) => <DayCell key={i} cell={c} />)}
      </div>
    </div>
  )
}

function DayCell({ cell }) {
  if (!cell.inMonth) return <div />

  const d = cell.day
  let bg = 'transparent'
  let ring = 'none'
  let textColor = 'var(--text-muted)'
  let title = cell.date

  if (d) {
    const c = completenessColor(d.bars)
    bg = `${c}33`
    textColor = c
    if (d.kind === 'training' || d.kind === 'mixed') ring = `inset 0 0 0 1.5px ${PURPLE}`
    title = `${cell.date} · ${d.bars.toLocaleString()} bars · ${d.kind}` +
            `${d.is_complete ? ' · complete' : ''}\n${fmtTime(d.first_bar)}–${fmtTime(d.last_bar)}`
  } else if (cell.weekend) {
    bg = 'var(--surface-2)'   // weekend, no data expected — muted
    title = `${cell.date} · weekend`
  } else {
    bg = `${RED}1f`           // missing weekday — gap the user should see
    title = `${cell.date} · no data (gap)`
  }

  return (
    <div
      title={title}
      style={{
        height: 34, borderRadius: 5, background: bg, boxShadow: ring,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, fontVariantNumeric: 'tabular-nums', color: textColor,
      }}
    >
      {cell.dayNum}
    </div>
  )
}

// ── Legend ──────────────────────────────────────────────────────────────────

function Legend() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', fontSize: 11, color: 'var(--text-muted)', padding: '4px 4px' }}>
      <span>Completeness:</span>
      <LegendChip color={GREEN} label={`full (≥${FULL_DAY})`} />
      <LegendChip color={AMBER} label={`partial (${PARTIAL_DAY}–${FULL_DAY})`} />
      <LegendChip color={RED}   label={`sparse (<${PARTIAL_DAY})`} />
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ width: 12, height: 12, borderRadius: 4, background: `${RED}1f` }} /> missing weekday
      </span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ width: 12, height: 12, borderRadius: 4, boxShadow: `inset 0 0 0 1.5px ${PURPLE}` }} /> training / mixed
      </span>
      <span style={{ marginLeft: 4 }}>· “Days N / {EXPECTED_TRADING_DAYS}” uses ≈{EXPECTED_TRADING_DAYS} expected trading days/month (approx.)</span>
    </div>
  )
}

function LegendChip({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 12, height: 12, borderRadius: 4, background: `${color}33`, boxShadow: `inset 0 0 0 1px ${color}` }} />
      {label}
    </span>
  )
}
