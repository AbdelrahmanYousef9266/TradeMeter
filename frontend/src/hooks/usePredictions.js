import { useEffect } from 'react'
import useStore from '../store'
import { getModels } from '../services/api'

/**
 * Hydrates + keeps the model grid in sync with the DISPLAYED context.
 *
 * In LIVE mode the per-bar WebSocket already streams live model updates; this
 * poll simply seeds them and reconciles. In OFFLINE mode there is no per-bar WS
 * (the bulk-import fast path only emits throttled progress), so this poll of
 * /models?context=offline is what makes the offline models visibly learn —
 * levels climbing, signals updating — while a training run is in progress.
 *
 * displayContext is set by the mode banner (store.setMode); switching it clears
 * the maps so the two contexts never mix.
 */
export function usePredictions() {
  const { modelSignals, modelLevels, updateModelSignal, updateModelLevel } = useStore()
  const displayContext = useStore(s => s.displayContext)

  useEffect(() => {
    let active = true

    const load = () => getModels(displayContext)
      .then(res => {
        if (!active) return
        res.data?.forEach(model => {
          const tf = model.timeframe || '5min'
          if (model.level_info) updateModelLevel(model.name, model.level_info, tf)
          if (model.signal)     updateModelSignal(model.name, model.signal, tf)
        })
      })
      .catch(err => {
        console.error('[Predictions] load failed:', err.response?.status, err.message)
      })

    load()
    // Poll so an offline training run animates (levels climb) and the live grid
    // reconciles with the backend even between WS bars.
    const id = setInterval(load, 2500)
    return () => { active = false; clearInterval(id) }
  }, [displayContext])

  return { modelSignals, modelLevels }
}
