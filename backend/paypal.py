"""Server-side PayPal Subscriptions API client.

Secrets must be configured in environment variables; never put the secret in the browser.
"""
import os
from typing import Any, Dict

import httpx


class PayPalConfigurationError(RuntimeError):
    pass


class PayPalAPIError(RuntimeError):
    pass


class PayPalClient:
    def __init__(self) -> None:
        self.client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
        self.plan_id = os.getenv("PAYPAL_PLAN_ID", "").strip()
        self.webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
        self.api_base = os.getenv(
            "PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com"
        ).strip().rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.plan_id)

    def public_config(self) -> Dict[str, Any]:
        return {
            "enabled": self.is_configured,
            "client_id": self.client_id if self.is_configured else "",
            "plan_id": self.plan_id if self.is_configured else "",
        }

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise PayPalConfigurationError(
                "PayPal is not configured. Set PAYPAL_CLIENT_ID, "
                "PAYPAL_CLIENT_SECRET, and PAYPAL_PLAN_ID."
            )

    def _access_token(self) -> str:
        self._require_configured()
        try:
            response = httpx.post(
                f"{self.api_base}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
                timeout=15.0,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not token:
                raise PayPalAPIError("PayPal did not return an access token.")
            return token
        except PayPalAPIError:
            raise
        except httpx.HTTPError as exc:
            raise PayPalAPIError("Unable to authenticate with PayPal.") from exc

    def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        if not subscription_id or len(subscription_id) > 128:
            raise PayPalAPIError("Invalid PayPal subscription ID.")
        token = self._access_token()
        try:
            response = httpx.get(
                f"{self.api_base}/v1/billing/subscriptions/{subscription_id}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise PayPalAPIError("Unexpected PayPal subscription response.")
            return data
        except PayPalAPIError:
            raise
        except httpx.HTTPError as exc:
            raise PayPalAPIError("Unable to verify the PayPal subscription.") from exc

    def verify_webhook_signature(self, headers: Dict[str, str], event: Dict[str, Any]) -> bool:
        self._require_configured()
        if not self.webhook_id:
            return False
        lowered = {str(k).lower(): v for k, v in headers.items()}
        required = {
            "auth_algo": lowered.get("paypal-auth-algo"),
            "cert_url": lowered.get("paypal-cert-url"),
            "transmission_id": lowered.get("paypal-transmission-id"),
            "transmission_sig": lowered.get("paypal-transmission-sig"),
            "transmission_time": lowered.get("paypal-transmission-time"),
        }
        if not all(required.values()):
            return False
        token = self._access_token()
        payload = {
            **required,
            "webhook_id": self.webhook_id,
            "webhook_event": event,
        }
        try:
            response = httpx.post(
                f"{self.api_base}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json().get("verification_status") == "SUCCESS"
        except httpx.HTTPError as exc:
            raise PayPalAPIError("Unable to verify the PayPal webhook signature.") from exc


paypal_client = PayPalClient()
