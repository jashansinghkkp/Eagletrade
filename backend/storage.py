"""
Insta Trade - Persistent Storage Manager
Supports:
1. Cloud PostgreSQL (Neon / Supabase / Render PostgreSQL via DATABASE_URL)
2. Persistent Disks (Render /var/data or custom DATA_DIR)
3. Local SQLite (data/trading_terminal.db) with seamless zero-lockout auto-creation on login
"""

import os
import sqlite3
import hashlib
import secrets
import datetime
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("storage")

BASE_DIR = Path(__file__).resolve().parent.parent

# Persistent disk detection:
DATA_DIR_ENV = os.environ.get("DATA_DIR")
if DATA_DIR_ENV and Path(DATA_DIR_ENV).exists():
    DATA_DIR = Path(DATA_DIR_ENV)
elif Path("/var/data").exists():
    DATA_DIR = Path("/var/data")
else:
    DATA_DIR = BASE_DIR / "data"

DB_PATH = DATA_DIR / "trading_terminal.db"


class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        raw_db_url = os.environ.get("DATABASE_URL", "").strip()
        if raw_db_url.startswith("postgres://"):
            raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
        self.database_url = raw_db_url
        self.is_postgres = bool(self.database_url)

        if not self.is_postgres:
            self._ensure_dir()
        else:
            logger.info("Connecting to Cloud PostgreSQL Database via DATABASE_URL")

        self.init_db()

    def _ensure_dir(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _get_connection(self):
        if self.is_postgres:
            import psycopg2
            return psycopg2.connect(self.database_url)
        else:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

    def _get_cursor(self, conn):
        if self.is_postgres:
            import psycopg2.extras
            return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return conn.cursor()

    def _execute(self, cursor, sql: str, params: tuple = ()):
        if self.is_postgres:
            sql = sql.replace("?", "%s")
        cursor.execute(sql, params)

    def init_db(self):
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            # 1. Users table
            self._execute(cursor, """
                CREATE TABLE IF NOT EXISTS users (
                    username VARCHAR(100) PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    client_id TEXT,
                    token TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. User Funds table
            self._execute(cursor, """
                CREATE TABLE IF NOT EXISTS user_funds (
                    username VARCHAR(100) PRIMARY KEY,
                    available_cash REAL DEFAULT 1000000.0,
                    used_margin REAL DEFAULT 0.0,
                    realized_pnl REAL DEFAULT 0.0
                )
            """)

            # 3. User Positions table
            self._execute(cursor, """
                CREATE TABLE IF NOT EXISTS user_positions (
                    id VARCHAR(200) PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    symbol VARCHAR(100) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    product VARCHAR(20) DEFAULT 'INTRADAY',
                    net_qty INTEGER NOT NULL,
                    buy_avg REAL DEFAULT 0.0,
                    sell_avg REAL DEFAULT 0.0,
                    margin_held REAL DEFAULT 0.0,
                    expiry VARCHAR(50) DEFAULT '',
                    created_date VARCHAR(50) DEFAULT ''
                )
            """)

            # 4. User Orders table
            self._execute(cursor, """
                CREATE TABLE IF NOT EXISTS user_orders (
                    id VARCHAR(100) PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    order_time VARCHAR(50) NOT NULL,
                    symbol VARCHAR(100) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    order_type VARCHAR(20) NOT NULL,
                    product VARCHAR(20) NOT NULL,
                    qty INTEGER NOT NULL,
                    price REAL NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    expiry VARCHAR(50) DEFAULT '',
                    order_date VARCHAR(50) DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 5. User Sessions table (multi-device, multi-tab persistent sessions)
            self._execute(cursor, """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token VARCHAR(200) PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. User Daily P&L History table (1-Year daily ledger)
            self._execute(cursor, """
                CREATE TABLE IF NOT EXISTS user_daily_pnl (
                    id VARCHAR(100) PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    pnl_date VARCHAR(50) NOT NULL,
                    realized_pnl REAL NOT NULL,
                    trades_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Safe column migrations for existing tables
            migrations = [
                ("user_orders", "order_date", "VARCHAR(50) DEFAULT ''"),
                ("user_orders", "expiry", "VARCHAR(50) DEFAULT ''"),
                ("user_positions", "expiry", "VARCHAR(50) DEFAULT ''"),
                ("user_positions", "created_date", "VARCHAR(50) DEFAULT ''"),
            ]
            for tbl, col, col_def in migrations:
                try:
                    self._execute(cursor, f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")
                    conn.commit()
                except Exception:
                    if self.is_postgres:
                        try:
                            conn.rollback()
                        except Exception:
                            pass

            conn.commit()

        # Seed default user if database is new
        self._seed_default_user()

    @staticmethod
    def hash_password(password: str) -> str:
        salt = "insta_trade_salt_2026"
        return hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()

    def _seed_default_user(self):
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, "SELECT COUNT(*) as cnt FROM users")
            row = cursor.fetchone()
            if row and row["cnt"] == 0:
                default_user = "aman_trader"
                default_pass = "password123"
                token = secrets.token_hex(24)
                self._execute(cursor, """
                    INSERT INTO users (username, password_hash, display_name, client_id, token)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    default_user,
                    self.hash_password(default_pass),
                    "Aman Pro",
                    "XH01499",
                    token
                ))
                self._execute(cursor, """
                    INSERT INTO user_funds (username, available_cash, used_margin, realized_pnl)
                    VALUES (?, 1000000.0, 0.0, 0.0)
                    ON CONFLICT(username) DO NOTHING
                """, (default_user,))
                conn.commit()

    # ------------------ USER AUTH ------------------
    def register_user(self, username: str, password: str, display_name: Optional[str] = None, client_id: Optional[str] = None) -> Dict[str, Any]:
        clean_user = username.strip().lower()
        if not clean_user or len(clean_user) < 3:
            return {"s": "error", "message": "Username must be at least 3 characters long"}
        if not password or len(password) < 4:
            return {"s": "error", "message": "Password must be at least 4 characters long"}

        d_name = display_name.strip() if display_name else clean_user.capitalize()
        c_id = client_id.strip().upper() if client_id else "PRO"
        pwd_hash = self.hash_password(password)
        token = secrets.token_hex(24)

        try:
            with self._get_connection() as conn:
                cursor = self._get_cursor(conn)
                self._execute(cursor, """
                    INSERT INTO users (username, password_hash, display_name, client_id, token)
                    VALUES (?, ?, ?, ?, ?)
                """, (clean_user, pwd_hash, d_name, c_id, token))

                self._execute(cursor, """
                    INSERT INTO user_sessions (token, username) VALUES (?, ?)
                    ON CONFLICT(token) DO NOTHING
                """, (token, clean_user))

                self._execute(cursor, """
                    INSERT INTO user_funds (username, available_cash, used_margin, realized_pnl)
                    VALUES (?, 1000000.0, 0.0, 0.0)
                    ON CONFLICT(username) DO NOTHING
                """, (clean_user,))
                conn.commit()

            return {
                "s": "ok",
                "message": f"Account '{clean_user}' created successfully with Rs. 10 Lakhs Virtual Capital!",
                "data": {
                    "username": clean_user,
                    "display_name": d_name,
                    "client_id": c_id,
                    "token": token
                }
            }
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str or "already exists" in err_str:
                return {"s": "error", "message": f"Username '{clean_user}' is already registered. Please choose another or login."}
            return {"s": "error", "message": f"Registration failed: {e}"}

    def authenticate_user(self, username: str, password: str) -> Dict[str, Any]:
        clean_user = username.strip().lower()
        pwd_hash = self.hash_password(password)

        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                SELECT username, display_name, client_id, password_hash
                FROM users WHERE username = ?
            """, (clean_user,))
            row = cursor.fetchone()
            if not row:
                # Seamless Cloud Recovery:
                # If database was wiped by container redeploy or user logging in on new browser,
                # auto-create/restore the account immediately with the entered credentials!
                logger.info(f"Auto-creating/restoring user '{clean_user}' on login.")
                return self.register_user(
                    username=clean_user,
                    password=password,
                    display_name=clean_user.capitalize(),
                    client_id="PRO",
                )

            if row["password_hash"] != pwd_hash:
                return {"s": "error", "message": "Incorrect password. Please try again."}

            token = secrets.token_hex(24)
            self._execute(cursor, "UPDATE users SET token = ? WHERE username = ?", (token, clean_user))
            self._execute(cursor, """
                INSERT INTO user_sessions (token, username) VALUES (?, ?)
                ON CONFLICT(token) DO NOTHING
            """, (token, clean_user))
            conn.commit()

            return {
                "s": "ok",
                "message": f"Welcome back, {row['display_name'] or clean_user}!",
                "data": {
                    "username": clean_user,
                    "display_name": row["display_name"] or clean_user.capitalize(),
                    "client_id": row["client_id"] or "PRO",
                    "token": token
                }
            }

    def get_user_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        t = token.strip()
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            # 1. Multi-device/multi-tab session check
            self._execute(cursor, """
                SELECT u.username, u.display_name, u.client_id
                FROM user_sessions s
                JOIN users u ON s.username = u.username
                WHERE s.token = ?
            """, (t,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            # 2. Direct token check
            self._execute(cursor, "SELECT username, display_name, client_id FROM users WHERE token = ?", (t,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def restore_user(self, username: str, token: str, display_name: Optional[str] = None, client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        clean_user = username.strip().lower()
        if not clean_user or not token:
            return None

        d_name = display_name.strip() if display_name else clean_user.capitalize()
        c_id = client_id.strip().upper() if client_id else "PRO"

        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, "SELECT * FROM users WHERE username = ?", (clean_user,))
            existing = cursor.fetchone()
            if existing:
                self._execute(cursor, "UPDATE users SET token = ? WHERE username = ?", (token.strip(), clean_user))
                self._execute(cursor, """
                    INSERT INTO user_sessions (token, username) VALUES (?, ?)
                    ON CONFLICT(token) DO NOTHING
                """, (token.strip(), clean_user))
                conn.commit()
            else:
                pwd_hash = self.hash_password("restored_pwd_2026")
                self._execute(cursor, """
                    INSERT INTO users (username, password_hash, display_name, client_id, token)
                    VALUES (?, ?, ?, ?, ?)
                """, (clean_user, pwd_hash, d_name, c_id, token.strip()))

                self._execute(cursor, """
                    INSERT INTO user_sessions (token, username) VALUES (?, ?)
                    ON CONFLICT(token) DO NOTHING
                """, (token.strip(), clean_user))

                self._execute(cursor, """
                    INSERT INTO user_funds (username, available_cash, used_margin, realized_pnl)
                    VALUES (?, 1000000.0, 0.0, 0.0)
                    ON CONFLICT(username) DO NOTHING
                """, (clean_user,))
                conn.commit()

        return self.get_user(clean_user)

    def sync_user_state(self, username: str, positions: Optional[List[Dict[str, Any]]] = None, orders: Optional[List[Dict[str, Any]]] = None):
        clean_user = username.strip().lower()
        if not clean_user:
            return
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            if positions:
                for p in positions:
                    if not p or not p.get("symbol") or not p.get("net_qty"):
                        continue
                    pos_id = p.get("id") or f"{clean_user}:{p['symbol']}"
                    expiry = p.get("expiry") or ""
                    created_date = p.get("created_date") or datetime.date.today().strftime("%Y-%m-%d")
                    self._execute(cursor, """
                        INSERT INTO user_positions (id, username, symbol, side, product, net_qty, buy_avg, sell_avg, margin_held, expiry, created_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            net_qty = excluded.net_qty,
                            buy_avg = excluded.buy_avg,
                            sell_avg = excluded.sell_avg,
                            margin_held = excluded.margin_held,
                            expiry = CASE WHEN excluded.expiry IS NOT NULL AND excluded.expiry != '' THEN excluded.expiry ELSE user_positions.expiry END,
                            created_date = COALESCE(user_positions.created_date, excluded.created_date)
                    """, (
                        pos_id,
                        clean_user,
                        p["symbol"],
                        p.get("side", "BUY"),
                        p.get("product", "INTRADAY"),
                        int(p["net_qty"]),
                        float(p.get("buy_avg", 0.0)),
                        float(p.get("sell_avg", 0.0)),
                        float(p.get("margin_held", 0.0)),
                        expiry,
                        created_date
                    ))
            if orders:
                IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
                today_ist = datetime.datetime.now(IST).strftime("%Y-%m-%d")
                for o in orders:
                    if not o or not o.get("id") or not o.get("symbol"):
                        continue
                    o_date = o.get("order_date") or o.get("date") or today_ist
                    # Only accept orders from today's trading session (previous days are cleared at EOD)
                    if o_date != today_ist:
                        continue
                    self._execute(cursor, """
                        INSERT INTO user_orders (id, username, order_time, symbol, side, order_type, product, qty, price, status, expiry, order_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            order_time = excluded.order_time,
                            status = excluded.status,
                            expiry = excluded.expiry,
                            order_date = excluded.order_date
                    """, (
                        o["id"],
                        clean_user,
                        o.get("time", ""),
                        o["symbol"],
                        o.get("side", "BUY"),
                        o.get("type", o.get("order_type", "BUY")),
                        o.get("product", "INTRADAY"),
                        int(o.get("qty", 1)),
                        float(o.get("price", 0.0)),
                        o.get("status", "FILLED"),
                        o.get("expiry", ""),
                        o_date
                    ))
            conn.commit()

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, "SELECT username, display_name, client_id FROM users WHERE username = ?", (username.strip().lower(),))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def update_user_credentials(self, username: str, password: Optional[str] = None, display_name: Optional[str] = None, client_id: Optional[str] = None) -> Dict[str, Any]:
        clean_user = username.strip().lower()
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            updates = []
            params = []
            if password and password.strip():
                updates.append("password_hash = ?")
                params.append(self.hash_password(password.strip()))
            if display_name:
                updates.append("display_name = ?")
                params.append(display_name.strip())
            if client_id:
                updates.append("client_id = ?")
                params.append(client_id.strip().upper())

            if updates:
                params.append(clean_user)
                self._execute(cursor, f"UPDATE users SET {', '.join(updates)} WHERE username = ?", tuple(params))
                conn.commit()

            self._execute(cursor, "SELECT username, display_name, client_id FROM users WHERE username = ?", (clean_user,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    # ------------------ FUNDS PER USER ------------------
    def get_funds(self, username: str) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, "SELECT available_cash, used_margin, realized_pnl FROM user_funds WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row:
                return {
                    "available_cash": float(row["available_cash"]),
                    "used_margin": float(row["used_margin"]),
                    "realized_pnl": float(row["realized_pnl"]),
                }
            return {"available_cash": 1000000.0, "used_margin": 0.0, "realized_pnl": 0.0}

    def update_funds(self, username: str, available_cash: float, used_margin: float, realized_pnl: float):
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                INSERT INTO user_funds (username, available_cash, used_margin, realized_pnl)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    available_cash = excluded.available_cash,
                    used_margin = excluded.used_margin,
                    realized_pnl = excluded.realized_pnl
            """, (username, available_cash, used_margin, realized_pnl))
            conn.commit()

    def reset_funds(self, username: str, capital: float = 1000000.0):
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                UPDATE user_funds SET available_cash = ?, used_margin = 0.0, realized_pnl = 0.0
                WHERE username = ?
            """, (capital, username))
            self._execute(cursor, "DELETE FROM user_positions WHERE username = ?", (username,))
            self._execute(cursor, "DELETE FROM user_orders WHERE username = ?", (username,))
            self._execute(cursor, "DELETE FROM user_daily_pnl WHERE username = ?", (username,))
            conn.commit()

    # ------------------ POSITIONS PER USER ------------------
    def get_positions(self, username: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                SELECT id, symbol, side, product, net_qty, buy_avg, sell_avg, margin_held, expiry, created_date
                FROM user_positions WHERE username = ?
            """, (username,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def save_position(self, username: str, pos: Dict[str, Any]):
        pos_id = f"{username}:{pos['symbol']}"
        expiry = pos.get("expiry") or ""
        created_date = pos.get("created_date") or datetime.date.today().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                INSERT INTO user_positions (id, username, symbol, side, product, net_qty, buy_avg, sell_avg, margin_held, expiry, created_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    side = excluded.side,
                    product = excluded.product,
                    net_qty = excluded.net_qty,
                    buy_avg = excluded.buy_avg,
                    sell_avg = excluded.sell_avg,
                    margin_held = excluded.margin_held,
                    expiry = CASE WHEN excluded.expiry IS NOT NULL AND excluded.expiry != '' THEN excluded.expiry ELSE user_positions.expiry END,
                    created_date = COALESCE(user_positions.created_date, excluded.created_date)
            """, (
                pos_id,
                username,
                pos["symbol"],
                pos.get("side", "BUY"),
                pos.get("product", "INTRADAY"),
                int(pos["net_qty"]),
                float(pos.get("buy_avg", 0.0)),
                float(pos.get("sell_avg", 0.0)),
                float(pos.get("margin_held", 0.0)),
                expiry,
                created_date
            ))
            conn.commit()

    def delete_position(self, username: str, symbol: str):
        pos_id = f"{username}:{symbol}"
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, "DELETE FROM user_positions WHERE id = ?", (pos_id,))
            conn.commit()

    def clear_positions(self, username: str):
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, "DELETE FROM user_positions WHERE username = ?", (username,))
            conn.commit()

    # ------------------ ORDERS PER USER ------------------
    def get_orders(self, username: str, today_only: bool = True) -> List[Dict[str, Any]]:
        IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        today_ist = datetime.datetime.now(IST).strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            if today_only:
                # EOD Auto-Pruning: Purge old orders older than today's IST trading session
                try:
                    self._execute(cursor, """
                        DELETE FROM user_orders 
                        WHERE username = ? AND order_date != '' AND order_date IS NOT NULL AND order_date < ?
                    """, (username, today_ist))
                    conn.commit()
                except Exception:
                    pass

                self._execute(cursor, """
                    SELECT id, order_time as time, symbol, side, order_type as type, product, qty, price, status, expiry, order_date as date
                    FROM user_orders 
                    WHERE username = ? AND order_date = ?
                    ORDER BY id DESC
                """, (username, today_ist))
            else:
                self._execute(cursor, """
                    SELECT id, order_time as time, symbol, side, order_type as type, product, qty, price, status, expiry, order_date as date
                    FROM user_orders WHERE username = ? ORDER BY id DESC
                """, (username,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def add_order(self, username: str, order: Dict[str, Any]):
        IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        today_ist = datetime.datetime.now(IST).strftime("%Y-%m-%d")
        order_date = order.get("order_date") or order.get("date") or today_ist
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                INSERT INTO user_orders (id, username, order_time, symbol, side, order_type, product, qty, price, status, expiry, order_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    order_time = excluded.order_time,
                    status = excluded.status,
                    expiry = excluded.expiry,
                    order_date = excluded.order_date
            """, (
                order["id"],
                username,
                order.get("time", datetime.datetime.now(IST).strftime("%H:%M:%S")),
                order["symbol"],
                order["side"],
                order.get("type", "BUY"),
                order.get("product", "INTRADAY"),
                int(order["qty"]),
                float(order["price"]),
                order.get("status", "FILLED"),
                order.get("expiry", ""),
                order_date
            ))
            conn.commit()

    # ------------------ 1-YEAR DAILY P&L HISTORY & CALENDAR ------------------
    def record_daily_pnl(self, username: str, pnl_date: str, realized_pnl: float, trades_count: int = 1):
        clean_user = username.strip().lower()
        rec_id = f"{clean_user}:{pnl_date}"
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                INSERT INTO user_daily_pnl (id, username, pnl_date, realized_pnl, trades_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    realized_pnl = excluded.realized_pnl,
                    trades_count = excluded.trades_count
            """, (rec_id, clean_user, pnl_date, float(realized_pnl), int(trades_count)))
            conn.commit()

    def get_daily_pnl_history(self, username: str, days_limit: int = 365) -> Dict[str, Any]:
        clean_user = username.strip().lower()
        IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(IST)
        today_date = now_ist.date()
        today_str = today_date.strftime("%Y-%m-%d")
        cutoff_date_str = (today_date - datetime.timedelta(days=days_limit)).strftime("%Y-%m-%d")

        # Sync today's current Realized P&L from closed positions (Unrealized MTM is strictly excluded)
        try:
            funds = self.get_funds(clean_user)
            today_realized = float(funds.get("realized_pnl", 0.0))
            today_orders = self.get_orders(clean_user, today_only=True)
            if today_realized != 0.0 or len(today_orders) > 0:
                self.record_daily_pnl(clean_user, today_str, today_realized, len(today_orders))
        except Exception:
            pass

        # Query ONLY actual recorded rows from genuine trades in the database
        with self._get_connection() as conn:
            cursor = self._get_cursor(conn)
            self._execute(cursor, """
                SELECT pnl_date, realized_pnl, trades_count
                FROM user_daily_pnl
                WHERE username = ? AND pnl_date >= ?
                ORDER BY pnl_date DESC
            """, (clean_user, cutoff_date_str))
            rows = cursor.fetchall()

        all_entries = []
        for r in rows:
            pnl_val = float(r["realized_pnl"])
            tr_cnt = int(r["trades_count"])
            d_str = r["pnl_date"]
            try:
                d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                formatted_date = d_obj.strftime("%d %b %Y")
                day_name = d_obj.strftime("%A")
            except Exception:
                formatted_date = d_str
                day_name = ""

            status = "PROFIT" if pnl_val > 0 else ("LOSS" if pnl_val < 0 else "BREAKEVEN")
            all_entries.append({
                "date": d_str,
                "formatted_date": formatted_date,
                "day_name": day_name,
                "pnl": round(pnl_val, 2),
                "trades": tr_cnt,
                "status": status,
            })

        # Calculate metrics from real data only
        total_pnl = sum(e["pnl"] for e in all_entries)
        profit_days = [e for e in all_entries if e["pnl"] > 0]
        loss_days = [e for e in all_entries if e["pnl"] < 0]
        breakeven_days = [e for e in all_entries if e["pnl"] == 0.0]

        win_rate = round((len(profit_days) / len(all_entries) * 100), 1) if all_entries else 0.0

        max_profit_day = max(profit_days, key=lambda x: x["pnl"]) if profit_days else None
        max_loss_day = min(loss_days, key=lambda x: x["pnl"]) if loss_days else None

        # Monthly aggregation from real data only
        monthly_map = {}
        for e in all_entries:
            try:
                month_key = datetime.datetime.strptime(e["date"], "%Y-%m-%d").strftime("%b %Y")
            except Exception:
                month_key = "Recent"
            if month_key not in monthly_map:
                monthly_map[month_key] = {"month": month_key, "pnl": 0.0, "trades": 0, "profit_days": 0, "loss_days": 0, "total_days": 0}
            monthly_map[month_key]["pnl"] += e["pnl"]
            monthly_map[month_key]["trades"] += e["trades"]
            monthly_map[month_key]["total_days"] += 1
            if e["pnl"] > 0:
                monthly_map[month_key]["profit_days"] += 1
            elif e["pnl"] < 0:
                monthly_map[month_key]["loss_days"] += 1

        monthly_breakdown = []
        for m in monthly_map.values():
            m["pnl"] = round(m["pnl"], 2)
            active_d = m["profit_days"] + m["loss_days"]
            m["win_rate"] = round((m["profit_days"] / active_d * 100), 1) if active_d > 0 else 0.0
            monthly_breakdown.append(m)

        # Running cumulative P&L
        cumulative = 0.0
        for e in reversed(all_entries):
            cumulative += e["pnl"]
            e["cumulative_pnl"] = round(cumulative, 2)

        return {
            "summary": {
                "total_pnl": round(total_pnl, 2),
                "win_rate": win_rate,
                "total_trading_days": len(all_entries),
                "profit_days_count": len(profit_days),
                "loss_days_count": len(loss_days),
                "breakeven_days_count": len(breakeven_days),
                "max_profit": max_profit_day["pnl"] if max_profit_day else 0.0,
                "max_profit_date": max_profit_day["formatted_date"] if max_profit_day else "-",
                "max_loss": max_loss_day["pnl"] if max_loss_day else 0.0,
                "max_loss_date": max_loss_day["formatted_date"] if max_loss_day else "-",
                "avg_daily_pnl": round(total_pnl / len(all_entries), 2) if all_entries else 0.0,
            },
            "monthly": monthly_breakdown,
            "days": all_entries,
        }


# Global DB instance
db = DatabaseManager()

