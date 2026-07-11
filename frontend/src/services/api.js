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

export const getModels         = (context = 'live') => api.get('/models', { params: { context } })
export const getModelLevel     = (name, timeframe = '5min', context = 'live') => api.get(`/models/${name}/level`, { params: { timeframe, context } })
export const getModelSettings  = (name, timeframe = '5min', context = 'live') => api.get(`/models/${name}/settings`, { params: { timeframe, context } })
export const updateModelSettings = (name, d, timeframe = '5min', context = 'live') => api.put(`/models/${name}/settings`, d, { params: { timeframe, context } })
export const resetModel        = (name, timeframe = '5min', context = 'live') => api.post(`/models/${name}/reset`, null, { params: { timeframe, context } })
export const getLeaderboardPnl = (context = 'live') => api.get('/models/leaderboard', { params: { context } })
export const getLeaderboardLvl = (context = 'live') => api.get('/models/leaderboard/levels', { params: { context } })
export const getModelHistory   = (name, p)   => api.get(`/models/${name}/history`, { params: p })

// Promotion — the ONLY path from offline-trained weights to live trading
export const getPromotionPreview  = (timeframe = 'all') => api.get('/models/promotion-preview', { params: { timeframe } })
export const promoteOfflineToLive = (timeframe = 'all') => api.post('/models/promote', { timeframe, confirm: 'PROMOTE' })

export const getHistory            = (params) => api.get('/market/history',      { params })
export const getMarketStatus       = ()       => api.get('/market/status')
export const getRecentBars         = (limit = 200, timeframe = '5min') => api.get('/market/bars', { params: { limit, timeframe } })
export const getDataCoverage       = ()       => api.get('/market/coverage')
export const getDataSummary        = (timeframe = '1min')         => api.get('/market/data-summary', { params: { timeframe } })
export const getDataDays           = (month, timeframe = '1min')  => api.get('/market/data-days', { params: { month, timeframe } })
export const getDataIntegrity      = (timeframe = '1min')         => api.get('/market/data-integrity', { params: { timeframe } })
export const getPredictionsHistory = (params) => api.get('/predictions/history', { params })
export const getLatestPredictions  = (timeframe = '5min', context = 'live') => api.get('/predictions/latest', { params: { timeframe, context } })

export const getCCStatus    = ()     => api.get('/cc')
export const getModelCC     = (name) => api.get(`/cc/${name}`)
export const forceEvaluation = (name) => api.post(`/cc/${name}/evaluate`)

// Model 11 — Deep LSTM
export const getLSTMStatus = () => api.get('/models/lstm/status')
export const trainLSTM     = () => api.post('/models/lstm/train')

// System MODE — the source of truth for ONLINE (live) vs OFFLINE (training on
// history). Switching requires a drained queue; pass flush=true to flush-and-switch
// (the backend returns 409 otherwise).
export const getMode        = ()              => api.get('/mode')
export const setModeLive    = (flush = false) => api.post('/mode/live',    { flush })
export const setModeOffline = (flush = false) => api.post('/mode/offline', { flush })

// Training Mode — thin aliases over the mode switch (offline == old training mode)
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
