# Model management endpoints:
# GET  /models                    — all 10 models with current signal, accuracy, level, rank
# GET  /models/{id}               — single model detail including full level info
# GET  /models/{id}/settings      — model behavior settings (filtered by rank unlocks)
# PUT  /models/{id}/settings      — update settings (validates against rank unlock gates)
# POST /models/{id}/reset         — reset model weights (keeps level and XP)
# GET  /models/{id}/history       — accuracy + XP history over time
# GET  /models/{id}/level         — current level, XP, streak, rank, unlocked settings
# GET  /models/leaderboard        — ranked by today P&L
# GET  /models/leaderboard/levels — ranked by model level
