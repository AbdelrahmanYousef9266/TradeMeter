-- Security hardening: stop storing the NT connection token in plaintext.
--
-- Previously nt_token_prefix held the FULL plaintext token (used for an exact
-- lookup), which defeated the bcrypt hash entirely. We now keep:
--   nt_token_hash    — bcrypt hash for final verification (unchanged)
--   nt_token_lookup  — SHA-256 hex digest, queryable index (NEW)
--   nt_token_prefix  — masked display value only ("TM-••••")
--
-- pgcrypto (enabled in 001_initial.sql) provides digest() for the backfill.

ALTER TABLE users ADD COLUMN IF NOT EXISTS nt_token_lookup TEXT;

-- Backfill the lookup index from any legacy full-token prefixes (pre-hardening
-- rows store the 9-char "TM-XXXXXX" plaintext in nt_token_prefix).
UPDATE users
   SET nt_token_lookup = encode(digest(nt_token_prefix, 'sha256'), 'hex')
 WHERE nt_token_lookup IS NULL
   AND nt_token_prefix IS NOT NULL
   AND nt_token_prefix LIKE 'TM-%'
   AND length(nt_token_prefix) = 9;

-- Redact the legacy plaintext now that the lookup index exists.
UPDATE users
   SET nt_token_prefix = 'TM-••••'
 WHERE nt_token_prefix IS NOT NULL
   AND nt_token_prefix LIKE 'TM-%'
   AND length(nt_token_prefix) = 9;

CREATE INDEX IF NOT EXISTS idx_users_nt_token_lookup
    ON users (nt_token_lookup);
