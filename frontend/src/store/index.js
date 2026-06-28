import { create } from 'zustand'

const useStore = create((set) => ({
  // Auth
  user: null,
  setUser: (user) => set({ user }),

  // NT connection status (from WebSocket open/close)
  ntConnected: false,
  setNtConnected: (v) => set({ ntConnected: v }),

  // Live bar data
  currentBar: null,
  barHistory: [],
  setBar: (bar) => set(state => ({
    currentBar: bar,
    barHistory: [...state.barHistory.slice(-199), bar],
  })),

  // Model signals keyed by model name
  // Each entry: { signal, confidence, direction_up, direction_down, predicted_high, predicted_low }
  modelSignals: {},
  updateModelSignal: (name, signal) => set(state => ({
    modelSignals: { ...state.modelSignals, [name]: signal },
  })),

  // Model level info keyed by model name
  // Each entry: { level, xp, streak, rank, xp_progress_pct, unlocked_settings }
  modelLevels: {},
  updateModelLevel: (name, level) => set(state => ({
    modelLevels: { ...state.modelLevels, [name]: level },
  })),

  // Leaderboard data
  leaderboardPnl:    [],
  leaderboardLevels: [],
  setLeaderboardPnl:    (data) => set({ leaderboardPnl: data }),
  setLeaderboardLevels: (data) => set({ leaderboardLevels: data }),

  // Level-up notification queue
  levelUpQueue: [],
  pushLevelUp: (event) => set(state => ({
    levelUpQueue: [...state.levelUpQueue, { ...event, id: Date.now() + Math.random() }],
  })),
  dismissLevelUp: (id) => set(state => ({
    levelUpQueue: state.levelUpQueue.filter(e => e.id !== id),
  })),

  // Global settings (persisted to localStorage manually in Settings page)
  settings: {
    instrument:  'MES 03-25',
    barType:     '1min',
    indicators: {
      rsi:         true,
      ema9:        true,
      ema21:       true,
      ema50:       true,
      macd:        true,
      atr:         true,
      volumeDelta: true,
    },
  },
  setSettings: (settings) => set({ settings }),
}))

export default useStore
