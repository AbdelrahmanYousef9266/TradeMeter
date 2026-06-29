-- Champion/Challenger promotion history table

CREATE TABLE IF NOT EXISTS cc_history (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  model_name     TEXT NOT NULL,
  winner         TEXT NOT NULL,
  champion_pnl   DOUBLE PRECISION,
  challenger_pnl DOUBLE PRECISION,
  old_params     JSONB,
  new_params     JSONB,
  bars_evaluated INTEGER,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cc_history_user ON cc_history (user_id, created_at DESC);
