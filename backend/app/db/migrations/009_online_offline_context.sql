-- ONLINE/OFFLINE separation -- per-context model state and levels.
--
-- Until now a user had ONE set of models per (model_name, timeframe), and a
-- "training mode" flag mutated those same live models in place from historical
-- bars. Phase 3 splits every model into two independent contexts:
--
--     context = 'live'    -- serves live trading, learns only from live bars
--     context = 'offline' -- a COPY trained on history, never touches live
--
-- so a historical training run learns on its own weights and is only ever merged
-- into live via an explicit promotion. Add a context dimension to model_levels
-- and model_state and fold it into the primary key so the same
-- (user, model_name, timeframe) can exist once per context without colliding.
--
-- Existing rows ARE the current live weights, so they default to 'live'. The
-- offline context starts empty and is seeded as a copy of live on the first
-- offline run.

ALTER TABLE model_levels ADD COLUMN IF NOT EXISTS context TEXT NOT NULL DEFAULT 'live';
ALTER TABLE model_state  ADD COLUMN IF NOT EXISTS context TEXT NOT NULL DEFAULT 'live';

-- Repoint the primary keys to include context so (user, model_name, timeframe)
-- can appear once per context without colliding.
ALTER TABLE model_levels DROP CONSTRAINT IF EXISTS model_levels_pkey;
ALTER TABLE model_levels ADD  CONSTRAINT model_levels_pkey PRIMARY KEY (user_id, model_name, timeframe, context);

ALTER TABLE model_state DROP CONSTRAINT IF EXISTS model_state_pkey;
ALTER TABLE model_state ADD  CONSTRAINT model_state_pkey PRIMARY KEY (user_id, model_name, timeframe, context);
