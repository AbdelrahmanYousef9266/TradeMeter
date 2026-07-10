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
export const getModelLevel     = (name, timeframe = '5min') => api.get(`/models/${name}/level`, { params: { timeframe } })
export const getModelSettings  = (name, timeframe = '5min') => api.get(`/models/${name}/settings`, { params: { timeframe } })
export const updateModelSettings = (name, d, timeframe = '5min') => api.put(`/models/${name}/settings`, d, { params: { timeframe } })
export const resetModel        = (name, timeframe = '5min') => api.post(`/models/${name}/reset`, null, { params: { timeframe } })
export const getLeaderboardPnl = ()           => api.get('/models/leaderboard')
export const getLeaderboardLvl = ()           => api.get('/models/leaderboard/levels')
export const getModelHistory   = (name, p)   => api.get(`/models/${name}/history`, { params: p })

export const getHistory            = (params) => api.get('/market/history',      { params })
export const getMarketStatus       = ()       => api.get('/market/status')
export const getRecentBars         = (limit = 200, timeframe = '5min') => api.get('/market/bars', { params: { limit, timeframe } })
export const getDataCoverage       = ()       => api.get('/market/coverage')
export const getDataSummary        = (timeframe = '1min')         => api.get('/market/data-summary', { params: { timeframe } })
export const getDataDays           = (month, timeframe = '1min')  => api.get('/market/data-days', { params: { month, timeframe } })
export const getDataIntegrity      = (timeframe = '1min')         => api.get('/market/data-integrity', { params: { timeframe } })
export const getPredictionsHistory = (params) => api.get('/predictions/history', { params })
export const getLatestPredictions  = (timeframe = '5min') => api.get('/predictions/latest', { params: { timeframe } })

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
export const flushQueue        = () => api.post('/training/flush-queue')

// Ingestion arm gate — decide WHEN strategy bars enter the pipeline
export const armIngestion       = ()              => api.post('/ingestion/arm')
export const disarmIngestion    = (flush = false) => api.post('/ingestion/disarm', { flush })
export const getIngestionStatus = ()              => api.get('/ingestion/status')

// System resources — real CPU/RAM for the AI Lab stream panel
export const getSystemStats    = () => api.get('/system/stats')

export default api
