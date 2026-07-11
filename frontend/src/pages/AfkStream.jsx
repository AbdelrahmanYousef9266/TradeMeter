import { useState, useEffect, useMemo, useRef } from 'react'
import useStore from '../store'
import {
  getSystemStats, getMode, getLSTMStatus, getIngestionStatus,
  armIngestion, disarmIngestion, setModeLive, setModeOffline,
} from '../services/api'
import ArchitectureDiagram from '../components/ArchitectureDiagram'
import SystemDesignDiagram from '../components/SystemDesignDiagram'
import LeaderboardRace from '../components/LeaderboardRace'
import TradeSignalPanel from '../components/dashboard/TradeSignalPanel'

// Monospace stack for the control-panel look.
const MONO = "ui-monospace, 'JetBrains Mono', 'SF Mono', 'Cascadia Code', Menlo, Consolas, monospace"

// Bar colors per resource.
const C_CPU = '#1D9E75'   // green
const C_RAM = '#378ADD'   // blue
const C_GPU = '#E0912F'   // amber

const MODEL_META = {
  scalper:        { label: 'Scalper',       color: '#3B82C4' },
  momentum:       { label: 'Momentum',      color: '#1D9E75' },
  mean_reversion: { label: 'Mean Reversion',color: '#D85A30' },
  breakout:       { label: 'Breakout',      color: '#BA7517' },
  conservative:   { label: 'Conservative',  color: '#639922' },
  aggressive:     { label: 'Aggressive',    color: '#E24B4A' },
  volume:         { label: 'Volume',        color: '#7F77DD' },
  contrarian:     { label: 'Contrarian',    color: '#D4537E' },
  personal:       { label: 'Secret',        color: '#378ADD' },
  lstm:           { label: 'Deep LSTM',     color: '#534AB7' },
}
const MODEL_NAMES = Object.keys(MODEL_META)

// US equity RTH: weekdays 09:30–16:00 ET. Uses the browser's Intl DB for an
// accurate ET conversion (handles DST) rather than a fixed offset.
function isMarketOpen() {
  const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const day = et.getDay()                 // 0 Sun … 6 Sat
  const mins = et.getHours() * 60 + et.getMinutes()
  return day >= 1 && day <= 5 && mins >= 570 && mins < 960
}

