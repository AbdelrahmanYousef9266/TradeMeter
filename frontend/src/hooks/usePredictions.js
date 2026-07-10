import { useEffect } from 'react'
import useStore from '../store'
import { getModels } from '../services/api'

export function usePredictions() {
  const { modelSignals, modelLevels, updateModelSignal, updateModelLevel } = useStore()

  useEffect(() => {
    getModels()
      .then(res => {
        res.data?.forEach(model => {
          // Each model entry is tagged with its timeframe (Phase 2) — key the
          // store maps by (name, timeframe) so the two series stay distinct.
          const tf = model.timeframe || '5min'
          if (model.level_info) {
            updateModelLevel(model.name, model.level_info, tf)
          }
          if (model.signal) {
            updateModelSignal(model.name, model.signal, tf)
          }
        })
      })
      .catch(err => {
        console.error('[Predictions] load failed:', err.response?.status, err.message)
      })
  }, [])

  return { modelSignals, modelLevels }
}
