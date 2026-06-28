# Auth Design

## Two-Step Auth Flow Overview

TradeMeter uses two separate auth mechanisms that together form a complete identity chain:

1. **Google OAuth** — authenticates the human user in the browser, issues a JWT in an httpOnly cookie
2. **NT Connection Token** — authenticates the NinjaTrader TCP connection, maps it permanently to the authenticated user

This two-step design exists because NinjaTrader runs as a local desktop application (.NET 4.8) with no ability to participate in a browser OAuth flow. The connection token is the bridge.

---

## Step 1: Google OAuth

### Flow

1. User opens TradeMeter and clicks **Sign in with Google**
2. Frontend redirects to `GET /auth/google`
3. Backend redirects to Google consent screen with `client_id`, `redirect_uri`, `scope=openid email profile`
4. User consents → Google redirects to `GET /auth/google/callback?code=...`
5. Backend exchanges code for Google tokens, fetches user info
6. If new user: create user record + generate NT connection token
7. If existing user: update `last_login`, preserve existing NT token
8. Mint JWT → set as httpOnly cookie (`SameSite=Lax`, `Secure` in production)
9. Redirect user to `/connect` page

### JWT Structure

```json
{
  "sub": "uuid-user-id",
  "email": "user@example.com",
  "name": "Jane Trader",
  "nt_connected": false,
  "iat": 1719400000,
  "exp": 1719486400
}
```

JWT expires in 24 hours (`JWT_EXPIRE_HOURS`). The `nt_connected` claim reflects whether the user's NinjaTrader strategy is currently sending live data.

---

## Step 2: NT Connection Token

### Generation

```python
import secrets, string
alphabet = string.ascii_letters + string.digits
token = "TM-" + "".join(secrets.choice(alphabet) for _ in range(6))
# e.g. "TM-a3f9x2"
```

Generated once per user on first Google login. Stored as a **bcrypt hash** in the `users` table. The plaintext token is shown once on the Connect page — it is never persisted in plaintext.

### How NinjaTrader Uses It

The strategy reads the `ConnectionToken` parameter and includes it at the start of every TCP message:

```
TM-a3f9x2|1719400000|MES SEP24|5100.25|5101.50|5099.75|5100.75|342|1MIN\n
```

### How the Backend Validates It

On the **first message** from a new TCP connection:
1. Parse the token from the pipe-delimited message
2. bcrypt verify against all `nt_token_hash` values (small table — O(users) cost, acceptable)
3. If matched: cache `tcp_connection_id → user_id` in Redis (TTL 24 hours), update `nt_connected = TRUE` and `nt_last_seen` in TimescaleDB
4. If not matched: close TCP connection immediately

All subsequent messages on the same TCP connection use the cached `user_id` without re-querying the database.

**The token is permanent** — users only set it up once. If they rotate it (via Settings → Rotate Token), the old token is immediately invalidated and any active TCP connection using the old token is dropped.

---

## Multi-User

Each user has a completely independent token. When two users (you + brother) are both connected:
- Two separate TCP connections are open to the backend
- Each is mapped to a different `user_id`
- All tick writes, prediction writes, and model updates are scoped to their respective `user_id`
- Neither user can see the other's data through any API endpoint

---

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/google` | None | Redirect to Google consent screen |
| `GET` | `/auth/google/callback` | None | Handle OAuth callback, create user, set JWT cookie |
| `POST` | `/auth/logout` | JWT | Clear session cookie |
| `GET` | `/auth/me` | JWT | Return current user info from JWT |
| `GET` | `/auth/nt-token` | JWT | Return the user's NT connection token (plaintext, re-shown here only) |
| `GET` | `/auth/nt-status` | JWT | Return whether NT is currently connected (`{ "connected": true/false, "last_seen": "..." }`) |
| `POST` | `/auth/rotate-token` | JWT | Generate new NT token, invalidate old one, drop active TCP connection |

---

## Security Notes

- JWT cookie is `HttpOnly` and `SameSite=Lax` — safe from XSS and most CSRF scenarios
- NT connection tokens are stored bcrypt-hashed — plaintext is never persisted after display
- All traffic must be behind HTTPS in production (Nginx terminates TLS)
- Google OAuth `redirect_uri` must exactly match the URI allowlisted in Google Cloud Console per environment (localhost for dev, production domain for prod)
- TCP connections that fail token validation receive no error response — the connection is simply closed
- Token rotation immediately invalidates all Redis cached mappings for the old token
