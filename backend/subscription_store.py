"""Persistent signup intents and subscription state backed by the app PostgreSQL database."""
import secrets
from datetime import datetime, timezone
from backend.storage import get_db_connection


def init_subscription_tables():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_signups (
                    signup_id VARCHAR(80) PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name VARCHAR(100),
                    client_id VARCHAR(50),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    username VARCHAR(50) PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
                    paypal_subscription_id VARCHAR(128) UNIQUE,
                    plan_id VARCHAR(128),
                    status VARCHAR(32) NOT NULL DEFAULT 'inactive',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS demo_accounts (
                    username VARCHAR(50) PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_by VARCHAR(100) NOT NULL DEFAULT 'admin'
                )
            """)
        conn.commit()
    finally:
        conn.close()


def create_pending_signup(username: str, password_hash: str, display_name: str = "", client_id: str = ""):
    clean = username.strip().lower()
    if not clean or len(clean) < 3:
        return {"s": "error", "message": "Username must be at least 3 characters."}
    signup_id = secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pending_signups WHERE created_at < NOW() - INTERVAL '24 hours'")
            cur.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (clean,))
            if cur.fetchone():
                return {"s": "error", "message": "Username already exists."}
            cur.execute("SELECT 1 FROM pending_signups WHERE LOWER(username) = LOWER(%s)", (clean,))
            if cur.fetchone():
                return {"s": "error", "message": "A signup is already pending for this username. Resume that signup or try again after 24 hours."}
            cur.execute(
                "INSERT INTO pending_signups (signup_id, username, password_hash, display_name, client_id) VALUES (%s, %s, %s, %s, %s)",
                (signup_id, clean, password_hash, (display_name or clean)[:100], (client_id or "")[:50]),
            )
        conn.commit()
        return {"s": "ok", "signup_id": signup_id, "message": "Signup saved. Complete PayPal subscription to activate your account."}
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return {"s": "error", "message": "That username is already registered or has a pending signup."}
        raise
    finally:
        conn.close()


def get_pending_signup(signup_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT signup_id, username, password_hash, display_name, client_id FROM pending_signups WHERE signup_id = %s", (signup_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def activate_pending_signup(signup_id: str, subscription_id: str, plan_id: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT signup_id, username, password_hash, display_name, client_id FROM pending_signups WHERE signup_id = %s FOR UPDATE", (signup_id,))
            row = cur.fetchone()
            if not row:
                return {"s": "error", "message": "Signup request not found or expired."}
            signup = dict(row)
            cur.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (signup["username"],))
            if cur.fetchone():
                cur.execute("DELETE FROM pending_signups WHERE signup_id = %s", (signup_id,))
                conn.commit()
                return {"s": "error", "message": "Username is already registered."}
            cur.execute(
                "INSERT INTO users (username, password, display_name, client_id, token) VALUES (%s, %s, %s, %s, %s)",
                (signup["username"], signup["password_hash"], signup.get("display_name") or signup["username"], signup.get("client_id") or "XH01499", secrets.token_hex(32)),
            )
            cur.execute(
                "INSERT INTO user_subscriptions (username, paypal_subscription_id, plan_id, status, updated_at) VALUES (%s, %s, %s, 'active', %s)",
                (signup["username"], subscription_id, plan_id, datetime.now(timezone.utc)),
            )
            cur.execute("DELETE FROM pending_signups WHERE signup_id = %s", (signup_id,))
        conn.commit()
        return {"s": "ok", "message": "Subscription verified and account activated.", "username": signup["username"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_subscription_status(subscription_id: str, status: str) -> bool:
    normalized = (status or "").lower()
    if normalized not in {"active", "suspended", "cancelled", "expired", "inactive"}:
        return False
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_subscriptions SET status = %s, updated_at = %s WHERE paypal_subscription_id = %s",
                (normalized, datetime.now(timezone.utc), subscription_id),
            )
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def is_subscription_active(username: str) -> bool:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM user_subscriptions WHERE LOWER(username) = LOWER(%s)", (username,))
            row = cur.fetchone()
            if not row or str(row["status"]).lower() != "active":
                return False
            cur.execute("SELECT enabled FROM demo_accounts WHERE LOWER(username) = LOWER(%s)", (username,))
            demo = cur.fetchone()
            # Normal paid accounts have no demo_accounts row. Demo accounts must be enabled.
            return bool(demo["enabled"]) if demo else True
    finally:
        conn.close()


def is_demo_account(username: str) -> bool:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM demo_accounts WHERE LOWER(username) = LOWER(%s)", (username,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def create_demo_account(username: str, password_hash: str, display_name: str = "", created_by: str = "admin"):
    clean = (username or "").strip().lower()
    if len(clean) < 3 or len(clean) > 50:
        return {"s": "error", "message": "Username must be between 3 and 50 characters."}
    conn = get_db_connection()
    token = secrets.token_hex(32)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (clean,))
            if cur.fetchone():
                return {"s": "error", "message": "Username already exists."}
            cur.execute("SELECT 1 FROM pending_signups WHERE LOWER(username) = LOWER(%s)", (clean,))
            if cur.fetchone():
                return {"s": "error", "message": "A signup is already pending for this username."}
            cur.execute(
                "INSERT INTO users (username, password, display_name, client_id, token) VALUES (%s, %s, %s, %s, %s)",
                (clean, password_hash, (display_name or clean)[:100], "DEMO", token),
            )
            cur.execute(
                "INSERT INTO user_subscriptions (username, paypal_subscription_id, plan_id, status, updated_at) VALUES (%s, NULL, 'demo', 'active', NOW())",
                (clean,),
            )
            cur.execute(
                "INSERT INTO demo_accounts (username, enabled, created_by) VALUES (%s, TRUE, %s)",
                (clean, (created_by or "admin")[:100]),
            )
        conn.commit()
        return {"s": "ok", "username": clean, "message": "Demo account created."}
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return {"s": "error", "message": "Username already exists."}
        raise
    finally:
        conn.close()


def list_demo_accounts():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.username, u.display_name, d.enabled, d.created_at, d.created_by
                FROM demo_accounts d JOIN users u ON u.username = d.username
                ORDER BY d.created_at DESC
            """)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def set_demo_account_enabled(username: str, enabled: bool) -> bool:
    clean = (username or "").strip().lower()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE demo_accounts SET enabled = %s WHERE LOWER(username) = LOWER(%s)", (bool(enabled), clean))
            changed = cur.rowcount > 0
            if changed:
                cur.execute(
                    "UPDATE user_subscriptions SET status = %s, updated_at = NOW() WHERE LOWER(username) = LOWER(%s)",
                    ("active" if enabled else "inactive", clean),
                )
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_subscription(username: str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT paypal_subscription_id, plan_id, status, updated_at FROM user_subscriptions WHERE LOWER(username) = LOWER(%s)", (username,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
