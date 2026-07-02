import { create } from 'zustand'

const useStore = create((set) => ({
  // Auth
  user: null,
  setUser: (user) => set({ user }),

  // NT connection status (from WebSocket open/close)
  ntConnected: false,
  setNtConnected: (v) => set(state => ({
    ntConnected: v,
    warmup: { ...state.warmup, ntConnected: v },
  })),

  // Warmup progress — updated from WS tick messages during the 50-bar warmup period
  warmup: {
    barsReceived: 0,
    barsNeeded:   50,
    isWarmingUp:  true,
    ntConnected:  false,
  },
  setWarmup: (partial) => set(state => ({
    warmup: { ...state.warmup, ...partial },
  })),

  // Live bar data
  currentBar: null,
  barHistory: [],
  // Epoch ms of the last bar/tick received over the WebSocket. Lets pages tell
  // whether market data is actively streaming (live OR replay) vs. idle,
  // independent of the real-world clock.
  lastBarAt: 0,
  // setBar: appends a new candle to history — use for bar closes only
  setBar: (bar) => set(state => ({
    currentBar: bar,
    barHistory: [...state.barHistory.slice(-199), bar],
    lastBarAt: Date.now(),
  })),
  // setCurrentBar: updates live price display only — use for ticks and warmup bars
  setCurrentBar: (bar) => set({ currentBar: bar, lastBarAt: Date.now() }),
  // setBarHistory: bulk-replace history (used to hydrate the chart on page load)
  setBarHistory: (bars) => set({ barHistory: bars, currentBar: bars[bars.length - 1] ?? null }),

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

  // Session P&L keyed by model name
  // Each entry: { points, dollars, wins, losses, open }
  modelPnl: {},
  updateModelPnl: (name, pnl) => set(state => ({
    modelPnl: { ...state.modelPnl, [name]: pnl },
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
