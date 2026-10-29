# Admin-managed EAGLETRADE demo accounts

## What this adds
- Admin-key-protected API to create, list, enable, and disable demo accounts.
- Demo accounts are stored in Neon PostgreSQL (`users`, `user_subscriptions`, `demo_accounts`).
- Demo users sign in through the existing login form; no PayPal subscription is required for a demo account.
- Disabling a demo account blocks future authenticated requests through the subscription check.
- Demo users are blocked from submitting Fyers broker credentials. Trading endpoints in this app are virtual/paper-trading endpoints.

## Render configuration
1. Open the EAGLETRADE backend service in Render → Environment.
2. Add `EAGLETRADE_ADMIN_KEY` with a long random secret (at least 32 random bytes). Generate it locally with a trusted password manager or `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Save and redeploy. Never commit this value to GitHub or share it with demo users.
4. Open `https://YOUR-RENDER-SERVICE/admin/demo-accounts` and enter the key. Replace the URL with your actual Render hostname.
5. Create a username and temporary password (8+ characters), then share credentials privately. Ask users to change the password after first login.

## API
All routes require the `X-Admin-Key` header and return 503 if the Render environment variable is missing:
- `GET /api/admin/demo-accounts`
- `POST /api/admin/demo-accounts` with JSON `{"username":"demo_user01","password":"temporary-password","display_name":"Demo User"}`
- `PATCH /api/admin/demo-accounts/{username}?enabled=false` (or `true`)

## Important security and release notes
- Admin management is protected by a shared secret, not by an application administrator role. Keep the key private and rotate it immediately if exposed.
- The browser admin page keeps the key in page memory only, but do not use it on shared computers.
- Review and test in a staging deployment before merging. Verify that requests without a key and with an incorrect key fail, a demo user can log in, a disabled demo user is denied, demo users cannot set Fyers credentials, and two demo accounts cannot see each other's virtual data.
- Existing subscription checks are the source of authorization for normal login. Demo accounts have a separate `demo_accounts` row and an active `demo` subscription record. No existing user or table is deleted.
- Do not share a demo user's token or use live broker credentials in a demo account.