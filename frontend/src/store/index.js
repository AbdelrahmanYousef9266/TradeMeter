// Zustand global store — state shape:
// {
//   user: { id, email, ntConnected },
//   currentBar: { time, open, high, low, close, volume },
//   modelSignals: { [modelName]: { signal, confidence, direction, target } },
//   modelLevels: { [modelName]: { level, xp, streak, rank, xpProgressPct, unlockedSettings } },
//   leaderboard: { pnl: [...], levels: [...] },
//   levelUpQueue: [LevelUpEvent],   // notifications waiting to display
//   settings: { instrument, barType, indicators }
// }
// Actions: setUser, setBar, updateModelSignal, updateModelLevel,
//          updateLeaderboard, pushLevelUpNotification, dismissLevelUp, setSettings
