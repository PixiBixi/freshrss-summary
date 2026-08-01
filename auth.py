"""Authentication helpers: password hashing, session guards, rate limiting."""

import collections
import hashlib
import logging
import os
import secrets
import time

from fastapi import HTTPException, Request

from config import get_secret_key_from_config
from db import get_or_create_secret_key, get_user_hash, upsert_user

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
    except Exception:  # broad catch intentional: any malformed hash → reject
        return False


async def init_admin_user() -> None:
    """
    Ensure at least one user exists in DB.

    - If the user already exists in DB: keep the stored password (DB wins over env var).
    - Else if ADMIN_PASSWORD env var is set: create admin with that password.
    - Else: generate a random password, store it, log it.
    """
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")

    if await get_user_hash(admin_username):
        return

    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_password:
        await upsert_user(admin_username, hash_password(admin_password))
        logger.info("Admin user '%s' created from ADMIN_PASSWORD env var", admin_username)
    else:
        admin_password = secrets.token_urlsafe(16)
        await upsert_user(admin_username, hash_password(admin_password))
        sep = "=" * 56
        logger.warning(sep)
        logger.warning("  FIRST RUN — admin account created")
        logger.warning("  Username : %s", admin_username)
        logger.warning("  Password : %s", admin_password)
        logger.warning("  Set ADMIN_PASSWORD env var to set initial password")
        logger.warning(sep)


async def resolve_secret_key() -> str:
    """
    Return the secret key for session signing. Precedence: env > config > database.

    The database fallback generates a random key on first run and persists it, so
    sessions survive restarts. It must never be *derived* from something public:
    a key computed from the config path is identical on every installation, which
    lets anyone forge a signed session cookie and bypass authentication entirely.
    """
    if v := os.environ.get("SECRET_KEY"):
        return v
    if sk := get_secret_key_from_config():
        return sk
    logger.warning(
        "No SECRET_KEY configured — using a random key persisted in the database. "
        "Set SECRET_KEY or auth.secret_key to control it explicitly."
    )
    return await get_or_create_secret_key()


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
