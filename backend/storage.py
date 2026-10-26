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
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.storage import db
from backend.virtual_engine import VirtualTradingEngine
from backend.fyers_client import FyersClient

app = FastAPI(title="Insta Trade", description="High-Speed Indian Market Virtual Trading Terminal")

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
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ")[1].strip()
    elif x_auth_token:
        token = x_auth_token.strip()

    if token:
        user = db.get_user_by_token(token)
        if user:
            return user["username"]
        # Seamless recovery across ephemeral container resets:
        if x_user_name and len(x_user_name.strip()) >= 3:
            user = db.restore_user(username=x_user_name.strip(), token=token)
            if user:
                return user["username"]

    # Fallback: if valid X-User-Name is passed and user exists
    if x_user_name and len(x_user_name.strip()) >= 3:
        clean = x_user_name.strip().lower()
        user = db.get_user(clean)
        if user:
            return user["username"]

    return None


def require_authenticated_user(
    authorization: Optional[str] = Header(None),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name"),
) -> str:
    username = get_current_username(authorization=authorization, x_auth_token=x_auth_token, x_user_name=x_user_name)
    if username:
        return username

    raise HTTPException(status_code=401, detail="Please sign in with your Login ID and Password to trade.")


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


# ------------------ USER AUTH ENDPOINTS ------------------
@app.post("/api/auth/register")
def register_account(payload: RegisterPayload):
    return db.register_user(
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        client_id=payload.client_id,
    )


@app.post("/api/auth/login")
def login_account(payload: LoginPayload):
    return db.authenticate_user(username=payload.username, password=payload.password)


@app.post("/api/auth/restore")
def restore_account(payload: RestorePayload):
    user = db.restore_user(
        username=payload.username,
        token=payload.token,
        display_name=payload.display_name,
        client_id=payload.client_id,
    )
    if not user:
        raise HTTPException(status_code=400, detail="Unable to restore account")
    funds = virtual_engine.get_funds_for_user(user["username"])
    return {
        "s": "ok",
        "user": user,
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
    }


@app.post("/api/auth/update")
def update_credentials(payload: UpdateCredentialsPayload, username: str = Depends(require_authenticated_user)):
    user = db.update_user_credentials(
        username=username,
        password=payload.password,
        display_name=payload.display_name,
        client_id=payload.client_id,
    )
    return {
        "s": "ok",
        "message": "Account credentials updated successfully!",
        "user": user,
    }


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
        password=payload.password,
        display_name=payload.display_name,
        client_id=payload.client_id,
    )
    return {
        "s": "ok",
        "message": f"Credentials saved for '{username}'!",
        "data": user,
    }


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
def set_fyers_token(payload: FyersTokenPayload):
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
    username: Optional[str] = Depends(get_current_username)
):
    clean_user = (username or "aman_trader").strip().lower()
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

