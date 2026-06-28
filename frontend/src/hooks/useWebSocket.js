// Custom hook — connects to WS /market/live, handles two message types:
// 1. bar update: { time, bar, models } → updates currentBar + all modelSignals in store
// 2. level_up:  { type:"level_up", model_name, new_level, new_rank, unlocked }
//              → pushes to levelUpQueue in store, triggers toast notification
// Handles reconnect with exponential backoff (1s → 2s → 4s → max 30s)
// Cleans up WebSocket on component unmount
