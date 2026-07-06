import { useEffect } from 'react'
import useStore from '../../store'

const RANK_COLORS = {
  Rookie: '#6b7280', Apprentice: '#185FA5', Pro: '#0F6E56',
  Elite: '#534AB7', Expert: '#854F0B', Master: '#993C1D',
}

// Auto-dismiss after this long with NO new events. A rapid burst (bulk import)
// keeps re-arming the timer, so the single toast stays up and updates in place,
// then fades once the burst ends.
const AUTO_DISMISS_MS = 4000

const titleCase = (s) => (s || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
const fmtPts = (v) => { const n = Number(v) || 0; return `${n >= 0 ? '+' : ''}${n}` }

/**
 * Single, in-place level-up / CC-promotion toast (fixed bottom-right).
 *
 * Reads the coalesced `levelUpToast` slot from the store. At most one toast is
 * ever on screen; new events replace its content (with a refresh pulse) instead
 * of stacking, and an "(+N more)" line reflects how many events were absorbed
 * while it has been visible. Self-positioning and self-dismissing — render it
 * once on any page that wants notifications.
 */
export default function LevelUpToast() {
  const toast   = useStore(s => s.levelUpToast)
  const dismiss = useStore(s => s.dismissLevelUp)   // stable zustand action

  // Re-arm the auto-dismiss timer every time a new event is coalesced in
  // (seq changes). `dismiss` is stable, so unrelated re-renders don't reset it.
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(dismiss, AUTO_DISMISS_MS)
    return () => clearTimeout(t)
  }, [toast?.seq, dismiss])

  if (!toast) return null

  const isCC      = toast.display_type === 'cc_promotion'
  const rankColor = isCC ? '#534AB7' : (RANK_COLORS[toast.new_rank] || '#6b7280')
  const name      = titleCase(toast.model_name)

  let icon, title, subtitle
  if (isCC) {
    const promoted = toast.winner === 'challenger'
    icon     = promoted ? '⚔️' : '🏆'
    title    = `${name} — ${promoted ? 'Challenger promoted!' : 'Champion retained'}`
    subtitle = `Champion ${fmtPts(toast.champion_pnl)} vs Challenger ${fmtPts(toast.challenger_pnl)} pts`
  } else {
    icon     = '⬆'
    title    = `${name} reached Level ${toast.new_level}`
    subtitle = toast.unlocked ? `+ ${toast.unlocked} unlocked` : null
  }

  const indent = isCC ? 0 : 22

  return (
    <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 1000 }}>
      <div
        onClick={dismiss}
        style={{
          background: 'var(--surface-2)',
          border: `1px solid ${rankColor}44`,
          borderLeft: `3px solid ${rankColor}`,
          borderRadius: 10,
          padding: '10px 14px',
          minWidth: 260,
          maxWidth: 340,
          cursor: 'pointer',
          animation: 'slide-in 0.25s ease-out',
        }}
      >
        {/* Keyed by seq so each in-place update remounts and replays the pulse. */}
        <div key={toast.seq} style={{ animation: toast.seq > 0 ? 'lvl-pulse 0.4s ease-out' : undefined }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 14 }}>{icon}</span>
            <span style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: 13 }}>
              {title}
            </span>
            {!isCC && (
              <span style={{
                fontSize: 10, fontWeight: 500, padding: '1px 6px', borderRadius: 4,
                background: `${rankColor}22`, color: rankColor,
              }}>
                {toast.new_rank}
              </span>
            )}
          </div>

          {subtitle && (
            <div style={{
              fontSize: 11,
              color: isCC ? 'var(--text-secondary)' : 'var(--text-success)',
              paddingLeft: indent,
            }}>
              {subtitle}
            </div>
          )}

          {toast.absorbed > 0 && (
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, paddingLeft: indent }}>
              +{toast.absorbed} more level-up{toast.absorbed > 1 ? 's' : ''}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