export default function AfkStream() {
  const { modelSignals, modelLevels, modelPnl, lastBarAt, currentBar } = useStore()

  const [sys, setSys]           = useState({ cpu_percent: 0, ram_used_gb: 0, ram_total_gb: 0, ram_percent: 0 })
  const [mode, setMode]         = useState('live')
  const training = mode === 'offline'   // OFFLINE mode == the old training mode
  const [trainQueue, setTrainQueue] = useState(0)
  const [lstm, setLstm]         = useState(null)
  const [ing, setIng]           = useState({ armed: false, queue_pending: 0 })
  const [symbol, setSymbol]     = useState(null)   // sticky instrument (e.g. "MES")
  const [lstmDoneAt, setLstmDoneAt] = useState(0)  // when LSTM last finished training
  const [gpu, setGpu]           = useState(38)   // decorative — see below
  const [now, setNow]           = useState(Date.now())

  // ── Poll real CPU/RAM every 2s ─────────────────────────────────────────
  useEffect(() => {
    let active = true
    const poll = () => getSystemStats().then(r => active && setSys(r.data)).catch(() => {})
    poll()
    const id = setInterval(poll, 2000)
    return () => { active = false; clearInterval(id) }
  }, [])

  // ── Poll system MODE every 2s (drives Task + AI Status + narration) ──────
  useEffect(() => {
    let active = true
    const poll = () => getMode().then(r => {
      if (!active) return
      setMode(r.data?.mode === 'offline' ? 'offline' : 'live')
      setTrainQueue(Math.max(0, r.data?.queue_pending ?? 0))   // never negative
    }).catch(() => {})
    poll()
    const id = setInterval(poll, 2000)
    return () => { active = false; clearInterval(id) }
  }, [])

  // ── Poll ingestion arm-gate status every 5s (drives armed/idle narration) ──
  useEffect(() => {
    let active = true
    const poll = () => getIngestionStatus().then(r => {
      if (!active) return
      const d = r.data || {}
      setIng({ armed: !!d.armed, queue_pending: Math.max(0, d.queue_pending ?? 0) })
    }).catch(() => {})
    poll()
    const id = setInterval(poll, 5000)
    return () => { active = false; clearInterval(id) }
  }, [])

  // ── Poll LSTM status every 5s (drives "Collecting Data" task) ──────────
  useEffect(() => {
    let active = true
    const poll = () => getLSTMStatus().then(r => active && setLstm(r.data)).catch(() => {})
    poll()
    const id = setInterval(poll, 5000)
    return () => { active = false; clearInterval(id) }
  }, [])

  // ── Sticky instrument symbol ────────────────────────────────────────────
  // Inter-bar tick payloads carry the symbol (e.g. "MES 09-26"); bar-close
  // payloads don't. Remember the last one seen (first token → "MES") so the
  // narration keeps the instrument even across bars that omit it.
  useEffect(() => {
    const s = currentBar?.symbol
    if (s) setSymbol(String(s).split(' ')[0])
  }, [currentBar])

  // ── Detect an LSTM training completion ──────────────────────────────────
  // The backend trains synchronously with no live "training" flag, so the one
  // honest signal is last_trained changing. When it does, flash a short
  // "neural network trained" recognition. (A live epoch counter would need a
  // backend progress signal, which doesn't exist yet — see report.)
  const prevTrainedRef = useRef(undefined)
  useEffect(() => {
    const lt = lstm?.last_trained
    if (lt === undefined || lt === null) return
    if (prevTrainedRef.current === undefined) { prevTrainedRef.current = lt; return }  // seed; don't flash on first load
    if (lt !== prevTrainedRef.current) { prevTrainedRef.current = lt; setLstmDoneAt(Date.now()) }
  }, [lstm])

  // ── Decorative GPU gauge ────────────────────────────────────────────────
  // This system is CPU-only — there is no real GPU to read. We render a
  // plausible slowly-drifting 30–45% value purely so the panel looks alive.
  // NOT a real measurement.
  useEffect(() => {
    const id = setInterval(() => {
      setGpu(g => Math.min(45, Math.max(30, g + (Math.random() - 0.5) * 3)))
    }, 2000)
    return () => clearInterval(id)
  }, [])

  // Tick every 2s so data-freshness (and thus market/AI status) re-evaluates
  // promptly without waiting on a message.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 2000)
    return () => clearInterval(id)
  }, [])

  // ── Derived model stats (all 19 models, both timeframes) ───────────────
  // Store maps are keyed by the composite id "name:timeframe" (Phase 2); the
  // base model name is the part before the last ':'.
  const stats = useMemo(() => {
    let totalWins = 0, totalLosses = 0, samples = 0, predictions = 0
    let leader = null, leaderPts = -Infinity
    let bestAcc = null

    const activeKeys = new Set([...Object.keys(modelSignals), ...Object.keys(modelLevels)])

    Object.entries(modelLevels).forEach(([, l]) => {
      samples += l?.bars_learned ?? 0
      predictions = Math.max(predictions, l?.bars_learned ?? 0)
    })

    Object.entries(modelPnl).forEach(([key, p]) => {
      const w = p?.wins ?? 0, ls = p?.losses ?? 0
      totalWins += w
      totalLosses += ls
      const pts = p?.points ?? 0
      if (pts > leaderPts) { leaderPts = pts; leader = key.split(':')[0] }
      if (w + ls > 0) {
        const acc = w / (w + ls)
        if (bestAcc === null || acc > bestAcc) bestAcc = acc
      }
    })

    const overallWinRate = (totalWins + totalLosses) > 0
      ? totalWins / (totalWins + totalLosses) : null

    return {
      activeCount: activeKeys.size || MODEL_NAMES.length,
      leader: (leader && leaderPts !== 0) ? leader : null,
      leaderPts,
      bestAcc,
      overallWinRate,
      samples,
      predictions,
    }
  }, [modelSignals, modelLevels, modelPnl])

  // Most recent non-HOLD signal = highest-confidence live non-HOLD across all models.
  const lastSignal = useMemo(() => {
    let best = null
    Object.values(modelSignals).forEach(s => {
      if (s && s.signal && s.signal !== 'HOLD') {
        if (!best || (s.confidence ?? 0) > (best.confidence ?? 0)) {
          best = { signal: s.signal, confidence: s.confidence ?? 0 }
        }
      }
    })
    return best
  }, [modelSignals])

  // ── Derived status strings ──────────────────────────────────────────────
  const task = training ? 'Training on History'
    : (lstm && lstm.is_dormant) ? 'Collecting Data'
    : 'Improve Accuracy'

  // "Data is streaming" = a bar/tick arrived recently OR the WS is connected and
  // a bar has been seen recently. This is what makes the panel honest during
  // replay/training, when the wall clock is outside market hours but data flows.
  const dataFlowing = lastBarAt > 0 && (now - lastBarAt) < 15000
  const rthOpen     = isMarketOpen()

  // AI Status follows the data, not the clock.
  const aiStatus = training ? { label: 'Training', color: C_GPU }
    : dataFlowing ? { label: 'Learning', color: C_CPU }
    : { label: 'Idle', color: '#565b66' }

  // Market status:
  //   REPLAY — training on, OR data flowing while the real ET clock is outside
  //            market hours (i.e. historical playback), shown in purple.
  //   LIVE   — data flowing during real market hours.
  //   OPEN   — market hours but no data currently streaming (feed idle).
  //   CLOSED — no data flowing AND outside market hours.
  const GREEN  = { color: C_CPU,     bg: '#1D9E7522' }
  const PURPLE = { color: '#8b5cf6', bg: '#8b5cf622' }
  const GREY   = { color: '#565b66', bg: '#ffffff08' }
  let market
  if (training || (dataFlowing && !rthOpen)) market = { text: 'REPLAY', ...PURPLE }
  else if (dataFlowing)                      market = { text: 'LIVE',   ...GREEN }
  else if (rthOpen)                          market = { text: 'OPEN',   ...GREEN }
  else                                       market = { text: 'CLOSED', ...GREY }

  // ── Status narration — plain-English headline of current activity ────────
  // Composed entirely from already-polled state, highest-priority active state
  // wins. Dot color encodes the activity type (purple=training, green=live,
  // amber=waiting, gray=idle).
  const narration = useMemo(() => {
    const PURPLE = '#8b5cf6', GREEN = C_CPU, AMBER = C_GPU, GRAY = '#565b66'
    const inst = symbol || null
    const hhmm = (t) => {
      try {
        return new Date(t).toLocaleTimeString('en-US', {
          timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
        })
      } catch { return null }
    }
    const year = (() => {
      try { return currentBar?.time ? new Date(currentBar.time).getFullYear() : null }
      catch { return null }
    })()

    // 1. LSTM live training (optional backend signal — dormant unless emitted).
    if (lstm?.training) {
      const ep = lstm.epoch, tot = lstm.total_epochs ?? 20
      const acc = lstm.val_accuracy != null ? ` · val acc ${Math.round(lstm.val_accuracy * 100)}%` : ''
      return { dot: PURPLE, text: ep ? `🧬 Training neural network — epoch ${ep}/${tot}${acc}` : '🧬 Training neural network…' }
    }
    // 1b. LSTM just finished (real signal: last_trained changed) — brief flash.
    if (lstmDoneAt && (now - lstmDoneAt) < 9000) {
      const acc = lstm?.train_accuracy != null ? ` — val acc ${Math.round(lstm.train_accuracy * 100)}%` : ''
      return { dot: PURPLE, text: `🧬 Neural network trained${acc}` }
    }
    // 2. Bulk import draining (training mode on + bars still queued).
    // "bars remaining" is the queue depth directly, clamped ≥ 0 — never a
    // subtraction that can go negative when the baseline desyncs after flush.
    const remaining = Math.max(0, trainQueue)
    if (training && remaining > 0) {
      const ctx = [year, inst].filter(Boolean).join(' ')
      return { dot: PURPLE, text: `📚 Offline — training on ${ctx ? ctx + ' ' : ''}history · ${remaining.toLocaleString()} bars remaining` }
    }
    // 3. Offline mode, queue empty — waiting for the historical blast.
    if (training) {
      return { dot: PURPLE, text: '📚 Offline mode — training on history (live models untouched)' }
    }
    // 4. Live — armed and bars flowing recently.
    if (ing.armed && dataFlowing) {
      const t = currentBar?.time ? hhmm(currentBar.time) : null
      return { dot: GREEN, text: `🟢 Live — watching ${inst || 'the market'} for signals${t ? ` · last bar ${t} ET` : ''}` }
    }
    // 5. Armed but no recent bars.
    if (ing.armed) {
      return { dot: AMBER, text: '📡 Armed — waiting for market data' }
    }
    // 6. Disarmed / idle.
    return { dot: GRAY, text: '⏸ Idle — ingestion paused' }
  }, [lstm, lstmDoneAt, now, training, trainQueue, ing, dataFlowing, currentBar, symbol])

  // ── Operator controls — same endpoints/state as the dashboard components ──
  // These hit the same backend the dashboard's IngestionControl (arm gate) and
  // ModeBanner (mode switch) use, so a toggle here reflects there (and vice
  // versa) via the shared polls above — no local-only divergence. Optimistically
  // apply the response so the button flips instantly; the poll reconciles either way.
  const [opBusy, setOpBusy] = useState(false)

  const toggleArm = async () => {
    if (opBusy) return
    setOpBusy(true)
    try {
      const res = ing.armed ? await disarmIngestion() : await armIngestion()
      if (res?.data) setIng(res.data)
    } catch { /* leave state as-is on failure */ } finally { setOpBusy(false) }
  }

  // Switch system mode. On stream there's no dialog, so if the queue isn't
  // drained (backend 409) we flush-and-switch — a deliberate operator action.
  const toggleMode = async () => {
    if (opBusy) return
    setOpBusy(true)
    const call = training ? setModeLive : setModeOffline
    try {
      let res
      try { res = await call(false) }
      catch (e) {
        if (e.response?.status === 409) res = await call(true)   // flush & switch
        else throw e
      }
      if (res?.data) {
        setMode(res.data.mode === 'offline' ? 'offline' : 'live')
        if (res.data.queue_pending != null) setTrainQueue(Math.max(0, res.data.queue_pending))
      }
    } catch { /* leave state as-is on failure */ } finally { setOpBusy(false) }
  }

  const pct = (v) => v == null ? '—' : `${Math.round(v * 100)}%`
  const num = (v) => (v ?? 0).toLocaleString()

  return (
    <div style={{
      width: '100vw', height: '100vh', overflow: 'hidden', boxSizing: 'border-box',
      background: 'var(--surface-0, #0e0f11)', padding: 14,
      display: 'flex', gap: 14, color: 'var(--text-primary)',
    }}>
      {/* ══════════════ LEFT: AI LAB PANEL ══════════════ */}
      <aside style={{
        width: 320, flexShrink: 0, borderRadius: 14,
        background: 'linear-gradient(160deg, #16181d 0%, #101216 60%, #0c0d10 100%)',
        border: '1px solid #23262d', boxShadow: 'inset 0 1px 0 #ffffff08',
        fontFamily: MONO, display: 'flex', flexDirection: 'column',
        padding: '16px 16px 14px', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 4 }}>
          <span style={{
            width: 9, height: 9, borderRadius: '50%', background: C_CPU,
            boxShadow: `0 0 8px ${C_CPU}`, animation: 'lab-pulse 1.8s ease-in-out infinite',
          }} />
          <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: '0.14em' }}>🤖 AI&nbsp;LAB</span>
        </div>
        <div style={{ fontSize: 9.5, color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: 14 }}>
          AUTONOMOUS&nbsp;ML&nbsp;CONTROL
        </div>

        {/* Section 1 — System */}
        <SectionTitle>SYSTEM</SectionTitle>
        <KVRow icon="🔨" label="Task" value={task} accent={training ? C_GPU : undefined} />
        <BarRow icon="💻" label="CPU"  value={`${(sys.cpu_percent ?? 0).toFixed(0)}%`} pct={(sys.cpu_percent ?? 0) / 100} color={C_CPU} />
        <BarRow icon="🧠" label="RAM"
                value={`${(sys.ram_used_gb ?? 0).toFixed(1)}/${(sys.ram_total_gb ?? 0).toFixed(1)}G`}
                pct={(sys.ram_percent ?? 0) / 100} color={C_RAM} />
        <BarRow icon="🎮" label="GPU" value={`${gpu.toFixed(0)}%`} pct={gpu / 100} color={C_GPU} sub="sim" />

        <Divider />

        {/* Section 2 — Models */}
        <SectionTitle>MODELS</SectionTitle>
        <KVRow icon="📊" label="Models"      value={num(stats.activeCount)} />
        <KVRow icon="🏆" label="Leader"
               value={stats.leader ? MODEL_META[stats.leader].label : '—'}
               accent={stats.leader ? MODEL_META[stats.leader].color : undefined} />
        <KVRow icon="📈" label="Accuracy"    value={pct(stats.bestAcc)} />
        <KVRow icon="📉" label="Win Rate"    value={pct(stats.overallWinRate)} />
        <KVRow icon="⚡" label="Predictions" value={num(stats.predictions)} />
        <KVRow icon="🧠" label="Samples"     value={num(stats.samples)} />

        <Divider />

        {/* Section 3 — Status */}
        <SectionTitle>STATUS</SectionTitle>
        <KVRow icon="📡" label="Market"
               badge={{ text: market.text, color: market.color, bg: market.bg }} />
        <KVRow icon={<span style={{ color: aiStatus.color }}>●</span>} label="AI Status"
               value={aiStatus.label} accent={aiStatus.color} />
        <KVRow icon="🔥" label="Last Signal"
               badge={lastSignal ? {
                 text: `${lastSignal.signal} ${Math.round((lastSignal.confidence ?? 0) * 100)}%`,
                 color: lastSignal.signal === 'BUY' ? C_CPU : '#E24B4A',
                 bg: lastSignal.signal === 'BUY' ? '#1D9E7522' : '#E24B4A22',
               } : { text: '—', color: 'var(--text-muted)', bg: '#ffffff08' }} />

        <div style={{ flex: 1 }} />
        <OperatorControls
          armed={ing.armed} offline={training}
          queued={Math.max(0, trainQueue || ing.queue_pending || 0)}
          busy={opBusy} onArm={toggleArm} onMode={toggleMode}
        />
        <ContactBadge />
        <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.08em', textAlign: 'center', marginTop: 10 }}>
          streaming · no interaction
        </div>
      </aside>

      {/* ══════════════ RIGHT: SIGNAL · RACE · ARCHITECTURE ══════════════ */}
      <main style={{
        flex: 1, minWidth: 0, minHeight: 0, overflow: 'hidden',
        display: 'flex', flexDirection: 'column', gap: 12,
      }}>
        {/* Status narration — plain-English headline of current activity */}
        <div style={{ flexShrink: 0 }}>
          <StatusTicker dot={narration.dot} text={narration.text} />
        </div>

        {/* Trade Signal — top (most actionable) */}
        <div style={{ flexShrink: 0 }}>
          <TradeSignalPanel compact />
        </div>

        {/* Leaderboard race — middle */}
        <div style={{
          flexShrink: 0, borderRadius: 14, overflow: 'hidden', fontFamily: MONO,
          background: 'linear-gradient(160deg, #15171b 0%, #101216 100%)',
          border: '1px solid #23262d', boxShadow: 'inset 0 1px 0 #ffffff08',
          padding: '12px 16px',
        }}>
          <LeaderboardRace compact />
        </div>

        {/* Architecture — remaining space */}
        <div style={{
          flex: 1, minHeight: 0, borderRadius: 14, overflow: 'hidden',
          background: 'linear-gradient(160deg, #15171b 0%, #101216 100%)',
          border: '1px solid #23262d', boxShadow: 'inset 0 1px 0 #ffffff08',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 16px', borderBottom: '1px solid #1e2127', flexShrink: 0,
            fontFamily: MONO,
          }}>
            <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.04em' }}>System Design &amp; Architecture</span>
            <span style={{ fontSize: 9.5, color: 'var(--text-muted)', letterSpacing: '0.08em' }}>
              DEPLOYMENT · DATA FLOW
            </span>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: 10 }}>
            <div style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
              <SystemDesignDiagram compact />
            </div>
            <div style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'flex-start' }}>
              <ArchitectureDiagram compact />
            </div>
          </div>
        </div>
      </main>

      <style>{`
        @keyframes lab-pulse { 0%,100%{opacity:1; transform:scale(1)} 50%{opacity:.45; transform:scale(.85)} }
        @keyframes status-fade { from{opacity:0; transform:translateY(3px)} to{opacity:1; transform:translateY(0)} }
      `}</style>
    </div>
  )
}

