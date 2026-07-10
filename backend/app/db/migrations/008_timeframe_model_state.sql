-- Multi-timeframe Phase 2 -- per-timeframe model state and levels.
--
-- Until now a user had ONE set of models (keyed by model_name), learned from
-- 1-min bars. Phase 2 runs the full personality set on BOTH 1-min and 5-min as
-- independent competitors, so the same model_name (e.g. 'momentum') now exists
-- once per timeframe and must persist separately -- a 5-min Momentum's weights
-- and level must not collide with the 1-min Momentum's.
--
-- Add a timeframe dimension to model_levels and model_state and fold it into the
-- primary key. Existing rows were learned from 1-min data, so they default to
-- '1min' (the 1-min pipeline restores them, the 5-min pipeline starts fresh and
-- is trained via a training-mode reprocess of the already-stored 5-min bars).

ALTER TABLE model_levels ADD COLUMN IF NOT EXISTS timeframe TEXT NOT NULL DEFAULT '1min';
ALTER TABLE model_state  ADD COLUMN IF NOT EXISTS timeframe TEXT NOT NULL DEFAULT '1min';

-- Repoint the primary keys to include timeframe so (user, model_name) can appear
-- once per timeframe without colliding.
ALTER TABLE model_levels DROP CONSTRAINT IF EXISTS model_levels_pkey;
ALTER TABLE model_levels ADD  CONSTRAINT model_levels_pkey PRIMARY KEY (user_id, model_name, timeframe);

ALTER TABLE model_state DROP CONSTRAINT IF EXISTS model_state_pkey;
ALTER TABLE model_state ADD  CONSTRAINT model_state_pkey PRIMARY KEY (user_id, model_name, timeframe);
