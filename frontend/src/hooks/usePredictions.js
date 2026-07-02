import { useEffect } from 'react'
import useStore from '../store'
import { getModels } from '../services/api'

export function usePredictions() {
  const { modelSignals, modelLevels, updateModelSignal, updateModelLevel } = useStore()

  useEffect(() => {
    getModels()
      .then(res => {
        res.data?.forEach(model => {
          if (model.level_info) {
            updateModelLevel(model.name, model.level_info)
          }
          if (model.signal) {
            updateModelSignal(model.name, model.signal)
          }
        })
      })
      .catch(err => {
        console.error('[Predictions] load failed:', err.response?.status, err.message)
      })
  }, [])

  return { modelSignals, modelLevels }
}
