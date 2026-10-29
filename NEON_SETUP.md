# EAGLETRADE online storage with Neon

EAGLETRADE uses Neon PostgreSQL as the persistent online database. The frontend must call the FastAPI backend; never connect the browser directly to Neon or expose the database connection string.

## 1. Create a Neon database

1. Sign in at https://neon.tech and create a project.
2. Select the region closest to your application server.
3. In the Neon dashboard, select **Connect** and copy the PostgreSQL connection string. Prefer the pooled connection string for a serverless web deployment.
4. Add `sslmode=require` if it is not already present.
5. Set the value as `DATABASE_URL` in the backend host's environment variables. Do not commit the real URL to GitHub and do not put it in frontend JavaScript.

Example only (replace all placeholders):
`DATABASE_URL=postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require`

## 2. Deploy the backend

- Install dependencies from `requirements.txt`.
- Run the FastAPI application using your existing deployment command, for example `uvicorn backend.server:app --host 0.0.0.0 --port 8000`.
- On startup, `backend/storage.py` creates the required tables, including `user_trade_state` and `user_preferences`.
- Keep `DATABASE_URL` set in the deployment platform's environment settings. A local `.env` file is for local development only.

## 3. What is stored online

- User account records and session-token records in PostgreSQL.
- Virtual trading account funds, open positions, order history, and holdings in the per-user `user_trade_state` JSONB row.
- Daily P&L history in `daily_pnl`.
- Watchlist, theme, split-screen orientation, split ratio, and split widgets in `user_preferences`.

All trade-state and preference APIs are scoped to the authenticated username. Market quote/option-chain caches remain transient because they are live market data, not user-owned records. The browser may retain an authentication token for session restoration; this is separate from the persistent trading data.

## 4. Migration from browser storage

After deployment, sign in on the browser that contains the old data. The frontend attempts a one-time migration of legacy cached positions/orders only if the online trade state is empty. Old watchlist/theme/workspace preferences are migrated to Neon if the account has no saved cloud preferences. After successful preference migration, those old preference keys are removed from that browser.

The legacy browser cache is not a substitute for a backup. Verify the imported positions and orders before clearing browser data. If data is important, export or back it up before deployment.

## 5. Verification checklist

- Create a test account and add a virtual order.
- Open Neon SQL Editor and inspect that account's `user_trade_state` row.
- Change the watchlist or workspace layout and inspect `user_preferences`.
- Sign in from a second browser/device: the same account should receive the same saved data and preferences.
- Restart/redeploy the backend and confirm funds, positions and orders remain.
- Test database connection failure behavior before production use.

## Security

- Never expose `DATABASE_URL` in frontend code, public logs, screenshots, or GitHub commits.
- Use HTTPS for the web app.
- Keep each query filtered by authenticated username; do not trust a username supplied only by the browser.
- Enable Neon backups/restore features appropriate to your plan and test recovery procedures.
