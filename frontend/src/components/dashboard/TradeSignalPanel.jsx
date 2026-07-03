import { useEffect, useMemo, useRef, useState } from 'react'
import useStore from '../../store'
import { getModelSettings } from '../../services/api'

/**
 * TradeSignalPanel — ONE clear, actionable trade plan per bar.
 *
 * Picks the single best call: the model with the highest confidence among those
 * currently firing a non-HOLD signal, tie-broken by session P&L (the leader).
 * Entry / target / stop are computed with the SAME ATR math the trade simulator
 * uses (app/services/ml/trade_tracker.py :: open_trade), so the numbers match
 * what the model would actually trade:
 *
 *   stop_dist   = atr * atr_stop_mult
 *   target_dist = atr * atr_target_mult
 *   BUY  → target = entry + target_dist,  stop = entry - stop_dist
 *   SELL → target = entry - target_dist,  stop = entry + stop_dist
 *   MES point value = $5
 *
 * Entry uses the latest bar close as the expected next-bar open (the real fill
 * price per the look-ahead fix). ATR + multipliers come from the same sources
 * the pipeline uses: features.atr_14 and the model's settings (falling back to
 * the pipeline's own .get() defaults of 1.5 / 3.0 when a model omits them).
 */

const MES_POINT_VALUE = 5.0
const DEFAULT_STOP_MULT = 1.5     // matches pipeline params.get("atr_stop_mult", 1.5)
const DEFAULT_TARGET_MULT = 3.0   // matches pipeline params.get("atr_target_mult", 3.0)

const MODEL_LABELS = {
  scalper: 'Scalper', momentum: 'Momentum', mean_reversion: 'Mean Reversion',
  breakout: 'Breakout', conservative: 'Conservative', aggressive: 'Aggressive',
  volume: 'Volume', contrarian: 'Contrarian', personal: 'Secret', lstm: 'Deep LSTM',
}
const MODEL_NAMES = Object.keys(MODEL_LABELS)

const GREEN = '#1D9E75'
const RED   = '#E24B4A'

