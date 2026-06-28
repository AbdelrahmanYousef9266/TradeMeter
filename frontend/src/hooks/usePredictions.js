import { useEffect } from 'react'
import useStore from '../store'
import { getModels } from '../services/api'

export function usePredictions() {
  const { modelSignals, modelLevels, updateModelSignal, updateModelLevel } = useStore()

  useEffect(() => {
    getModels()
      .then(res => {
        res.data.forEach(model => {
          if (model.signal) {
            updateModelSignal(model.model_name, {
              signal:     model.signal,
              confidence: model.confidence,
            })
          }
          updateModelLevel(model.model_name, {
            level:           model.level,
            xp_progress_pct: model.xp_progress_pct,
            streak:          model.streak,
            rank:            model.rank,
            bars_learned:    model.bars_learned,
          })
        })
      })
      .catch(() => {})
  }, [])

  return { modelSignals, modelLevels }
}
