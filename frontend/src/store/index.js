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

  // ── Multi-timeframe model maps ────────────────────────────────────────────
  // Phase 2: the same model_name runs on BOTH the 1-min and 5-min series as
  // independent competitors, so these maps are keyed by the composite id
  // `${name}:${timeframe}` (e.g. "momentum:5min") — matching the backend's `id`.
  // Read with modelKey(name, tf). Updaters default to the primary (5-min).

  // Each entry: { signal, confidence, direction_up, direction_down, predicted_high, predicted_low }
  modelSignals: {},
  updateModelSignal: (name, signal, timeframe = '5min') => set(state => ({
    modelSignals: { ...state.modelSignals, [`${name}:${timeframe}`]: signal },
  })),

  // Each entry: { level, xp, streak, rank, xp_progress_pct, unlocked_settings }
  modelLevels: {},
  updateModelLevel: (name, level, timeframe = '5min') => set(state => ({
    modelLevels: { ...state.modelLevels, [`${name}:${timeframe}`]: level },
  })),

  // Each entry: { points, dollars, wins, losses, open }
  modelPnl: {},
  updateModelPnl: (name, pnl, timeframe = '5min') => set(state => ({
    modelPnl: { ...state.modelPnl, [`${name}:${timeframe}`]: pnl },
  })),

  // Which timeframe's candles the live chart renders (both series stream now;
  // rendering one keeps the chart from interleaving 1-min and 5-min bars).
  chartTimeframe: '5min',
  setChartTimeframe: (tf) => set({ chartTimeframe: tf, barHistory: [], currentBar: null }),

  // ── System MODE + displayed context ───────────────────────────────────────
  // mode is the backend's per-user LIVE|OFFLINE state (polled from GET /mode).
  // displayContext is which model set the dashboard shows: 'live' in LIVE mode,
  // 'offline' in OFFLINE mode (so you can watch a training run). The model maps
  // above hold ONE context at a time — switching context CLEARS them so offline
  // data never renders on a live card or vice versa. WS/poll updates carrying a
  // different context are dropped (see useWebSocket + usePredictions).
  mode: 'live',
  displayContext: 'live',
  setMode: (mode) => set(state => {
    if (state.mode === mode) return {}
    return {
      mode,
      displayContext: mode === 'offline' ? 'offline' : 'live',
      // Purge the other context's cards so the two never mix.
      modelSignals: {}, modelLevels: {}, modelPnl: {},
      leaderboardPnl: [], leaderboardLevels: [],
    }
  }),

  // Offline training progress (from WS "training_progress" batches): bars
  // processed this run + queue depth. Drives the offline banner.
  offlineProgress: { processed: 0, queuePending: 0 },
  setOfflineProgress: (p) => set(state => ({ offlineProgress: { ...state.offlineProgress, ...p } })),

  // Leaderboard data
  leaderboardPnl:    [],
  leaderboardLevels: [],
  setLeaderboardPnl:    (data) => set({ leaderboardPnl: data }),
  setLeaderboardLevels: (data) => set({ leaderboardLevels: data }),

  // Single-slot level-up / CC-promotion toast (coalesced — never a growing stack).
  // We keep ONE toast object instead of a queue that could balloon to tens of
  // thousands of entries during a bulk import. Each new event replaces the
  // content in place:
  //   • seq       bumps on every event  → drives the refresh pulse + timer reset
  //   • absorbed  counts extra events folded in while this toast has been visible
  //               → renders as "(+N more level-ups)"
  // Dropped events are never shown later; only the latest is displayed.
  levelUpToast: null,
  pushLevelUp: (event) => set(state => {
    const prev = state.levelUpToast
    return {
      levelUpToast: {
        ...event,
        seq:      prev ? prev.seq + 1 : 0,
        absorbed: prev ? prev.absorbed + 1 : 0,
      },
    }
  }),
  dismissLevelUp: () => set({ levelUpToast: null }),

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

// Composite key for the timeframe-scoped model maps (modelSignals/Levels/Pnl).
export const modelKey = (name, timeframe = '5min') => `${name}:${timeframe}`

export default useStore
