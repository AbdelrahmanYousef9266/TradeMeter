import { useState } from 'react'
import { Link } from 'react-router-dom'
import useStore from '../store'
import IndicatorToggles from '../components/settings/IndicatorToggles'
import StrategyConfig   from '../components/settings/StrategyConfig'
import DataCoverageCalendar from '../components/DataCoverageCalendar'
import { resetModel } from '../services/api'

const ALL_MODELS = [
  'scalper', 'momentum', 'mean_reversion', 'breakout',
  'conservative', 'aggressive', 'volume', 'contrarian', 'personal',
]

const card = {
  background: 'var(--surface-2)',
  border: '0.5px solid var(--border)',
  borderRadius: 12,
  padding: '14px 16px',
}

export default function Settings() {
  const { settings, setSettings } = useStore()
  const [saved, setSaved]   = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [resetting, setResetting] = useState(false)

  const handleSave = () => {
    localStorage.setItem('tm_settings', JSON.stringify(settings))
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleResetAll = async () => {
    setResetting(true)
    setConfirm(false)
    await Promise.allSettled(ALL_MODELS.map(n => resetModel(n)))
    setResetting(false)
  }

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '24px 16px' }}>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <Link to="/dashboard" style={{ color: 'var(--text-secondary)', fontSize: 13 }}>← Dashboard</Link>
        <h1 style={{ fontSize: 17, fontWeight: 500 }}>Settings</h1>
      </div>

      {/* Strategy config */}
      <div style={{ ...card, marginBottom: 12 }}>
        <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Instrument
        </p>
        <StrategyConfig settings={settings} onChange={setSettings} />
      </div>

      {/* Indicator toggles */}
      <div style={{ ...card, marginBottom: 12 }}>
        <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Chart Indicators
        </p>
        <IndicatorToggles
          indicators={settings.indicators}
          onChange={inds => setSettings({ ...settings, indicators: inds })}
        />
      </div>

      {/* Data coverage */}
      <div style={{ ...card, marginBottom: 12 }}>
        <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Data Coverage
        </p>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
          Days with collected market data, colored by bar volume
        </p>
        <DataCoverageCalendar />
      </div>

      {/* Save */}
      <button
        onClick={handleSave}
        style={{
          width: '100%', padding: '9px', borderRadius: 8,
          background: saved ? 'var(--bg-success)' : 'var(--accent)',
          color: saved ? 'var(--text-success)' : '#fff',
          fontWeight: 500, marginBottom: 24,
          border: saved ? '1px solid var(--text-success)' : 'none',
        }}
      >
        {saved ? 'Saved' : 'Save Settings'}
      </button>

      {/* Danger zone */}
      <div style={{ ...card, borderColor: '#f8717144' }}>
        <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-danger)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Danger Zone
        </p>
        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
          Resets all 9 model weights. Level and XP are preserved.
        </p>

        {!confirm ? (
          <button
            onClick={() => setConfirm(true)}
            style={{
              padding: '7px 14px', borderRadius: 7,
              border: '1px solid var(--text-danger)',
              color: 'var(--text-danger)', background: 'transparent',
            }}
          >
            Reset all model weights
          </button>
        ) : (
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={handleResetAll}
              disabled={resetting}
              style={{
                padding: '7px 14px', borderRadius: 7,
                background: 'var(--text-danger)', color: '#fff', border: 'none',
                opacity: resetting ? 0.6 : 1,
              }}
            >
              {resetting ? 'Resetting…' : 'Confirm reset'}
            </button>
            <button
              onClick={() => setConfirm(false)}
              style={{
                padding: '7px 14px', borderRadius: 7,
                border: '1px solid var(--border)', color: 'var(--text-secondary)',
                background: 'transparent',
              }}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
