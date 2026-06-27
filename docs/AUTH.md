# Auth Design

## Two-Step Flow Overview

TradeMeter uses two separate auth mechanisms that together form a complete identity chain:

1. **Google OAuth** — authenticates the human user in the browser, issues a JWT session cookie
2. **NT Connection Token** — authenticates the NinjaTrader TCP connection, maps it to the authenticated user

This two-step design exists because NinjaTrader runs as a local desktop application with no ability to participate in a browser-based OAuth flow.

---

## Step 1: Google OAuth

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/auth/google` | Redirects user to Google consent screen |
| `GET` | `/auth/google/callback` | Handles OAuth callback, creates session |
| `POST` | `/auth/logout` | Clears session cookie |
| `GET` | `/auth/me` | Returns current user from JWT |

### Flow

1. Frontend redirects to `/auth/google`
2. Backend redirects to Google with `client_id`, `redirect_uri`, `scope=openid email profile`
3. User consents; Google redirects to `/auth/google/callback?code=...`
4. Backend exchanges code for Google tokens, fetches user info
5. Backend creates or updates a user record in TimescaleDB
6. Backend mints a JWT, sets it as an `HttpOnly` cookie
7. Frontend is redirected to `/connect` page

### User Record Creation

On first login, a user record is created with:
- `google_id` (stable Google sub claim)
- `email`
- `display_name`
- A freshly generated `nt_connection_token` (format: `TM-[6 random alphanumeric chars]`)

On subsequent logins, the user record is updated but the `nt_connection_token` is preserved unless the user explicitly rotates it.

---

## Step 2: NT Connection Token

### How It's Generated

```python
import secrets, string
alphabet = string.ascii_letters + string.digits
token = "TM-" + "".join(secrets.choice(alphabet) for _ in range(6))
# e.g. "TM-a3f9x2"
```

The token is stored **hashed** (SHA-256) in the database. The plaintext is only shown to the user once on the Connect page.

### How NinjaTrader Uses It

The strategy reads the `ConnectionToken` parameter and prepends it to every TCP message:

```json
{"token": "TM-a3f9x2", "ts": 1719400000, "open": 5100.25, "high": 5101.50, "low": 5099.75, "close": 5100.75, "volume": 342}
```

### How the Backend Validates It

On the first message from a new TCP connection:
1. Extract `token` from the JSON payload
2. SHA-256 hash the token
3. Look up the hash in the `users` table
4. If found: cache `tcp_connection_id → user_id` in Redis (TTL: 24 hours)
5. If not found: close the TCP connection immediately

Subsequent messages on the same TCP connection use the cached `user_id` without re-querying the database.

---

## JWT Structure

```json
{
  "sub": "42",
  "email": "user@example.com",
  "name": "Jane Trader",
  "iat": 1719400000,
  "exp": 1719486400
}
```

The JWT is signed with HS256 using `JWT_SECRET` from `.env`. Expiry is controlled by `JWT_EXPIRE_HOURS` (default: 24).

---

## Security Notes

- The JWT cookie is `HttpOnly` and `SameSite=Lax` to prevent XSS and CSRF
- The NT connection token is stored hashed; the plaintext is never persisted
- All traffic should be behind HTTPS in production (Nginx terminates TLS)
- TCP connections without a valid token are closed within one message exchange
- Users can rotate their NT token from the Settings page, immediately invalidating the old one
- `GOOGLE_REDIRECT_URI` must exactly match the URI allowlisted in Google Cloud Console