export default function TradeSignalPanel({ compact = false }) {
  const { modelSignals, modelLevels, modelPnl, currentBar, barHistory } = useStore()
  const [settingsCache, setSettingsCache] = useState({})

  // ── Pick the single best actionable call ────────────────────────────────
  const leader = useMemo(() => {
    let best = null
    for (const name of MODEL_NAMES) {
      const s = modelSignals[name]
      if (!s || (s.signal !== 'BUY' && s.signal !== 'SELL')) continue
      const conf = s.confidence ?? 0
      const pts  = modelPnl[name]?.points ?? 0
      if (!best || conf > best.conf || (conf === best.conf && pts > best.pts)) {
        best = { name, signal: s.signal, conf, pts }
      }
    }
    return best
  }, [modelSignals, modelPnl])

  const leaderName = leader?.name ?? null

  // ── Fetch the leading model's real ATR multipliers (cached per model) ───
  useEffect(() => {
    if (!leaderName || settingsCache[leaderName]) return
    let active = true
    getModelSettings(leaderName)
      .then(res => {
        if (!active) return
        const s = res.data || {}
        const stop   = s.atr_stop_mult?.value
        const target = s.atr_target_mult?.value
        setSettingsCache(c => ({ ...c, [leaderName]: {
          stopMult:   typeof stop   === 'number' ? stop   : DEFAULT_STOP_MULT,
          targetMult: typeof target === 'number' ? target : DEFAULT_TARGET_MULT,
        }}))
      })
      .catch(() => active && setSettingsCache(c => ({ ...c, [leaderName]: {
        stopMult: DEFAULT_STOP_MULT, targetMult: DEFAULT_TARGET_MULT,
      }})))
    return () => { active = false }
  }, [leaderName, settingsCache])

  // ── Compute the trade plan (mirrors trade_tracker.open_trade exactly) ───
  const plan = useMemo(() => {
    if (!leader) return null
    // Latest CLOSED bar carries both close and features (atr_14); fall back to
    // the live currentBar. Entry = that close (the expected next-bar open).
    const bar = (barHistory && barHistory.length ? barHistory[barHistory.length - 1] : null) || currentBar
    const entry = bar?.close
    const atr   = bar?.features?.atr_14
    if (typeof entry !== 'number' || typeof atr !== 'number' || atr <= 0) return null

    const mult = settingsCache[leaderName] || { stopMult: DEFAULT_STOP_MULT, targetMult: DEFAULT_TARGET_MULT }
    const stopDist   = atr * mult.stopMult
    const targetDist = atr * mult.targetMult
    const isBuy = leader.signal === 'BUY'

    return {
      isBuy,
      entry,
      target: isBuy ? entry + targetDist : entry - targetDist,
      stop:   isBuy ? entry - stopDist   : entry + stopDist,
      targetDist,
      stopDist,
      rr:            stopDist > 0 ? targetDist / stopDist : 0,
      riskDollars:   Math.round(stopDist   * MES_POINT_VALUE),
      rewardDollars: Math.round(targetDist * MES_POINT_VALUE),
    }
  }, [leader, leaderName, settingsCache, barHistory, currentBar])

  // ── Flash when the leading model OR direction changes ───────────────────
  const signature = leader ? `${leader.name}|${leader.signal}` : 'none'
  const [flash, setFlash] = useState(false)
  const prevSig = useRef(signature)
  useEffect(() => {
    if (signature !== prevSig.current) {
      prevSig.current = signature
      if (signature !== 'none') {
        setFlash(true)
        const t = setTimeout(() => setFlash(false), 700)
        return () => clearTimeout(t)
      }
    }
  }, [signature])

  const accent = !leader ? 'var(--border)' : leader.signal === 'BUY' ? GREEN : RED
  // `compact` (used on the AFK stream) trims padding + font sizes so the panel
  // fits a shared column. Default (Dashboard, /stream) stays full-size.
  const pad = compact ? '12px 14px' : '18px 22px'
  const actionSize = compact ? 24 : 34

  // ── Resting state ───────────────────────────────────────────────────────
  if (!leader || !plan) {
    return (
      <Shell accent="var(--border)" flash={false} pad={pad}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{
            width: 10, height: 10, borderRadius: '50%', background: 'var(--text-muted)',
            animation: 'ts-pulse 2s ease-in-out infinite', flexShrink: 0,
          }} />
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-secondary)' }}>
              No active signal — models watching
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              Every model is on HOLD. A trade plan appears here the moment one fires.
            </div>
          </div>
        </div>
        <Disclaimer />
        <PanelStyles />
      </Shell>
    )
  }

  const rank = modelLevels[leaderName]?.rank ?? 'Rookie'
  const confPct = Math.max(0, Math.min(100, Math.round((leader.conf ?? 0) * 100)))
  const label = MODEL_LABELS[leaderName] || leaderName

  return (
    <Shell accent={accent} flash={flash} pad={pad}>
      {/* Header */}
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
        Live Signal from <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
        {' · '}{rank}{' · '}<span style={{ color: accent }}>{confPct}% confidence</span>
      </div>

      {/* Big action */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: compact ? 10 : 14, margin: compact ? '6px 0 10px' : '10px 0 14px' }}>
        <span style={{ fontSize: actionSize, fontWeight: 800, color: accent, letterSpacing: '-0.02em', lineHeight: 1 }}>
          {plan.isBuy ? '▲ BUY' : '▼ SELL'}
        </span>
        <span style={{ fontSize: compact ? 12 : 13, color: 'var(--text-secondary)' }}>
          {plan.isBuy ? 'Long MES — entry on next bar' : 'Short MES — entry on next bar'}
        </span>
      </div>

      {/* Three levels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: compact ? 8 : 10 }}>
        <Level label="Entry" price={plan.entry} sub="next bar open (est.)" color="var(--text-primary)" compact={compact} />
        <Level label="🎯 Target" price={plan.target}
               sub={`+${plan.targetDist.toFixed(1)} pts`} color={GREEN} compact={compact} />
        <Level label="🛑 Stop" price={plan.stop}
               sub={`−${plan.stopDist.toFixed(1)} pts`} color={RED} compact={compact} />
      </div>

      {/* Footer stats */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10,
        marginTop: compact ? 8 : 12, paddingTop: compact ? 8 : 12,
        borderTop: '1px solid var(--border-subtle, #ffffff12)',
      }}>
        <Stat label="Risk : Reward" value={`${plan.rr.toFixed(1)} : 1`} color="var(--text-primary)" compact={compact} />
        <Stat label="Risk / contract"   value={`−$${plan.riskDollars}`}   color={RED} compact={compact} />
        <Stat label="Reward / contract" value={`+$${plan.rewardDollars}`} color={GREEN} compact={compact} />
      </div>

      <Disclaimer />
      <PanelStyles />
    </Shell>
  )
}

// ── Presentational pieces ─────────────────────────────────────────────────

function Shell({ accent, flash, pad, children }) {
  return (
    <div style={{
      background: 'var(--surface-2)',
      border: `1px solid ${accent}`,
      borderLeft: `4px solid ${accent}`,
      borderRadius: 14,
      padding: pad,
      boxShadow: flash ? `0 0 0 3px ${accent}44` : 'none',
      animation: flash ? 'ts-flash 0.7s ease' : 'none',
      transition: 'border-color 0.3s ease, box-shadow 0.3s ease',
    }}>
      {children}
    </div>
  )
}

function Level({ label, price, sub, color, compact }) {
  return (
    <div style={{
      background: 'var(--surface-1, #16181d)', borderRadius: 10, padding: compact ? '7px 10px' : '10px 12px',
    }}>
      <div style={{ fontSize: compact ? 10 : 11, color: 'var(--text-muted)', marginBottom: compact ? 2 : 4 }}>{label}</div>
      <div style={{ fontSize: compact ? 17 : 20, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em' }}>
        {price.toFixed(2)}
      </div>
      <div style={{ fontSize: compact ? 9.5 : 10.5, color: 'var(--text-muted)', marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>{sub}</div>
    </div>
  )
}

function Stat({ label, value, color, compact }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: compact ? 9 : 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ fontSize: compact ? 14 : 16, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

function Disclaimer() {
  return (
    <div style={{ fontSize: 9.5, color: 'var(--text-muted)', marginTop: 10, opacity: 0.7 }}>
      Simulated signal · not financial advice
    </div>
  )
}

function PanelStyles() {
  return (
    <style>{`
      @keyframes ts-pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
      @keyframes ts-flash { 0%{transform:scale(1)} 30%{transform:scale(1.012)} 100%{transform:scale(1)} }
    `}</style>
  )
}
