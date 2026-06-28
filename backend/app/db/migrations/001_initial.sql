CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  google_id TEXT NOT NULL UNIQUE,
  nt_token_hash TEXT,
  nt_connected BOOLEAN DEFAULT FALSE,
  nt_last_seen TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ticks (
  time TIMESTAMPTZ NOT NULL,
  user_id UUID NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  open DOUBLE PRECISION,
  high DOUBLE PRECISION,
  low DOUBLE PRECISION,
  close DOUBLE PRECISION,
  volume BIGINT,
  bar_type TEXT
);
SELECT create_hypertable('ticks', 'time');

CREATE TABLE predictions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  time TIMESTAMPTZ NOT NULL,
  user_id UUID NOT NULL REFERENCES users(id),
  model_name TEXT NOT NULL,
  signal TEXT NOT NULL,
  confidence DOUBLE PRECISION,
  predicted_high DOUBLE PRECISION,
  predicted_low DOUBLE PRECISION,
  direction_up_prob DOUBLE PRECISION,
  actual_outcome TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE model_settings (
  user_id UUID NOT NULL REFERENCES users(id),
  model_name TEXT NOT NULL,
  settings_json JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, model_name)
);

CREATE INDEX ON ticks (user_id, time DESC);
CREATE INDEX ON predictions (user_id, model_name, time DESC);
