"""
Insta Trade - Fast, Clean Trading Terminal Backend
Features:
1. Multi-User Virtual Trading (Paper Trading) with Real Live Market Prices (Zero broker needed!)
2. 100% Data Isolation per User (SQLite Persistent Storage in data/trading_terminal.db)
3. Zero API Key Exposure - Pure secure demo trading terminal for multiple users
"""

import os
from pathlib import Path
from typing import List, Optional, Union, Dict, Any
import secrets
import re
from fastapi import FastAPI, HTTPException, Query, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import logging

from backend.paypal import paypal_client, PayPalConfigurationError, PayPalAPIError
from backend.security import hash_password
from backend import subscription_store

from backend.storage import db
from backend.virtual_engine import VirtualTradingEngine
from backend.fyers_client import FyersClient

logger = logging.getLogger(__name__)
app = FastAPI(title="EAGLETRADE", description="Virtual trading terminal with mandatory PayPal subscription")


@app.on_event("startup")
def startup_subscription_tables():
    try:
        subscription_store.init_subscription_tables()
    except Exception as exc:
        logger.error("Subscription tables could not be initialized: %s", exc)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

virtual_engine = VirtualTradingEngine(initial_capital=1000000.0)
fyers_client = FyersClient()
virtual_engine.fyers_client = fyers_client


# ------------------ AUTH MODELS ------------------
class LoginPayload(BaseModel):
    username: str
    password: str


