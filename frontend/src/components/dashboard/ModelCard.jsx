// Single model card component showing:
// - Model name, personality tag
// - Signal badge (BUY/SELL/HOLD + confidence %)
// - Rank badge (Rookie/Apprentice/Pro/Elite/Expert/Master) with rank color
// - XP progress bar (0–100% to next level) with level number
// - Streak counter (highlighted green when streak >= 5)
// - Accuracy %, today P&L, price target, stop level
// - Unlocked settings chips (gray = locked, green = unlocked)
// - "Tune behavior" button (links to ModelSettings page)
// Personal models (9/10) have accent border and show blend weights + learning status
// Level-up animation plays when a level_up WebSocket event is received for this model
