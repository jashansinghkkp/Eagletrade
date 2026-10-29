import os
import hashlib
import secrets
import json
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            username VARCHAR(50) PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
            preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
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


    def get_preferences(self, username: str):
        clean_user = username.strip().lower()
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT preferences FROM user_preferences WHERE username = %s",
                (clean_user,),
            )
            row = cursor.fetchone()
            return dict(row["preferences"] or {}) if row else {}
        finally:
            cursor.close()
            conn.close()

    def update_preferences(self, username: str, preferences: dict):
        clean_user = username.strip().lower()
        encoded = json.dumps(preferences, separators=(",", ":"), allow_nan=False)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO user_preferences (username, preferences, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (username) DO UPDATE
                SET preferences = user_preferences.preferences || EXCLUDED.preferences,
                    updated_at = NOW()
                """,
                (clean_user, encoded),
            )
            conn.commit()
            cursor.execute(
                "SELECT preferences, updated_at FROM user_preferences WHERE username = %s",
                (clean_user,),
            )
            row = cursor.fetchone()
            return {"preferences": dict(row["preferences"] or {}), "updated_at": row["updated_at"].isoformat() if row and row.get("updated_at") else None}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
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
