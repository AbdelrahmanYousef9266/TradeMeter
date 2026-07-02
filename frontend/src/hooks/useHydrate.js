import { useEffect } from 'react'
import useStore from '../store'
import { getMarketStatus, getRecentBars } from '../services/api'

/**
 * Hydrate warmup/connection state and chart history from REST on mount, so a
 * page refresh reflects the true backend pipeline state immediately instead of
 * waiting for the next WebSocket message (which never arrives while paused).
 *
 * Live WebSocket messages continue to override these values as they arrive —
 * hydration only sets the starting point.
 *
 * NOTE: this addresses page refresh, where the backend state is intact. If the
 * backend itself restarts, its in-memory FeatureEngine genuinely resets and
 * warmup correctly restarts at 0 — that is expected, not a bug.
 */
export function useHydrate() {
  const { setWarmup, setNtConnected, setBarHistory } = useStore()

  useEffect(() => {
    // Warmup / connection state
    getMarketStatus()
      .then(res => {
        const s = res.data
        setNtConnected(s.nt_connected)   // sets top-level ntConnected + warmup.ntConnected
        setWarmup({
          barsReceived: s.bars_received,
          barsNeeded:   s.bars_needed,
          isWarmingUp:  s.warming_up,
        })
      })
      .catch(() => {})

    // Chart history
    getRecentBars(200)
      .then(res => {
        if (Array.isArray(res.data) && res.data.length > 0) {
          setBarHistory(res.data)
        }
      })
      .catch(() => {})
  }, [])
}
