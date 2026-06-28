import { useEffect } from 'react'
import useStore from '../../store'

const RANK_COLORS = {
  Rookie: '#6b7280', Apprentice: '#185FA5', Pro: '#0F6E56',
  Elite: '#534AB7', Expert: '#854F0B', Master: '#993C1D',
}

export default function LevelUpToast({ event }) {
  const dismissLevelUp = useStore(s => s.dismissLevelUp)

  useEffect(() => {
    const t = setTimeout(() => dismissLevelUp(event.id), 5000)
    return () => clearTimeout(t)
  }, [event.id, dismissLevelUp])

  const rankColor = RANK_COLORS[event.new_rank] || '#6b7280'
  const name = event.model_name?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())

  return (
    <div
      onClick={() => dismissLevelUp(event.id)}
      style={{
        background: 'var(--surface-2)',
        border: `1px solid ${rankColor}44`,
        borderLeft: `3px solid ${rankColor}`,
        borderRadius: 10,
        padding: '10px 14px',
        minWidth: 260,
        cursor: 'pointer',
        animation: 'slide-in 0.25s ease-out',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
        <span style={{ fontSize: 14 }}>⬆</span>
        <span style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: 13 }}>
          {name} reached Level {event.new_level}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 500, padding: '1px 6px', borderRadius: 4,
          background: `${rankColor}22`, color: rankColor,
        }}>
          {event.new_rank}
        </span>
      </div>
      {event.unlocked && (
        <div style={{ fontSize: 11, color: 'var(--text-success)', paddingLeft: 22 }}>
          + {event.unlocked} unlocked
        </div>
      )}
    </div>
  )
}
