# ADWIN drift detector wrapper — one detector instance per model per user.
# Monitors rolling accuracy. If accuracy drops below DRIFT_ACCURACY_THRESHOLD (default 0.60):
#   - fires dashboard alert via Redis pub/sub
#   - resets River model weights to initial state
#   - resets XP streak to 0 (drift = broken streak)
#   - does NOT reset level or total XP (model keeps its rank, just loses streak bonus)
# Other models are unaffected when one drifts.
