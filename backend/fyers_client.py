"""
Fyers API v3 Client for Insta Trade
Supports Profile, Funds, Quotes, Orders, Positions, Holdings, and Historical Chart Data.
Includes seamless fallback mock data when API keys are not yet configured.
"""

import os
import json
import logging
import datetime
from typing import Dict, Any, List, Optional
import httpx
from dotenv import load_dotenv, set_key

logger = logging.getLogger("fyers_client")
logging.basicConfig(level=logging.INFO)

FYERS_BASE_URL = "https://api-t1.fyers.in"
DATA_BASE_URL = "https://api-t1.fyers.in/data"


class FyersClient:
    def __init__(self, env_path: str = ".env"):
        self.env_path = env_path
        load_dotenv(self.env_path, override=True)
        self.app_id = os.getenv("FYERS_APP_ID", "").strip()
        self.secret_key = os.getenv("FYERS_SECRET_KEY", "").strip()
        self.access_token = os.getenv("FYERS_ACCESS_TOKEN", "").strip()

        # In-memory mock state for preview / paper testing when no token
        self._mock_funds = {
            "available_cash": 250000.00,
            "used_margin": 45200.00,
            "realized_pnl": 3450.00,
            "unrealized_pnl": 1280.00,
            "total_collateral": 0.00,
        }
        self._mock_orders = [
            {
                "id": "ORD-101",
                "symbol": "NSE:NIFTY50-INDEX",
                "type": "BUY",
                "order_type": "MARKET",
                "product": "INTRADAY",
                "qty": 50,
                "price": 25420.50,
                "status": "FILLED",
                "time": "09:25:14",
            },
            {
                "id": "ORD-102",
                "symbol": "NSE:RELIANCE-EQ",
                "type": "BUY",
                "order_type": "LIMIT",
                "product": "CNC",
                "qty": 20,
                "price": 1280.00,
                "status": "OPEN",
                "time": "10:14:02",
            },
        ]
        self._mock_positions = [
            {
                "id": "POS-1",
                "symbol": "NSE:NIFTY24OCT25500CE",
                "side": "BUY",
                "product": "INTRADAY",
                "net_qty": 50,
                "buy_avg": 142.50,
                "sell_avg": 0.00,
                "ltp": 168.10,
                "pnl": 1280.00,
                "pnl_pct": 17.96,
            }
        ]

    def update_credentials(self, app_id: str, secret_key: str, access_token: str, client_id: str = ""):
        self.app_id = app_id.strip()
        self.secret_key = secret_key.strip()
        self.access_token = access_token.strip()
        if client_id:
            self.client_id = client_id.strip()

        os.environ["FYERS_APP_ID"] = self.app_id
        os.environ["FYERS_SECRET_KEY"] = self.secret_key
        os.environ["FYERS_ACCESS_TOKEN"] = self.access_token

        # Save to .env if file exists
        if os.path.exists(self.env_path):
            try:
                set_key(self.env_path, "FYERS_APP_ID", self.app_id)
                set_key(self.env_path, "FYERS_SECRET_KEY", self.secret_key)
                set_key(self.env_path, "FYERS_ACCESS_TOKEN", self.access_token)
                if getattr(self, "client_id", None):
                    set_key(self.env_path, "FYERS_CLIENT_ID", self.client_id)
            except Exception as e:
                logger.warning(f"Could not persist to .env: {e}")

    @property
    def is_configured(self) -> bool:
        return bool(self.app_id and self.access_token)

    def generate_auth_url(self, redirect_uri: str = "https://127.0.0.1:5000/fyers/callback") -> str:
        app_id = self.app_id
        return f"https://api-t1.fyers.in/api/v3/generate-authcode?client_id={app_id}&redirect_uri={redirect_uri}&response_type=code&state=insta_trade"

    def exchange_code_for_token(self, code_or_url: str) -> Dict[str, Any]:
        import hashlib
        import urllib.parse

        code = code_or_url.strip()
        if "code=" in code or "auth_code=" in code:
            if "?" in code:
                query = code.split("?", 1)[1]
            else:
                query = code
            params = urllib.parse.parse_qs(query)
            code = params.get("auth_code", params.get("code", [code]))[0]

        app_id = self.app_id
        secret = self.secret_key
        if not app_id or not secret:
            return {"s": "error", "message": "App ID and Secret Key are required."}

        app_id_hash = hashlib.sha256(f"{app_id}:{secret}".encode("utf-8")).hexdigest()
        payload = {
            "grant_type": "authorization_code",
            "appIdHash": app_id_hash,
            "code": code,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.post("https://api-t1.fyers.in/api/v3/validate-authcode", headers=headers, json=payload)
                data = res.json()
                if data.get("s") == "ok":
                    token = data.get("access_token")
                    if token:
                        self.update_credentials(app_id, secret, token)
                        return {"s": "ok", "message": "Successfully authenticated with Fyers!", "token": token}
                return {"s": "error", "message": data.get("message", "Token validation failed")}
        except Exception as e:
            return {"s": "error", "message": str(e)}

    def _get_headers(self) -> Dict[str, str]:
        # Fyers requires Authorization: {app_id}:{access_token}
        auth = f"{self.app_id}:{self.access_token}" if ":" not in self.access_token else self.access_token
        return {
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------ PROFILE ------------------
    def get_profile(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {
                "s": "ok",
                "status": "mock",
                "data": {
                    "name": "Trader (Demo Mode)",
                    "email": "demo@instatrade.local",
                    "fy_id": "DEMO-USER",
                    "mobile_number": "98XXXXXXXX",
                },
            }

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{FYERS_BASE_URL}/api/v3/profile", headers=self._get_headers())
                return res.json()
        except Exception as e:
            logger.error(f"Error fetching profile: {e}")
            return {"s": "error", "message": str(e)}

    # ------------------ FUNDS & MARGINS ------------------
    def get_funds(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"s": "ok", "status": "mock", "data": self._mock_funds}

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{FYERS_BASE_URL}/api/v3/funds", headers=self._get_headers())
                data = res.json()
                if data.get("s") == "ok" or data.get("code") == 200:
                    fund_limits = data.get("fund_limit", [])
                    avail = 0.0
                    used = 0.0
                    realized = 0.0
                    unrealized = 0.0
                    for item in fund_limits:
                        title = item.get("title", "").lower()
                        eq_amt = float(item.get("equityAmount", 0) or 0)
                        if "available" in title or "clear balance" in title:
                            avail += eq_amt
                        elif "utilised" in title or "margin used" in title or "exposure" in title:
                            used += eq_amt
                        elif "realized" in title:
                            realized += eq_amt
                        elif "unrealized" in title:
                            unrealized += eq_amt
                    return {
                        "s": "ok",
                        "status": "live",
                        "data": {
                            "available_cash": round(avail, 2),
                            "used_margin": round(used, 2),
                            "realized_pnl": round(realized, 2),
                            "unrealized_pnl": round(unrealized, 2),
                            "raw": fund_limits,
                        },
                    }
                return {"s": "error", "message": data.get("message", "Error fetching funds")}
        except Exception as e:
            logger.error(f"Error fetching funds: {e}")
            return {"s": "error", "message": str(e), "data": self._mock_funds}

    # ------------------ QUOTES ------------------
    def get_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        if not symbols:
            return {"s": "ok", "data": []}

        if not self.is_configured:
            # Generate simulated quotes
            mock_quotes = []
            default_prices = {
                "NSE:NIFTY50-INDEX": (25425.0, 0.45, 25310.0, 25480.0),
                "NSE:NIFTYBANK-INDEX": (53850.0, -0.22, 53600.0, 54100.0),
                "NSE:RELIANCE-EQ": (1285.50, 1.15, 1270.0, 1292.0),
                "NSE:HDFCBANK-EQ": (1640.20, -0.40, 1635.0, 1655.0),
                "NSE:INFY-EQ": (1895.00, 0.85, 1880.0, 1910.0),
                "NSE:TCS-EQ": (4150.00, 0.30, 4120.0, 4175.0),
                "NSE:TATAMOTORS-EQ": (975.40, 1.80, 955.0, 982.0),
            }
            for sym in symbols:
                base, chg_pct, low, high = default_prices.get(sym, (100.0, 0.5, 98.0, 102.0))
                # Add tiny random jitter
                ltp = round(base, 2)
                chg = round(ltp * (chg_pct / 100.0), 2)
                mock_quotes.append({
                    "symbol": sym,
                    "short_name": sym.split(":")[-1].replace("-EQ", "").replace("-INDEX", ""),
                    "ltp": ltp,
                    "change": chg,
                    "chg_percent": chg_pct,
                    "open": round(base - (chg * 0.5), 2),
                    "high": high,
                    "low": low,
                    "prev_close": round(base - chg, 2),
                    "volume": 1250000,
                })
            return {"s": "ok", "status": "mock", "data": mock_quotes}

        try:
            sym_str = ",".join(symbols)
            with httpx.Client(timeout=10.0) as client:
                res = client.get(
                    f"{DATA_BASE_URL}/quotes?symbols={sym_str}",
                    headers=self._get_headers(),
                )
                data = res.json()
                if data.get("s") == "ok":
                    formatted = []
                    for item in data.get("d", []):
                        v = item.get("v", {})
                        sym = item.get("n", "")
                        formatted.append({
                            "symbol": sym,
                            "short_name": sym.split(":")[-1].replace("-EQ", "").replace("-INDEX", ""),
                            "ltp": v.get("lp", 0.0),
                            "change": v.get("ch", 0.0),
                            "chg_percent": v.get("chp", 0.0),
                            "open": v.get("open_price", 0.0),
                            "high": v.get("high_price", 0.0),
                            "low": v.get("low_price", 0.0),
                            "prev_close": v.get("prev_close_price", 0.0),
                            "volume": v.get("volume", 0),
                        })
                    return {"s": "ok", "status": "live", "data": formatted}
                return {"s": "error", "message": data.get("message", "Quote fetch failed")}
        except Exception as e:
            logger.error(f"Error fetching quotes: {e}")
            return {"s": "error", "message": str(e)}

    # ------------------ FYERS OPTION CHAIN V3 ------------------
    def get_option_chain(self, symbol: str = "NSE:NIFTY50-INDEX", strikecount: int = 15) -> Dict[str, Any]:
        if not self.is_configured:
            return {"s": "error", "message": "Fyers not configured"}
        try:
            url = f"{DATA_BASE_URL}/options-chain-v3?symbol={symbol}&strikecount={strikecount}"
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url, headers=self._get_headers())
                return res.json()
        except Exception as e:
            logger.error(f"Error fetching Fyers option chain: {e}")
            return {"s": "error", "message": str(e)}

    # ------------------ HISTORICAL CANDLES ------------------
    def get_history(self, symbol: str, resolution: str = "5", days: int = 3) -> Dict[str, Any]:
        if not self.is_configured:
            # Generate simulated candles for chart
            now = datetime.datetime.now()
            candles = []
            base_price = 25400.0 if "NIFTY" in symbol else 1280.0
            price = base_price
            for i in range(120):
                t = now - datetime.timedelta(minutes=(120 - i) * 5)
                delta = ((i % 7) - 3) * (0.8 if "NIFTY" in symbol else 0.4)
                open_p = round(price, 2)
                close_p = round(price + delta, 2)
                high_p = round(max(open_p, close_p) + abs(delta) * 0.5 + 0.5, 2)
                low_p = round(min(open_p, close_p) - abs(delta) * 0.5 - 0.5, 2)
                price = close_p
                candles.append({
                    "time": int(t.timestamp()),
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "volume": 5000 + (i * 120),
                })
            return {"s": "ok", "status": "mock", "candles": candles}

        try:
            to_date = datetime.date.today().strftime("%Y-%m-%d")
            from_date = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")

            url = (
                f"{DATA_BASE_URL}/history?"
                f"symbol={symbol}&resolution={resolution}&date_format=1&"
                f"range_from={from_date}&range_to={to_date}&cont_flag=1"
            )
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, headers=self._get_headers())
                data = res.json()
                if data.get("s") == "ok":
                    raw_candles = data.get("candles", [])
                    candles = []
                    for c in raw_candles:
                        # [epoch_timestamp, open, high, low, close, volume]
                        candles.append({
                            "time": c[0],
                            "open": c[1],
                            "high": c[2],
                            "low": c[3],
                            "close": c[4],
                            "volume": c[5],
                        })
                    return {"s": "ok", "status": "live", "candles": candles}
                return {"s": "error", "message": data.get("message", "History fetch failed")}
        except Exception as e:
            logger.error(f"Error fetching history: {e}")
            return {"s": "error", "message": str(e)}

    # ------------------ ORDERS & POSITIONS ------------------
    def get_orders(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"s": "ok", "status": "mock", "orders": self._mock_orders}

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{FYERS_BASE_URL}/api/v3/orders", headers=self._get_headers())
                data = res.json()
                if data.get("s") == "ok":
                    return {"s": "ok", "status": "live", "orders": data.get("orderBook", [])}
                return {"s": "error", "message": data.get("message", "Failed to fetch orders")}
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return {"s": "error", "message": str(e), "orders": self._mock_orders}

    def get_positions(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"s": "ok", "status": "mock", "positions": self._mock_positions}

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{FYERS_BASE_URL}/api/v3/positions", headers=self._get_headers())
                data = res.json()
                if data.get("s") == "ok":
                    return {
                        "s": "ok",
                        "status": "live",
                        "positions": data.get("netPositions", []),
                        "overall": data.get("overall", {}),
                    }
                return {"s": "error", "message": data.get("message", "Failed to fetch positions")}
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {"s": "error", "message": str(e), "positions": self._mock_positions}

    def get_holdings(self) -> Dict[str, Any]:
        if not self.is_configured:
            mock_holdings = [
                {
                    "symbol": "NSE:TATASTEEL-EQ",
                    "quantity": 100,
                    "costPrice": 140.0,
                    "ltp": 154.20,
                    "pl": 1420.0,
                    "plPercent": 10.14,
                },
                {
                    "symbol": "NSE:INFY-EQ",
                    "quantity": 25,
                    "costPrice": 1820.0,
                    "ltp": 1895.0,
                    "pl": 1875.0,
                    "plPercent": 4.12,
                },
            ]
            return {"s": "ok", "status": "mock", "holdings": mock_holdings}

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{FYERS_BASE_URL}/api/v3/holdings", headers=self._get_headers())
                data = res.json()
                if data.get("s") == "ok":
                    return {"s": "ok", "status": "live", "holdings": data.get("holdings", [])}
                return {"s": "error", "message": data.get("message", "Failed to fetch holdings")}
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return {"s": "error", "message": str(e)}

    # ------------------ OPTION CHAIN ------------------
    def get_option_chain(
        self,
        symbol: str = "NSE:NIFTY50-INDEX",
        strikecount: int = 15,
        timestamp: str = "",
    ) -> Dict[str, Any]:
        if not self.is_configured:
            return {"s": "error", "message": "Fyers not configured"}

        try:
            params = {"symbol": symbol, "strikecount": strikecount}
            if timestamp:
                params["timestamp"] = timestamp
            with httpx.Client(timeout=10.0) as client:
                res = client.get(
                    f"{DATA_BASE_URL}/options-chain-v3",
                    headers=self._get_headers(),
                    params=params,
                )
                return res.json()
        except Exception as e:
            logger.error(f"Error fetching Fyers option chain: {e}")
            return {"s": "error", "message": str(e)}

    # ------------------ PLACE / MODIFY / CANCEL ------------------
    def place_order(
        self,
        symbol: str,
        qty: int,
        side: int,  # 1 = Buy, -1 = Sell
        order_type: int = 2,  # 1 = Limit, 2 = Market, 3 = Stop (SL-L), 4 = Stoplimit (SL-M)
        product_type: str = "INTRADAY",  # "CNC", "INTRADAY", "MARGIN"
        limit_price: float = 0.0,
        stop_price: float = 0.0,
    ) -> Dict[str, Any]:
        if not self.is_configured:
            # Paper trading fill
            order_id = f"SIM-{int(datetime.datetime.now().timestamp())}"
            new_ord = {
                "id": order_id,
                "symbol": symbol,
                "type": "BUY" if side == 1 else "SELL",
                "order_type": "MARKET" if order_type == 2 else "LIMIT",
                "product": product_type,
                "qty": qty,
                "price": limit_price if limit_price > 0 else 100.0,
                "status": "FILLED",
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
            }
            self._mock_orders.insert(0, new_ord)
            return {"s": "ok", "status": "mock", "message": "Simulated order placed successfully", "id": order_id}

        payload = {
            "symbol": symbol,
            "qty": qty,
            "type": order_type,
            "side": side,
            "productType": product_type,
            "limitPrice": limit_price,
            "stopPrice": stop_price,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
            "stopLoss": 0,
            "takeProfit": 0,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(
                    f"{FYERS_BASE_URL}/api/v3/orders/sync",
                    headers=self._get_headers(),
                    json=payload,
                )
                return res.json()
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"s": "error", "message": str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self.is_configured:
            for ord in self._mock_orders:
                if ord["id"] == order_id:
                    ord["status"] = "CANCELLED"
            return {"s": "ok", "status": "mock", "message": f"Order {order_id} cancelled"}

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.request(
                    "DELETE",
                    f"{FYERS_BASE_URL}/api/v3/orders/sync",
                    headers=self._get_headers(),
                    json={"id": order_id},
                )
                return res.json()
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return {"s": "error", "message": str(e)}

    def exit_position(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_configured:
            self._mock_positions = []
            return {"s": "ok", "status": "mock", "message": "Positions closed"}

        try:
            payload = {"id": symbol} if symbol else {}
            with httpx.Client(timeout=10.0) as client:
                res = client.request(
                    "DELETE",
                    f"{FYERS_BASE_URL}/api/v3/positions",
                    headers=self._get_headers(),
                    json=payload,
                )
                return res.json()
        except Exception as e:
            logger.error(f"Error exiting position: {e}")
            return {"s": "error", "message": str(e)}
