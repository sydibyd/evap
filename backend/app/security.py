"""Authentication & authorization: PBKDF2 password hashes, JWT sessions, role checks,
per-project CI tokens and the internal runner token."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import GitIntegration, User

ROLES = ("engineer", "reviewer", "admin")
PBKDF2_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "role": user.role, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    token = _bearer(authorization)
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return user
    return checker


# Engineers write tests; reviewers approve; admins can do everything.
any_user = get_current_user
writer = require_roles("engineer", "reviewer", "admin")
reviewer = require_roles("reviewer", "admin")
admin = require_roles("admin")


# --- CI tokens (per project, only the SHA-256 hash is stored) ---------------
def new_ci_token() -> str:
    return "evapci_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_ci_integration(authorization: str | None = Header(default=None),
                       db: Session = Depends(get_db)) -> GitIntegration:
    token = _bearer(authorization)
    gi = db.scalar(select(GitIntegration).where(GitIntegration.ci_token_hash == hash_token(token)))
    if not gi:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid CI token")
    return gi


def require_runner(authorization: str | None = Header(default=None)) -> None:
    token = _bearer(authorization)
    if not hmac.compare_digest(token, get_settings().runner_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid runner token")
