# EAGLETRADE admin subscriber management

## What it does
- Adds a paid-subscriber page at `/admin/subscribers`.
- Lists paid accounts that have a PayPal subscription record, with username, display name, client ID, plan, PayPal status, app-access toggle, and last-updated time.
- Lets the administrator disable or re-enable EAGLETRADE app access for a paid account.
- Keeps administrator access state separate from PayPal subscription status, so a later PayPal webhook does not re-enable an account that an administrator disabled.
- Does not display password hashes, authentication tokens, or broker credentials.
- Does not cancel/refund a PayPal subscription. Perform billing changes through PayPal separately.

## Setup
1. Set `EAGLETRADE_ADMIN_KEY` in the Render backend environment to a long random secret. Do not commit the value to GitHub or share it.
2. Deploy this branch through a reviewed pull request.
3. Open `https://YOUR-RENDER-SERVICE.onrender.com/admin/subscribers` and enter the same admin key. The existing demo manager remains at `/admin/demo-accounts`.

## API
All endpoints require the `X-Admin-Key` header and fail closed if `EAGLETRADE_ADMIN_KEY` is unset:
- `GET /api/admin/subscribers`
- `PATCH /api/admin/subscribers/{username}?enabled=false`
- `PATCH /api/admin/subscribers/{username}?enabled=true`

## Validation required before production
Automated tests and live Render/Neon tests have not yet been run. Test with staging accounts first:
1. Missing/wrong admin key is rejected.
2. A verified paid subscriber appears in the list; demo accounts and pending signups do not.
3. Disabling a subscriber blocks subsequent authenticated requests; re-enabling restores access only if the PayPal subscription is still active.
4. A PayPal webhook status update does not override the administrator's access toggle.
5. Existing paid users remain enabled by default after the database column migration.
