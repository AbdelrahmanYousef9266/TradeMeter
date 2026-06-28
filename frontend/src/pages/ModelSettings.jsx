import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getModelSettings, updateModelSettings, resetModel, getModelLevel } from '../services/api'
import ModelBehavior from '../components/settings/ModelBehavior'
import useStore from '../store'

const RANK_COLORS = {
  Rookie: '#6b7280', Apprentice: '#185FA5', Pro: '#0F6E56',
  Elite: '#534AB7', Expert: '#854F0B', Master: '#993C1D',
}

const RANK_ORDER = ['Rookie', 'Apprentice', 'Pro', 'Elite', 'Expert', 'Master']

function rankGte(a, b) {
  return RANK_ORDER.indexOf(a) >= RANK_ORDER.indexOf(b)
}

const card = {
  background: 'var(--surface-2)',
  border: '0.5px solid var(--border)',
  borderRadius: 12,
  padding: '14px 16px',
  marginBottom: 12,
}

export default function ModelSettings() {
  const { modelName } = useParams()
  const modelLevels = useStore(s => s.modelLevels)

  const [levelInfo,  setLevelInfo]  = useState(null)
  const [settings,   setSettings]   = useState(null)
  const [localVals,  setLocalVals]  = useState({})
  const [loading,    setLoading]    = useState(true)
  const [saved,      setSaved]      = useState(false)
  const [resetDone,  setResetDone]  = useState(false)
  const [error,      setError]      = useState(null)

  const labelName = modelName?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  useEffect(() => {
    if (!modelName) return
    Promise.all([
      getModelLevel(modelName),
      getModelSettings(modelName),
    ])
      .then(([lvlRes, settRes]) => {
        setLevelInfo(lvlRes.data)
        setSettings(settRes.data)
        const vals = {}
        Object.entries(settRes.data).forEach(([k, v]) => { vals[k] = v.value })
        setLocalVals(vals)
      })
      .catch(e => setError(e.message || 'Failed to load'))
      .finally(() => setLoading(false))
  }, [modelName])

  // Merge with live WS level info
  const live = modelLevels[modelName]
  const lvl  = live || levelInfo

  const handleSave = async () => {
    const payload = {}
    Object.entries(localVals).forEach(([k, v]) => {
      if (settings[k] && !settings[k].locked) payload[k] = v
    })
    await updateModelSettings(modelName, payload)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleReset = async () => {
    await resetModel(modelName)
    setResetDone(true)
    setTimeout(() => setResetDone(false), 3000)
  }

  if (loading) {
    return (
      <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-secondary)' }}>
        Loading...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '32px 16px' }}>
        <Link to="/dashboard" style={{ color: 'var(--text-secondary)', fontSize: 13 }}>← Dashboard</Link>
        <p style={{ color: 'var(--text-danger)', marginTop: 16 }}>{error}</p>
      </div>
    )
  }

  const rank      = lvl?.rank || 'Rookie'
  const rankColor = RANK_COLORS[rank] || '#6b7280'
  const xpPct     = lvl?.xp_progress_pct ?? 0

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '24px 16px' }}>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <Link to="/dashboard" style={{ color: 'var(--text-secondary)', fontSize: 13 }}>← Dashboard</Link>
        <h1 style={{ fontSize: 17, fontWeight: 500 }}>{labelName}</h1>
      </div>

      {/* Level header */}
      <div style={{ ...card }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 15, fontWeight: 500 }}>Level {lvl?.level ?? 1}</span>
              <span style={{
                fontSize: 11, fontWeight: 500, padding: '2px 7px', borderRadius: 5,
                background: `${rankColor}22`, color: rankColor,
              }}>{rank}</span>
            </div>
            <div style={{ display: 'flex', gap: 16, color: 'var(--text-secondary)', fontSize: 12 }}>
              <span>Streak {lvl?.streak ?? 0}</span>
              <span>Bars {lvl?.bars_learned ?? 0}</span>
            </div>
          </div>
          <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--text-secondary)' }}>
            {Math.round(xpPct * 100)}% to next level
          </div>
        </div>
        {/* XP bar */}
        <div style={{ height: 5, background: 'var(--surface-3)', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${xpPct * 100}%`,
            background: rankColor, borderRadius: 3,
            transition: 'width 0.4s ease',
          }} />
        </div>
      </div>

      {/* Settings sections gated by rank */}
      <div style={card}>
        <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Behavior Settings
        </p>

        {settings && (
          <ModelBehavior
            settings={settings}
            localVals={localVals}
            rank={rank}
            onChange={(key, val) => setLocalVals(prev => ({ ...prev, [key]: val }))}
          />
        )}
      </div>

      {/* Unlocked settings info */}
      {lvl?.unlocked_settings && (
        <div style={{ ...card }}>
          <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Unlocked
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {lvl.unlocked_settings.map(s => (
              <span key={s} style={{
                fontSize: 11, padding: '3px 8px', borderRadius: 5,
                background: 'var(--bg-success)', color: 'var(--text-success)',
                border: '1px solid rgba(74,222,128,0.2)',
              }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          onClick={handleSave}
          style={{
            flex: 1, padding: '9px', borderRadius: 8,
            background: saved ? 'var(--bg-success)' : 'var(--accent)',
            color: saved ? 'var(--text-success)' : '#fff', fontWeight: 500,
            border: saved ? '1px solid var(--text-success)' : 'none',
          }}
        >
          {saved ? 'Saved' : 'Save'}
        </button>
        <button
          onClick={handleReset}
          style={{
            padding: '9px 18px', borderRadius: 8,
            border: '1px solid var(--border)',
            color: resetDone ? 'var(--text-success)' : 'var(--text-secondary)',
            background: 'transparent',
          }}
        >
          {resetDone ? 'Reset done' : 'Reset weights'}
        </button>
      </div>
    </div>
  )
}