// ── Status narration ticker ───────────────────────────────────────────────
// Prominent single line, monospace, pulsing activity dot, brief fade on change
// (the key={text} remounts the span so the animation re-runs). Sized larger than
// the panel body so it reads at stream distance.
function StatusTicker({ dot, text }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 13, fontFamily: MONO,
      borderRadius: 14, padding: '13px 18px',
      background: 'linear-gradient(160deg, #15171b 0%, #101216 100%)',
      border: '1px solid #23262d', boxShadow: 'inset 0 1px 0 #ffffff08',
    }}>
      <span style={{
        width: 11, height: 11, borderRadius: '50%', background: dot, flexShrink: 0,
        boxShadow: `0 0 10px ${dot}`, animation: 'lab-pulse 1.6s ease-in-out infinite',
      }} />
      <span key={text} style={{
        fontSize: 17, fontWeight: 600, letterSpacing: '0.01em', color: 'var(--text-primary)',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        animation: 'status-fade 0.5s ease',
      }}>{text}</span>
      <span style={{
        marginLeft: 'auto', fontSize: 9.5, color: 'var(--text-muted)',
        letterSpacing: '0.14em', flexShrink: 0,
      }}>LIVE ACTIVITY</span>
    </div>
  )
}

// ── Operator controls ─────────────────────────────────────────────────────
// Compact arm/training toggles for the operator, de-emphasized so they don't
// compete with the stream. Backed by the same endpoints as the dashboard.
function OperatorControls({ armed, offline, queued, busy, onArm, onMode }) {
  const GREEN = C_CPU, PURPLE = '#8b5cf6'
  const btn = (active, color) => ({
    fontSize: 10.5, padding: '4px 9px', borderRadius: 6, fontFamily: MONO,
    cursor: busy ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
    color: active ? '#fff' : color,
    background: active ? color : 'transparent',
    border: `1px solid ${color}${active ? '' : '66'}`,
  })
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap',
      marginBottom: 10, opacity: 0.82,
    }}>
      <span style={{
        fontSize: 8.5, fontWeight: 700, letterSpacing: '0.16em',
        color: 'var(--text-muted)', marginRight: 1,
      }}>OP</span>
      <button onClick={onArm} disabled={busy} title="Arm / disarm ingestion (orthogonal to mode)"
              style={btn(armed, GREEN)}>
        {armed ? '● Armed' : '▶ Arm'}
      </button>
      {/* Mode toggle — shows the CURRENT mode; click switches (flushes if queued). */}
      <button onClick={onMode} disabled={busy} title="Switch LIVE ⇄ OFFLINE (flushes the queue if needed)"
              style={btn(offline, PURPLE)}>
        {offline ? '📚 Offline' : '🟢 Live'}
      </button>
      {queued > 0 && (
        <span style={{
          fontSize: 9.5, color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums',
        }}>{queued.toLocaleString()} queued</span>
      )}
    </div>
  )
}

