// Per-model settings page — shows current level, rank, and XP bar at top
// Settings are gated by rank:
//   - Rookie: read-only view of base settings
//   - Apprentice: confidence threshold slider unlocked
//   - Pro: signal mode presets unlocked
//   - Elite: blend weight visible and adjustable
//   - Expert: aggressive settings section unlocked
//   - Master: all settings fully unlocked
// Locked settings show a lock icon and tooltip: "Reach [Rank] to unlock"
// Save button applies changes immediately — model picks them up on next bar
// Reset button resets settings to defaults for current rank (does not reset level)
