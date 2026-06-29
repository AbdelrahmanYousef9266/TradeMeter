-- Level 3 P&L columns on predictions table
-- Safe to run on every startup (IF NOT EXISTS / idempotent ALTER)

ALTER TABLE predictions
  ADD COLUMN IF NOT EXISTS pnl_points  DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS pnl_dollars DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS exit_reason TEXT,
  ADD COLUMN IF NOT EXISTS bars_held   INTEGER;
