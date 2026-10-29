"""Small password hashing helpers using PBKDF2 from the Python standard library."""
import base64
import hashlib
import hmac
import secrets

_PREFIX = "$eagle$pbkdf2_sha256$"
_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_PREFIX}{_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def is_password_hash(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(stored, str):
        return False
    if not is_password_hash(stored):
        return hmac.compare_digest(password, stored)
    try:
        _, _, algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
