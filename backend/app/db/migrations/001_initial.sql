CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT        NOT NULL UNIQUE,
    google_id       TEXT        NOT NULL UNIQUE,
    nt_token_hash   TEXT,
    nt_token_prefix TEXT,
    nt_connected    BOOLEAN     NOT NULL DEFAULT FALSE,
    nt_last_seen    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ticks (
    time        TIMESTAMPTZ         NOT NULL,
    user_id     UUID                NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol      TEXT                NOT NULL,
    open        DOUBLE PRECISION    NOT NULL,
    high        DOUBLE PRECISION    NOT NULL,
    low         DOUBLE PRECISION    NOT NULL,
    close       DOUBLE PRECISION    NOT NULL,
    volume      BIGINT              NOT NULL,
    bar_type    TEXT                NOT NULL DEFAULT '1min'
);
SELECT create_hypertable('ticks', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS predictions (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    time              TIMESTAMPTZ NOT NULL,
    user_id           UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model_name        TEXT        NOT NULL,
    signal            TEXT        NOT NULL CHECK (signal IN ('BUY', 'SELL', 'HOLD')),
    confidence        DOUBLE PRECISION,
    predicted_high    DOUBLE PRECISION,
    predicted_low     DOUBLE PRECISION,
    direction_up_prob DOUBLE PRECISION,
    actual_outcome    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_settings (
    user_id      UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model_name   TEXT        NOT NULL,
    settings_json JSONB      NOT NULL DEFAULT '{}',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_ticks_user_time
    ON ticks (user_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_predictions_user_model_time
    ON predictions (user_id, model_name, time DESC);