// ── Contact / brand badge ─────────────────────────────────────────────────
// A tasteful "who made this / how to reach them" mark tucked at the bottom of
// the AI Lab column. Subtle enough not to compete with the live data, but
// intentional. The email is a real mailto link (clickable off-stream) that still
// reads as plain text on stream.
const BRAND_PURPLE = '#534AB7'
const EMAIL_PURPLE = '#8b82e8'

function ContactBadge() {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 11, fontFamily: MONO,
      padding: '10px 12px', borderRadius: 10,
      background: 'linear-gradient(180deg, var(--surface-2, #16181d), var(--surface-1, #101216))',
      border: '0.5px solid #ffffff14', borderLeft: `3px solid ${BRAND_PURPLE}`,
      boxShadow: 'inset 0 1px 0 #ffffff08',
    }}>
      <span style={{ fontSize: 21, lineHeight: 1, flexShrink: 0 }}>🧠</span>
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{
          fontSize: 12, fontWeight: 700, letterSpacing: '0.16em',
          color: 'var(--text-primary)',
        }}>ADAPTIVEMIND</span>
        <span style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.04em' }}>
          Contact for more information
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 1 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: C_CPU, flexShrink: 0,
            boxShadow: `0 0 6px ${C_CPU}`,
          }} />
          <a href="mailto:adaptivemindofficial@gmail.com" style={{
            fontSize: 10.5, color: EMAIL_PURPLE, textDecoration: 'none',
            letterSpacing: '0.01em', whiteSpace: 'nowrap', overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>adaptivemindofficial@gmail.com</a>
        </span>
      </div>
    </div>
  )
}

