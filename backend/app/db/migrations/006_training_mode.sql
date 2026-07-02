-- Training Mode: replay historical sessions to train the models without
-- polluting the live dataset or advancing the live watermark.
--
-- Bars (and the predictions/trades derived from them) ingested while a user is
-- in training mode are tagged is_training = true. Live-view queries filter
-- is_training = false so the chart, coverage calendar, and monotonic watermark
-- only ever reflect real forward data.

ALTER TABLE ticks       ADD COLUMN IF NOT EXISTS is_training BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS is_training BOOLEAN NOT NULL DEFAULT false;

-- Partial index so the hot live-view queries (watermark seed, chart hydration,
-- coverage) stay fast while ignoring training rows.
CREATE INDEX IF NOT EXISTS idx_ticks_user_live_time
    ON ticks (user_id, time DESC)
    WHERE is_training = false;