class RegisterPayload(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""
    client_id: Optional[str] = ""


class DemoAccountPayload(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""


class UpdateCredentialsPayload(BaseModel):
    password: Optional[str] = ""
    display_name: Optional[str] = ""
    client_id: Optional[str] = ""


class RestorePayload(BaseModel):
    username: str
    token: str
    display_name: Optional[str] = ""
    client_id: Optional[str] = ""


class OrderPayload(BaseModel):
    symbol: str
    qty: int
    side: int  # 1 for BUY, -1 for SELL
    order_type: Union[int, str] = 2  # 1=Limit, 2=Market, 3=SL-L, 4=SL-M
    product_type: str = "INTRADAY"  # "CNC", "INTRADAY", "MARGIN"
    limit_price: float = 0.0
    stop_price: float = 0.0
    expiry: Optional[str] = None


class SyncStatePayload(BaseModel):
    positions: Optional[List[Dict[str, Any]]] = None
    orders: Optional[List[Dict[str, Any]]] = None


# ------------------ USER AUTH DEPENDENCY ------------------
def get_current_username(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name"),
) -> Optional[str]:
    # Never trust X-User-Name by itself. Identity must be proven by a server-issued token.
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif x_auth_token:
        token = x_auth_token.strip()
    if not token:
        return None
    try:
        user = db.get_user_by_token(token)
        if not user:
            return None
        # Unpaid, suspended, cancelled, or expired accounts are not treated as authenticated.
        if not subscription_store.is_subscription_active(user["username"]):
            return None
        return user["username"]
    except Exception as exc:
        logger.warning("Authentication lookup failed: %s", exc)
        return None


def require_admin_key(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> None:
    configured_key = os.getenv("EAGLETRADE_ADMIN_KEY", "")
    if not configured_key:
        raise HTTPException(status_code=503, detail="Admin demo management is not configured.")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, configured_key):
        raise HTTPException(status_code=401, detail="Invalid admin key.")


def require_authenticated_user(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name"),
) -> str:
    username = get_current_username(
        authorization=authorization,
        x_auth_token=x_auth_token,
        x_user_name=x_user_name,
    )
    if username:
        return username
    raise HTTPException(
        status_code=401,
        detail="Sign in with an account that has an active PayPal subscription.",
    )


# ------------------ ADMIN-MANAGED DEMO ACCOUNTS ------------------
@app.get("/api/admin/demo-accounts")
def admin_list_demo_accounts(_: None = Depends(require_admin_key)):
    return {"s": "ok", "accounts": subscription_store.list_demo_accounts()}

@app.get("/api/admin/subscribers")
def admin_list_paid_subscribers(_: None = Depends(require_admin_key)):
    return {"s": "ok", "accounts": subscription_store.list_paid_subscribers()}


@app.patch("/api/admin/subscribers/{username}")
def admin_set_paid_subscriber_access(
    username: str,
    enabled: bool = Query(...),
    _: None = Depends(require_admin_key),
):
    changed = subscription_store.set_paid_subscriber_access(username, enabled)
    if not changed:
        raise HTTPException(status_code=404, detail="Paid subscriber not found.")
    return {"s": "ok", "username": username.strip().lower(), "enabled": enabled}


@app.post("/api/admin/demo-accounts")
def admin_create_demo_account(payload: DemoAccountPayload, _: None = Depends(require_admin_key)):
    username = (payload.username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,50}", username):
        raise HTTPException(status_code=400, detail="Username must be 3–50 characters using letters, numbers, dots, underscores, or hyphens.")
    if len(payload.password) < 8 or len(payload.password) > 128:
        raise HTTPException(status_code=400, detail="Demo password must be between 8 and 128 characters.")
    result = subscription_store.create_demo_account(
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or username,
    )
    if result.get("s") != "ok":
        raise HTTPException(status_code=409, detail=result.get("message", "Could not create demo account."))
    return {"s": "ok", "username": username, "message": "Demo account created. The user can sign in with the normal login form."}


@app.patch("/api/admin/demo-accounts/{username}")
def admin_set_demo_account_status(username: str, enabled: bool = Query(...), _: None = Depends(require_admin_key)):
    changed = subscription_store.set_demo_account_enabled(username, enabled)
    if not changed:
        raise HTTPException(status_code=404, detail="Demo account not found.")
    return {"s": "ok", "username": username.strip().lower(), "enabled": enabled}


# ------------------ STATUS & SYSTEM ------------------
@app.get("/api/status")
@app.get("/api/health")
@app.get("/health")
def get_status():
    # Never expose any broker API keys or secrets
    return {
        "status": "online",
        "trading_mode": "virtual",
        "market": "NSE / BSE Live Feeds",
        "storage": "Local SQLite Database (data/trading_terminal.db)",
    }


# ------------------ PAYPAL SUBSCRIPTIONS ------------------
class PendingSignupPayload(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""
    client_id: Optional[str] = ""


class VerifySubscriptionPayload(BaseModel):
    signup_id: str
    subscription_id: str


@app.get("/api/paypal/config")
def get_paypal_config():
    return paypal_client.public_config()


@app.post("/api/paypal/verify")
def verify_paypal_subscription(payload: VerifySubscriptionPayload):
    if not paypal_client.is_configured:
        raise HTTPException(status_code=503, detail="PayPal is not configured on the server.")
    pending = subscription_store.get_pending_signup(payload.signup_id)
    if not pending:
        raise HTTPException(status_code=400, detail="Signup session not found. Please register again.")
    try:
        sub = paypal_client.get_subscription(payload.subscription_id)
    except PayPalConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except PayPalAPIError as exc:
        logger.warning("PayPal verification failed: %s", exc)
        raise HTTPException(status_code=502, detail="PayPal could not verify this subscription. Please retry.")
    if sub.get("id") != payload.subscription_id:
        raise HTTPException(status_code=400, detail="PayPal subscription ID mismatch.")
    if sub.get("plan_id") != paypal_client.plan_id:
        raise HTTPException(status_code=400, detail="Subscription plan does not match EAGLETRADE's required plan.")
    if str(sub.get("status", "")).upper() != "ACTIVE":
        raise HTTPException(status_code=402, detail="Your PayPal subscription is not active yet.")
    custom_id = sub.get("custom_id")
    if custom_id != payload.signup_id:
        raise HTTPException(status_code=400, detail="This PayPal subscription belongs to a different signup session.")
    try:
        result = subscription_store.activate_pending_signup(
            signup_id=payload.signup_id,
            subscription_id=payload.subscription_id,
            plan_id=paypal_client.plan_id,
        )
    except Exception as exc:
        logger.exception("Could not activate paid account")
        raise HTTPException(status_code=500, detail="Subscription was verified but account activation failed. Contact support.")
    if result.get("s") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message", "Could not activate account."))
    return {"s": "ok", "message": result["message"], "data": {"username": result["username"]}}


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    try:
        valid = paypal_client.verify_webhook_signature(dict(request.headers), event)
    except (PayPalConfigurationError, PayPalAPIError) as exc:
        logger.warning("PayPal webhook verification failed: %s", exc)
        raise HTTPException(status_code=503, detail="Webhook signature verification is unavailable.")
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid PayPal webhook signature.")
    resource = event.get("resource") or {}
    subscription_id = resource.get("id")
    if subscription_id:
        # Query PayPal's current state instead of trusting event order; webhooks can be retried or arrive late.
        try:
            current = paypal_client.get_subscription(subscription_id)
        except PayPalAPIError as exc:
            logger.warning("Could not refresh subscription status from PayPal: %s", exc)
            raise HTTPException(status_code=503, detail="Unable to refresh subscription status.")
        if current.get("plan_id") == paypal_client.plan_id:
            actual_status = str(current.get("status", "")).upper()
            status_map = {
                "ACTIVE": "active",
                "SUSPENDED": "suspended",
                "CANCELLED": "cancelled",
                "EXPIRED": "expired",
            }
            normalized = status_map.get(actual_status, "inactive")
            subscription_store.set_subscription_status(subscription_id, normalized)
    return {"status": "received"}


# ------------------ USER AUTH ENDPOINTS ------------------
@app.post("/api/auth/register")
def register_account(payload: RegisterPayload):
    if not paypal_client.is_configured:
        raise HTTPException(status_code=503, detail="PayPal is not configured. Please contact the site administrator.")
    username = payload.username.strip().lower()
    if len(username) < 3 or len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be between 3 and 50 characters.")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    result = subscription_store.create_pending_signup(
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or "",
        client_id=payload.client_id or "",
    )
    if result.get("s") != "ok":
        raise HTTPException(status_code=409, detail=result.get("message", "Unable to start registration."))
    return result


@app.post("/api/auth/login")
def login_account(payload: LoginPayload):
    result = db.authenticate_user(username=payload.username, password=payload.password)
    if result.get("s") != "ok":
        raise HTTPException(status_code=401, detail=result.get("message", "Invalid username or password."))
    username = (result.get("user") or {}).get("username", payload.username)
    try:
        active = subscription_store.is_subscription_active(username)
    except Exception:
        logger.exception("Subscription status lookup failed during login")
        raise HTTPException(status_code=503, detail="Unable to check subscription status. Please retry.")
    if not active:
        raise HTTPException(status_code=402, detail="An active PayPal subscription is required before you can sign in.")
    user = result.get("user") or {}
    return {
        "s": "ok",
        "message": "Login successful",
        "data": {
            "token": result.get("token"),
            "username": user.get("username", username),
            "display_name": user.get("display_name") or username,
            "client_id": user.get("client_id") or "",
        },
    }


@app.post("/api/auth/restore")
def restore_account(payload: RestorePayload):
    # Restore validates an existing server-issued token; it never replaces tokens or creates users.
    user = db.get_user_by_token(payload.token)
    if not user or user.get("username", "").lower() != payload.username.strip().lower():
        raise HTTPException(status_code=401, detail="Session is invalid. Please sign in again.")
    if not subscription_store.is_subscription_active(user["username"]):
        raise HTTPException(status_code=402, detail="An active PayPal subscription is required.")
    funds = virtual_engine.get_funds_for_user(user["username"])
    return {
        "s": "ok",
        "user": {
            "username": user["username"],
            "display_name": user.get("display_name"),
            "client_id": user.get("client_id"),
        },
        "token": payload.token,
        "funds": funds,
    }


@app.get("/api/auth/me")
def get_current_user_profile(username: str = Depends(require_authenticated_user)):
    user = db.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    funds = virtual_engine.get_funds_for_user(username)
    return {
        "s": "ok",
        "user": user,
        "funds": funds,
        "subscription": subscription_store.get_subscription(username),
    }


@app.post("/api/auth/update")
def update_credentials(payload: UpdateCredentialsPayload, username: str = Depends(require_authenticated_user)):
    user = db.update_user_credentials(
        username=username,
        password=hash_password(payload.password) if payload.password else "",
        display_name=payload.display_name,
        client_id=payload.client_id,
    )
    return {"s": "ok", "message": "Account credentials updated successfully!", "user": user}


@app.get("/api/profile")
def get_profile(username: Optional[str] = Depends(get_current_username)):
    if not username:
        return {"s": "ok", "authenticated": False, "data": None}
    user = db.get_user(username) or {}
    return {
        "s": "ok",
        "authenticated": True,
        "data": {
            "username": user.get("username", username),
            "display_name": user.get("display_name", username),
            "client_id": user.get("client_id", "XH01499"),
            "mode": "Virtual Demo Paper Trading (Real Live NSE Data)",
        },
    }


@app.post("/api/profile")
def save_profile(payload: UpdateCredentialsPayload, username: str = Depends(require_authenticated_user)):
    user = db.update_user_credentials(
        username=username,
        password=hash_password(payload.password) if payload.password else "",
        display_name=payload.display_name,
        client_id=payload.client_id,
    )
    return {"s": "ok", "message": f"Credentials saved for '{username}'!", "data": user}


# ------------------ MARKET DATA ENDPOINTS (STREAMING) ------------------
@app.get("/api/optionchain")
def get_option_chain(
    underlying: str = Query("NIFTY"),
    expiry: Optional[str] = Query(None),
    strikecount: int = Query(15),
):
    return virtual_engine.get_option_chain(underlying, expiry=expiry, strike_count=strikecount)


# ------------------ FYERS BROKER ENDPOINTS ------------------
class FyersTokenPayload(BaseModel):
    access_token: Optional[str] = ""
    auth_code: Optional[str] = ""
    app_id: Optional[str] = ""
    secret_key: Optional[str] = ""
    client_id: Optional[str] = ""


@app.get("/api/fyers/status")
def get_fyers_status():
    is_cfg = fyers_client.is_configured
    has_token = bool(fyers_client.access_token)
    app_id = fyers_client.app_id
    client_id = getattr(fyers_client, "client_id", os.getenv("FYERS_CLIENT_ID", "XH01499"))
    return {
        "configured": is_cfg,
        "has_token": has_token,
        "app_id": app_id,
        "client_id": client_id,
        "mode": "FYERS_BROKER_LIVE" if is_cfg else "NSE_EXCHANGE_LIVE",
        "message": "Fyers API v3 Connected and Live" if is_cfg else "Using Direct Real-Time NSE Market Feed (Zero Token Required)",
    }


@app.get("/api/fyers/auth-url")
def get_fyers_auth_url(redirect_uri: str = Query("https://127.0.0.1:5000/fyers/callback")):
    return {"auth_url": fyers_client.generate_auth_url(redirect_uri)}


@app.post("/api/fyers/token")
def set_fyers_token(payload: FyersTokenPayload, username: str = Depends(require_authenticated_user)):
    if subscription_store.is_demo_account(username):
        raise HTTPException(status_code=403, detail="Demo accounts cannot connect broker credentials. Demo trading is virtual only.")
    app_id = payload.app_id.strip() if payload.app_id else fyers_client.app_id
    secret_key = payload.secret_key.strip() if payload.secret_key else fyers_client.secret_key
    client_id = payload.client_id.strip() if payload.client_id else getattr(fyers_client, "client_id", "XH01499")

    if payload.auth_code:
        res = fyers_client.exchange_code_for_token(payload.auth_code.strip())
        return res

    if payload.access_token:
        fyers_client.update_credentials(app_id, secret_key, payload.access_token.strip(), client_id=client_id)
        return {
            "s": "ok",
            "message": "Fyers access token updated and active!",
            "configured": fyers_client.is_configured,
        }

    return {"s": "error", "message": "Provide either access_token or auth_code"}


@app.get("/api/search")
def search_symbols(q: str = Query(..., min_length=1, description="Search query string")):
    results = virtual_engine.search_symbols(q)
    return {"s": "ok", "results": results}


@app.get("/api/quotes")
def get_quotes(symbols: str = Query(..., description="Comma-separated symbols")):
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    quotes = virtual_engine.get_quotes(sym_list)
    return {"s": "ok", "mode": "virtual", "data": quotes}


@app.get("/api/history")
def get_history(
    symbol: str = Query("NSE:NIFTY50-INDEX"),
    resolution: str = Query("5"),
    days: int = Query(3),
):
    candles = virtual_engine.get_history(symbol=symbol, resolution=resolution)
    return {"s": "ok", "mode": "virtual", "candles": candles}


# ------------------ USER-ISOLATED TRADING ENDPOINTS ------------------
@app.get("/api/funds")
def get_funds(username: Optional[str] = Depends(get_current_username)):
    if not username:
        return {
            "s": "ok",
            "authenticated": False,
            "username": None,
            "data": {
                "available_cash": 1000000.0,
                "used_margin": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            },
        }
    return {
        "s": "ok",
        "authenticated": True,
        "username": username,
        "data": virtual_engine.get_funds_for_user(username),
    }


@app.post("/api/virtual/reset")
def reset_virtual_funds(capital: float = Query(1000000.0), username: str = Depends(require_authenticated_user)):
    return virtual_engine.reset_account_for_user(username=username, capital=capital)


@app.get("/api/positions")
def get_positions(username: Optional[str] = Depends(get_current_username)):
    if not username:
        return {
            "s": "ok",
            "authenticated": False,
            "username": None,
            "positions": [],
        }
    return {
        "s": "ok",
        "authenticated": True,
        "username": username,
        "positions": virtual_engine.get_positions_for_user(username),
    }


@app.delete("/api/positions")
def exit_positions(symbol: Optional[str] = Query(None), username: str = Depends(require_authenticated_user)):
    return virtual_engine.exit_position_for_user(username=username, symbol=symbol)


@app.post("/api/positions/sync")
def sync_client_positions(payload: SyncStatePayload, username: str = Depends(require_authenticated_user)):
    db.sync_user_state(username=username, positions=payload.positions, orders=payload.orders)
    return {
        "s": "ok",
        "message": "User state synced successfully",
        "positions": virtual_engine.get_positions_for_user(username),
        "orders": virtual_engine.get_orders_for_user(username),
    }


@app.get("/api/orders")
def get_orders(username: Optional[str] = Depends(get_current_username)):
    if not username:
        return {
            "s": "ok",
            "authenticated": False,
            "username": None,
            "orders": [],
        }
    return {
        "s": "ok",
        "authenticated": True,
        "username": username,
        "orders": virtual_engine.get_orders_for_user(username),
    }


@app.post("/api/orders")
def place_order(order: OrderPayload, username: str = Depends(require_authenticated_user)):
    try:
        ot = order.order_type
        if isinstance(ot, str):
            ot = 1 if "LIMIT" in ot.upper() else 2
        else:
            try:
                ot = int(ot)
            except Exception:
                ot = 2

        return virtual_engine.place_order_for_user(
            username=username,
            symbol=order.symbol,
            qty=order.qty,
            side=order.side,
            order_type=ot,
            product=order.product_type,
            limit_price=order.limit_price,
            expiry=order.expiry,
        )
    except Exception as e:
        logger.error(f"Order placement error for user {username}: {e}", exc_info=True)
        return {"s": "error", "message": f"Order processing failed: {str(e)}"}


@app.get("/api/holdings")
def get_holdings(username: Optional[str] = Depends(get_current_username)):
    if not username:
        return {
            "s": "ok",
            "authenticated": False,
            "username": None,
            "holdings": [],
        }
    return {
        "s": "ok",
        "authenticated": True,
        "username": username,
        "holdings": virtual_engine.get_holdings_for_user(username),
    }


@app.get("/api/account/pnl-history")
def get_account_pnl_history(
    range: str = "1y",
    username: str = Depends(require_authenticated_user)
):
    clean_user = username.strip().lower()
    days_map = {"30d": 30, "3m": 90, "6m": 180, "1y": 365}
    days_limit = days_map.get(range.lower(), 365)
    history_data = db.get_daily_pnl_history(username=clean_user, days_limit=days_limit)
    return {
        "s": "ok",
        "authenticated": bool(username),
        "username": clean_user,
        "range": range,
        "data": history_data
    }


# ------------------ FRONTEND MOUNT ------------------
if FRONTEND_DIR.exists():
    @app.get("/admin/demo-accounts", include_in_schema=False)
    def serve_admin_demo_page():
        admin_page = FRONTEND_DIR / "admin-demo.html"
        if not admin_page.exists():
            raise HTTPException(status_code=404, detail="Admin page not found.")
        return FileResponse(str(admin_page))

    @app.get("/admin/subscribers", include_in_schema=False)
    def serve_admin_subscribers_page():
        admin_page = FRONTEND_DIR / "admin-subscribers.html"
        if not admin_page.exists():
            raise HTTPException(status_code=404, detail="Admin subscriber page not found.")
        return FileResponse(str(admin_page))

    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_index():
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Insta Trade API is running. frontend/index.html not found."}

    @app.get("/manifest.json")
    def serve_manifest():
        m_file = FRONTEND_DIR / "manifest.json"
        if m_file.exists():
            return FileResponse(str(m_file), media_type="application/manifest+json")
        raise HTTPException(status_code=404, detail="manifest.json not found")

    @app.get("/sw.js")
    def serve_sw():
        sw_file = FRONTEND_DIR / "sw.js"
        if sw_file.exists():
            return FileResponse(str(sw_file), media_type="application/javascript")
        raise HTTPException(status_code=404, detail="sw.js not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("backend.server:app", host=host, port=port)