// ── Panel primitives ─────────────────────────────────────────────────────

function SectionTitle({ children }) {
  return (
    <div style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: '0.18em',
      color: 'var(--text-muted)', marginBottom: 8,
    }}>{children}</div>
  )
}

function Divider() {
  return <div style={{ height: 1, background: '#ffffff0d', margin: '13px 0' }} />
}

const ROW = {
  display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9,
  fontSize: 12, lineHeight: 1.2,
}
const LABEL = { color: 'var(--text-secondary)', flex: 1, whiteSpace: 'nowrap' }
const VALUE = {
  fontWeight: 600, fontVariantNumeric: 'tabular-nums',
  whiteSpace: 'nowrap', textAlign: 'right',
}

function KVRow({ icon, label, value, accent, badge }) {
  return (
    <div style={ROW}>
      <span style={{ width: 16, textAlign: 'center', flexShrink: 0 }}>{icon}</span>
      <span style={LABEL}>{label}</span>
      {badge ? (
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
          color: badge.color, background: badge.bg, letterSpacing: '0.04em',
          fontVariantNumeric: 'tabular-nums',
        }}>{badge.text}</span>
      ) : (
        <span style={{ ...VALUE, color: accent || 'var(--text-primary)' }}>{value}</span>
      )}
    </div>
  )
}

function BarRow({ icon, label, value, pct, color, sub }) {
  const width = `${Math.min(100, Math.max(0, (pct ?? 0) * 100))}%`
  return (
    <div style={{ marginBottom: 9 }}>
      <div style={{ ...ROW, marginBottom: 4 }}>
        <span style={{ width: 16, textAlign: 'center', flexShrink: 0 }}>{icon}</span>
        <span style={LABEL}>
          {label}
          {sub && <span style={{ color: 'var(--text-muted)', fontSize: 9, marginLeft: 5 }}>({sub})</span>}
        </span>
        <span style={{ ...VALUE, color }}>{value}</span>
      </div>
      <div style={{ height: 5, borderRadius: 3, background: '#ffffff0d', overflow: 'hidden', marginLeft: 24 }}>
        <div style={{
          height: '100%', width, background: color, borderRadius: 3,
          boxShadow: `0 0 6px ${color}66`, transition: 'width 0.6s ease',
        }} />
      </div>
    </div>
  )
}
