-- Multi-timeframe support (Phase 1 -- data layer only).
--
-- Until now every bar lived in ticks keyed by (user_id, time), with dedup by
-- timestamp alone. That breaks with two timeframes because a 1-min and a 5-min
-- bar can share a timestamp (e.g. both at 09:35:00) yet are DIFFERENT series.
-- Add a timeframe dimension so each timeframe is an independent series.
--
-- Uniqueness/dedup semantics become (user_id, timeframe, time). ticks is a
-- TimescaleDB hypertable with no unique constraint, so dedup is enforced at
-- query time via DISTINCT ON. This migration only needs the column plus indexes.
-- The DISTINCT ON / watermark / COPY paths are updated in the ingestion code.

ALTER TABLE ticks       ADD COLUMN IF NOT EXISTS timeframe TEXT NOT NULL DEFAULT '1min';
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS timeframe TEXT NOT NULL DEFAULT '1min';

-- Timeframe-aware access paths. A 1-min and a 5-min bar at the same timestamp are
-- separate rows and both must persist. These indexes keep per-timeframe reads and
-- the live-view (is_training = false) queries fast.
CREATE INDEX IF NOT EXISTS idx_ticks_user_tf_time
    ON ticks (user_id, timeframe, time DESC);

CREATE INDEX IF NOT EXISTS idx_ticks_user_tf_live_time
    ON ticks (user_id, timeframe, time DESC)
    WHERE is_training = false;

CREATE INDEX IF NOT EXISTS idx_predictions_user_tf_model_time
    ON predictions (user_id, timeframe, model_name, time DESC);
