import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  withCredentials: true,
})

api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401 && window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export const getMe             = ()           => api.get('/auth/me')
export const getNTStatus       = ()           => api.get('/auth/nt-status')
export const getNTToken        = ()           => api.get('/auth/nt-token')
export const resetNTToken      = ()           => api.post('/auth/nt-token/reset')
export const logout            = ()           => api.post('/auth/logout')

export const getModels         = ()           => api.get('/models')
export const getModelLevel     = (name)       => api.get(`/models/${name}/level`)
export const getModelSettings  = (name)       => api.get(`/models/${name}/settings`)
export const updateModelSettings = (name, d) => api.put(`/models/${name}/settings`, d)
export const resetModel        = (name)       => api.post(`/models/${name}/reset`)
export const getLeaderboardPnl = ()           => api.get('/models/leaderboard')
export const getLeaderboardLvl = ()           => api.get('/models/leaderboard/levels')
export const getModelHistory   = (name, p)   => api.get(`/models/${name}/history`, { params: p })

export const getHistory            = (params) => api.get('/market/history',      { params })
export const getMarketStatus       = ()       => api.get('/market/status')
export const getRecentBars         = (limit = 200) => api.get(`/market/bars?limit=${limit}`)
export const getDataCoverage       = ()       => api.get('/market/coverage')
export const getPredictionsHistory = (params) => api.get('/predictions/history', { params })
export const getLatestPredictions  = ()       => api.get('/predictions/latest')

export const getCCStatus    = ()     => api.get('/cc')
export const getModelCC     = (name) => api.get(`/cc/${name}`)
export const forceEvaluation = (name) => api.post(`/cc/${name}/evaluate`)

// Model 11 — Deep LSTM
export const getLSTMStatus = () => api.get('/models/lstm/status')
export const trainLSTM     = () => api.post('/models/lstm/train')

// Training Mode — replay historical data to train the models
export const startTraining     = () => api.post('/training/start')
export const stopTraining      = () => api.post('/training/stop')
export const getTrainingStatus = () => api.get('/training/status')

export default api
