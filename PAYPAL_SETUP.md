# PayPal subscription setup for EAGLETRADE

The registration flow now creates a pending signup. The account is created only after the backend verifies the subscription with PayPal and confirms that the subscription is ACTIVE, uses the configured plan, and contains the exact signup ID as its `custom_id`.

## Configure credentials

1. Copy `.env.example` to `.env` in the deployment environment.
2. Set `DATABASE_URL` to the PostgreSQL database used by the application.
3. Set `PAYPAL_CLIENT_ID` to the same PayPal app client ID used by the PayPal SDK in `frontend/index.html`.
4. Set `PAYPAL_CLIENT_SECRET` to the matching secret. Do not put this secret in frontend code or commit it to GitHub.
5. Set `PAYPAL_PLAN_ID` to the plan you intend to sell. The current frontend plan ID is `P-75H6365063563890NNLOIKLI`.
6. Make sure the SDK client ID, plan, and API base are all from the same environment. Sandbox uses `https://api-m.sandbox.paypal.com`; live uses `https://api-m.paypal.com`.
7. Restart/redeploy the backend after changing environment variables.

## Webhooks

Create a webhook in the matching PayPal app and configure the URL as:

`https://YOUR-DOMAIN/api/paypal/webhook`

Subscribe to these event types:
- `BILLING.SUBSCRIPTION.ACTIVATED`
- `BILLING.SUBSCRIPTION.CANCELLED`
- `BILLING.SUBSCRIPTION.SUSPENDED`
- `BILLING.SUBSCRIPTION.EXPIRED`

Copy the webhook ID into `PAYPAL_WEBHOOK_ID`. The endpoint verifies PayPal's webhook signature before applying status updates. Use HTTPS in production.

## Flow

1. User enters registration details and submits the form.
2. Backend stores a short-lived pending signup and returns a random signup ID. It does not create an active user yet.
3. PayPal subscription is created with that signup ID as `custom_id`.
4. After approval, the browser submits the PayPal subscription ID to the backend.
5. Backend retrieves the subscription directly from PayPal, checks ID, plan, status and signup association, and only then creates the user and active subscription record.
6. Login and user-isolated APIs require a valid server-issued token and an active subscription. A username header alone is not authentication.

## Important before production

- Configure and test the full flow in PayPal sandbox first.
- Test cancellation, suspension, failed renewal and webhook delivery.
- Existing users do not automatically have a subscription record and will be denied login until their subscription status is deliberately migrated/verified.
- This repository is a virtual/paper trading terminal. Do not treat the payment gate as broker/exchange order execution or financial compliance approval.
