"""Authentication helpers: password hashing, session guards, rate limiting."""

import collections
import hashlib
import logging
import os
import secrets
import time

from fastapi import HTTPException, Request

from config import CONFIG_PATH, get_secret_key_from_config
from db import has_users, upsert_user

logger = logging.getLogger(__name__)


def hash_password(plain: str) -> str:
    """Hash a plaintext password with scrypt. Returns 'salt_hex:hash_hex'."""
    salt = os.urandom(16)
    key = hashlib.scrypt(plain.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + key.hex()


def verify_password(plain: str, stored: str) -> bool:
    """Verify a plaintext password against a stored 'salt_hex:hash_hex' string."""
    try:
        salt_hex, key_hex = stored.split(":", 1)
        key = hashlib.scrypt(plain.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1)
        return key.hex() == key_hex
    except Exception:  # noqa: BLE001 — broad catch intentional: any malformed hash → reject
        return False


async def init_admin_user() -> None:
    """
    Ensure at least one user exists in DB.

    - If ADMIN_PASSWORD env var is set: upsert admin with that password (useful
      for Docker secrets / initial deploy / password reset).
    - Else if DB has no users: generate a random password, store it, log it.
    """
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if admin_password:
        await upsert_user(admin_username, hash_password(admin_password))
        logger.info("Admin user '%s' password applied from ADMIN_PASSWORD env var", admin_username)
    elif not await has_users():
        admin_password = secrets.token_urlsafe(16)
        await upsert_user(admin_username, hash_password(admin_password))
        sep = "=" * 56
        logger.warning(sep)
        logger.warning("  FIRST RUN — admin account created")
        logger.warning("  Username : %s", admin_username)
        logger.warning("  Password : %s", admin_password)
        logger.warning("  Set ADMIN_PASSWORD env var to override on restart")
        logger.warning(sep)


def get_secret_key() -> str:
    """Return secret key for session signing. Precedence: env > config > random (warns)."""
    if v := os.environ.get("SECRET_KEY"):
        return v
    if sk := get_secret_key_from_config():
        return sk
    # No key configured: derive a stable key from the config path so sessions
    # survive restarts, but document that this is not cryptographically ideal.
    logger.warning(
        "No SECRET_KEY configured — session key derived from config path. "
        "Set auth.secret_key in config.yaml or SECRET_KEY env var for production."
    )
    return hashlib.sha256(str(CONFIG_PATH.resolve()).encode()).hexdigest()


def require_auth(request: Request) -> None:
    """FastAPI dependency: raises 401 if the request has no valid session."""
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Authentication required")


_login_attempts: dict[str, collections.deque] = {}
_LOGIN_MAX = 10
_LOGIN_WINDOW = 60  # seconds


def login_rate_limit(ip: str) -> bool:
    """Return True if the IP is within the rate limit, False if blocked."""
    now = time.time()
    q = _login_attempts.setdefault(ip, collections.deque())
    while q and q[0] < now - _LOGIN_WINDOW:
        q.popleft()
    if len(q) >= _LOGIN_MAX:
        return False
    q.append(now)
    return True
