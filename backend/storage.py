import os
import hashlib
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from backend.security import verify_password, is_password_hash, hash_password

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set in your .env file!")
    # Neon PostgreSQL requires sslmode=require (typically included in the connection string)
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create PostgreSQL tables with proper SERIAL auto-increment syntax
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username VARCHAR(50) PRIMARY KEY,
            password TEXT NOT NULL,
            display_name VARCHAR(100),
            client_id VARCHAR(50),
            token TEXT
        );
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_positions (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) REFERENCES users(username) ON DELETE CASCADE,
            symbol VARCHAR(50),
            qty INT,
            avg_price FLOAT,
            side INT
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_orders (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) REFERENCES users(username) ON DELETE CASCADE,
            order_id VARCHAR(50),
            symbol VARCHAR(50),
            qty INT,
            side INT,
            order_type INT,
            product_type VARCHAR(20),
            price FLOAT,
            status VARCHAR(20)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_pnl (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) REFERENCES users(username) ON DELETE CASCADE,
            date VARCHAR(20),
            pnl FLOAT
        );
    """)


    # Virtual-trading state used by backend/virtual_engine.py.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_funds (
            username VARCHAR(50) PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
            available_cash DOUBLE PRECISION NOT NULL DEFAULT 1000000.0,
            used_margin DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Extend older installations without dropping existing user state.
    for statement in (
        "ALTER TABLE user_positions ADD COLUMN IF NOT EXISTS net_qty INTEGER",
        "ALTER TABLE user_positions ADD COLUMN IF NOT EXISTS buy_avg DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE user_positions ADD COLUMN IF NOT EXISTS sell_avg DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE user_positions ADD COLUMN IF NOT EXISTS expiry VARCHAR(40) NOT NULL DEFAULT ''",
        "ALTER TABLE user_positions ADD COLUMN IF NOT EXISTS created_date VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS type VARCHAR(20) NOT NULL DEFAULT 'BUY'",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS order_type_text VARCHAR(20) NOT NULL DEFAULT 'MARKET'",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS product VARCHAR(30) NOT NULL DEFAULT 'INTRADAY'",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS expiry VARCHAR(40) NOT NULL DEFAULT ''",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS order_date VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS time VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE daily_pnl ADD COLUMN IF NOT EXISTS order_count INTEGER NOT NULL DEFAULT 0",
    ):
        cursor.execute(statement)
    cursor.execute("""
        UPDATE user_positions
        SET net_qty = CASE WHEN COALESCE(side, 1) < 0 THEN -ABS(COALESCE(qty, 0))
                           ELSE ABS(COALESCE(qty, 0)) END
        WHERE net_qty IS NULL
    """)
    cursor.execute("""
        UPDATE user_positions
        SET buy_avg = COALESCE(NULLIF(avg_price, 0), buy_avg),
            sell_avg = COALESCE(NULLIF(avg_price, 0), sell_avg)
        WHERE buy_avg = 0 OR sell_avg = 0
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS user_positions_username_symbol_uidx
        ON user_positions (username, symbol)
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS daily_pnl_username_date_uidx
        ON daily_pnl (username, date)
    """)

    conn.commit()
    cursor.close()
    conn.close()

# Initialize database tables on module import
try:
    init_db()
except Exception as e:
    print(f"Database initialization warning: {e}")

class Database:
    def get_user_by_token(self, token: str):
        if not token:
            return None
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE token = %s", (token,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return dict(user) if user else None

    def get_user(self, username: str):
        if not username:
            return None
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(%s)", (username.strip(),))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return dict(user) if user else None

    def register_user(self, username: str, password: str, display_name: str = "", client_id: str = ""):
        clean_user = username.strip().lower()
        if not clean_user or not password:
            return {"s": "error", "message": "Username and password are required"}
        
        existing = self.get_user(clean_user)
        if existing:
            return {"s": "error", "message": "Username already exists"}
        
        token = secrets.token_hex(32)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password, display_name, client_id, token) VALUES (%s, %s, %s, %s, %s)",
                (clean_user, password if is_password_hash(password) else hash_password(password), display_name or clean_user, client_id or "XH01499", token)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            cursor.close()
            conn.close()
            return {"s": "error", "message": str(e)}
        
        cursor.close()
        conn.close()
        return {
            "s": "ok",
            "message": "User registered successfully",
            "token": token,
            "user": {
                "username": clean_user,
                "display_name": display_name or clean_user,
                "client_id": client_id or "XH01499"
            }
        }

    def authenticate_user(self, username: str, password: str):
        clean_user = username.strip().lower()
        user = self.get_user(clean_user)
        if not user or not verify_password(password, user["password"]):
            return {"s": "error", "message": "Invalid username or password"}
        
        token = user.get("token") or secrets.token_hex(32)
        if not user.get("token"):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET token = %s WHERE username = %s", (token, clean_user))
            conn.commit()
            cursor.close()
            conn.close()

        return {
            "s": "ok",
            "message": "Login successful",
            "token": token,
            "user": {
                "username": user["username"],
                "display_name": user.get("display_name"),
                "client_id": user.get("client_id")
            }
        }

    def restore_user(self, username: str, token: str, display_name: str = "", client_id: str = ""):
        clean_user = username.strip().lower()
        user = self.get_user(clean_user)
        if user:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET token = %s WHERE username = %s", (token, clean_user))
            conn.commit()
            cursor.close()
            conn.close()
            user["token"] = token
            return user
        else:
            res = self.register_user(clean_user, "autorecoverypassword", display_name, client_id)
            if res["s"] == "ok":
                return self.get_user(clean_user)
        return None

    def update_user_credentials(self, username: str, password: str = "", display_name: str = "", client_id: str = ""):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        updates = []
        params = []
        if password:
            updates.append("password = %s")
            params.append(password if is_password_hash(password) else hash_password(password))
        if display_name:
            updates.append("display_name = %s")
            params.append(display_name)
        if client_id:
            updates.append("client_id = %s")
            params.append(client_id)
            
        if updates:
            params.append(clean_user)
            query = f"UPDATE users SET {', '.join(updates)} WHERE username = %s"
            cursor.execute(query, params)
            conn.commit()
            
        cursor.close()
        conn.close()
        return self.get_user(clean_user)

    def sync_user_state(self, username: str, positions=None, orders=None):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if positions is not None:
            cursor.execute("DELETE FROM user_positions WHERE username = %s", (clean_user,))
            for p in positions:
                cursor.execute(
                    "INSERT INTO user_positions (username, symbol, qty, avg_price, side) VALUES (%s, %s, %s, %s, %s)",
                    (clean_user, p.get("symbol"), p.get("qty", 0), p.get("avg_price", 0.0), p.get("side", 1))
                )
                
        if orders is not None:
            cursor.execute("DELETE FROM user_orders WHERE username = %s", (clean_user,))
            for o in orders:
                cursor.execute(
                    "INSERT INTO user_orders (username, order_id, symbol, qty, side, order_type, product_type, price, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (clean_user, str(o.get("order_id", "")), o.get("symbol"), o.get("qty", 0), o.get("side", 1), o.get("order_type", 2), o.get("product_type", "INTRADAY"), o.get("price", 0.0), o.get("status", "COMPLETE"))
                )
                
        conn.commit()
        cursor.close()
        conn.close()


    def get_all_users(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT username FROM users ORDER BY username")
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_funds(self, username: str):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_funds (username)
                    SELECT username FROM users WHERE LOWER(username) = %s
                    ON CONFLICT (username) DO NOTHING
                """, (clean_user,))
                cursor.execute("""
                    SELECT available_cash, used_margin, realized_pnl
                    FROM user_funds WHERE username = %s
                """, (clean_user,))
                row = cursor.fetchone()
                if not row:
                    raise ValueError(f"Trading account not found for user '{clean_user}'")
                conn.commit()
                return dict(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_funds(self, username: str, available_cash: float, used_margin: float, realized_pnl: float):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_funds (username, available_cash, used_margin, realized_pnl, updated_at)
                    SELECT username, %s, %s, %s, NOW()
                    FROM users WHERE LOWER(username) = %s
                    ON CONFLICT (username) DO UPDATE SET
                        available_cash = EXCLUDED.available_cash,
                        used_margin = EXCLUDED.used_margin,
                        realized_pnl = EXCLUDED.realized_pnl,
                        updated_at = NOW()
                """, (available_cash, used_margin, realized_pnl, clean_user))
                if cursor.rowcount == 0:
                    raise ValueError(f"Trading account not found for user '{clean_user}'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reset_funds(self, username: str, capital: float = 1000000.0):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_funds (username, available_cash, used_margin, realized_pnl, updated_at)
                    SELECT username, %s, 0, 0, NOW()
                    FROM users WHERE LOWER(username) = %s
                    ON CONFLICT (username) DO UPDATE SET
                        available_cash = EXCLUDED.available_cash,
                        used_margin = 0,
                        realized_pnl = 0,
                        updated_at = NOW()
                """, (capital, clean_user))
                if cursor.rowcount == 0:
                    raise ValueError(f"Trading account not found for user '{clean_user}'")
                cursor.execute("DELETE FROM user_positions WHERE LOWER(username) = %s", (clean_user,))
                cursor.execute("DELETE FROM user_orders WHERE LOWER(username) = %s", (clean_user,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_positions(self, username: str):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, username, symbol, qty, avg_price, side, net_qty,
                           buy_avg, sell_avg, expiry, created_date
                    FROM user_positions
                    WHERE LOWER(username) = %s
                    ORDER BY id
                """, (clean_user,))
                rows = [dict(row) for row in cursor.fetchall()]
            positions = []
            for row in rows:
                net_qty = row.get("net_qty")
                if net_qty is None:
                    net_qty = abs(int(row.get("qty") or 0)) * (-1 if int(row.get("side") or 1) < 0 else 1)
                row["net_qty"] = int(net_qty)
                row["side"] = "BUY" if row["net_qty"] > 0 else "SELL"
                row["buy_avg"] = float(row.get("buy_avg") or row.get("avg_price") or 0)
                row["sell_avg"] = float(row.get("sell_avg") or row.get("avg_price") or 0)
                row["expiry"] = row.get("expiry") or ""
                row["created_date"] = row.get("created_date") or ""
                positions.append(row)
            return positions
        finally:
            conn.close()

    def save_position(self, username: str, position: dict):
        clean_user = username.strip().lower()
        symbol = position.get("symbol")
        if not symbol:
            raise ValueError("Position symbol is required")
        net_qty = int(position.get("net_qty", 0))
        avg_price = float(position.get("buy_avg") or position.get("sell_avg") or 0)
        legacy_side = 1 if net_qty >= 0 else -1
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_positions
                        (username, symbol, qty, avg_price, side, net_qty, buy_avg, sell_avg, expiry, created_date)
                    SELECT username, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    FROM users WHERE LOWER(username) = %s
                    ON CONFLICT (username, symbol) DO UPDATE SET
                        qty = EXCLUDED.qty,
                        avg_price = EXCLUDED.avg_price,
                        side = EXCLUDED.side,
                        net_qty = EXCLUDED.net_qty,
                        buy_avg = EXCLUDED.buy_avg,
                        sell_avg = EXCLUDED.sell_avg,
                        expiry = EXCLUDED.expiry,
                        created_date = EXCLUDED.created_date
                """, (
                    symbol, abs(net_qty), avg_price, legacy_side, net_qty,
                    float(position.get("buy_avg") or 0), float(position.get("sell_avg") or 0),
                    position.get("expiry") or "", position.get("created_date") or "",
                    clean_user
                ))
                if cursor.rowcount == 0:
                    raise ValueError(f"Trading account not found for user '{clean_user}'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_position(self, username: str, symbol: str):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM user_positions WHERE LOWER(username) = %s AND symbol = %s",
                               (username.strip().lower(), symbol))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_order(self, username: str, order: dict):
        clean_user = username.strip().lower()
        side_text = str(order.get("side") or order.get("type") or "BUY").upper()
        side_num = 1 if side_text == "BUY" else -1
        order_type_text = str(order.get("order_type") or "MARKET").upper()
        order_type_num = 2 if order_type_text == "MARKET" else 1
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_orders
                        (username, order_id, symbol, qty, side, order_type, product_type,
                         price, status, type, order_type_text, product, expiry, order_date,
                         time, realized_pnl)
                    SELECT username, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    FROM users WHERE LOWER(username) = %s
                """, (
                    str(order.get("id") or order.get("order_id") or ""),
                    order.get("symbol"), int(order.get("qty") or 0), side_num, order_type_num,
                    str(order.get("product") or "INTRADAY"), float(order.get("price") or 0),
                    str(order.get("status") or "FILLED"), side_text, order_type_text,
                    str(order.get("product") or "INTRADAY"), str(order.get("expiry") or ""),
                    str(order.get("order_date") or ""), str(order.get("time") or ""),
                    float(order.get("realized_pnl") or order.get("pnl") or 0), clean_user
                ))
                if cursor.rowcount == 0:
                    raise ValueError(f"Trading account not found for user '{clean_user}'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_orders(self, username: str, today_only: bool = False):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                query = """
                    SELECT id, order_id, symbol, qty, side, order_type, product_type,
                           price, status, type, order_type_text, product, expiry, order_date,
                           time, realized_pnl
                    FROM user_orders WHERE LOWER(username) = %s
                """
                params = [clean_user]
                if today_only:
                    from datetime import datetime, timezone, timedelta
                    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
                    query += " AND order_date = %s"
                    params.append(today)
                query += " ORDER BY id DESC"
                cursor.execute(query, params)
                rows = [dict(row) for row in cursor.fetchall()]
            orders = []
            for row in rows:
                row["id"] = row.get("order_id") or str(row.get("id"))
                row["side"] = row.get("type") or ("BUY" if int(row.get("side") or 1) > 0 else "SELL")
                row["type"] = row["side"]
                row["order_type"] = row.get("order_type_text") or ("MARKET" if int(row.get("order_type") or 2) == 2 else "LIMIT")
                row["product"] = row.get("product") or row.get("product_type") or "INTRADAY"
                orders.append(row)
            return orders
        finally:
            conn.close()

    def record_daily_pnl(self, username: str, date: str, pnl: float, order_count: int = 0):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO daily_pnl (username, date, pnl, order_count)
                    SELECT username, %s, %s, %s FROM users WHERE LOWER(username) = %s
                    ON CONFLICT (username, date) DO UPDATE SET
                        pnl = EXCLUDED.pnl, order_count = EXCLUDED.order_count
                """, (date, pnl, order_count, clean_user))
                if cursor.rowcount == 0:
                    raise ValueError(f"Trading account not found for user '{clean_user}'")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_daily_pnl_history(self, username: str, days_limit: int = 365):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT date, pnl FROM daily_pnl WHERE username = %s ORDER BY date DESC LIMIT %s", (clean_user, days_limit))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(r) for r in rows]

db = Database()
