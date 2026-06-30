-- ML model-state persistence.
-- Stores the pickled River models (Champion/Challenger wrappers + Personal model)
-- so learned weights survive a backend restart instead of resetting to untrained.
-- One row per (user_id, model_name). model_name is one of the 8 personality
-- model names or 'personal'.

CREATE TABLE IF NOT EXISTS model_state (
  user_id    UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  model_name TEXT        NOT NULL,
  state      BYTEA       NOT NULL,
  bars_count INTEGER     NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, model_name)
);
